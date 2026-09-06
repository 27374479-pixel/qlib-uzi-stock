"""V4.1 leakage-safe paired 5-minute execution validation.

This tests the exact quantity that made the two v3 challengers pass:
selected minus control, not selected-side absolute return.

For an executable entry on trading day T, both frozen daily masks are evaluated
on T-1 and carried forward to T. Both sides use the same data-availability rule.
Returns are equal-weighted within side, paired by trade date, and bootstrapped
by trade date. No factor thresholds are tuned here.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import v4_intraday_survivor_validation as base
import v4_survivor_wrapper as survivor
from external_challenger_daily_screen import challenger_masks

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output"
PAIRED_CODES = OUT_DIR / "v4_paired_codes.txt"
PAIRED_MINUTE_FILES = (
    ROOT / "data_lake" / "raw" / "traderharness" / "paired_5min_2025.parquet",
    ROOT / "data_lake" / "raw" / "traderharness" / "paired_5min_2026.parquet",
)
MODULE_MAP = survivor.MAP


@dataclass(frozen=True)
class Config:
    start: str = "2015-01-01"
    end: str = "2026-09-03"
    sample_start: str = "2025-01-02"
    entry_times: tuple[str, ...] = ("14:30", "14:45", "14:55")
    exit_times: tuple[str, ...] = ("09:30", "10:00", "15:00")
    min_side_sizes: tuple[int, ...] = (5, 10)
    buy_cost: float = 0.0003
    sell_cost: float = 0.0013
    bootstrap_samples: int = 5000
    seed: int = 20260906
    output: str = "output/v4_paired_execution.json"


def _next_date_map(frame: pd.DataFrame) -> dict[pd.Timestamp, pd.Timestamp]:
    dates = sorted(pd.to_datetime(frame["date"]).dt.normalize().drop_duplicates())
    return {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}


def build_side_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Lag frozen selected/control masks one global trading day."""
    masks = challenger_masks(frame)
    nxt = _next_date_map(frame)
    pieces: list[pd.DataFrame] = []
    for module, challenger_id in MODULE_MAP.items():
        spec = masks[challenger_id]
        selected_mask = spec["selected"].fillna(False)
        control_mask = spec["control"].fillna(False) & ~selected_mask
        for side, mask in (("selected", selected_mask), ("control", control_mask)):
            x = frame.loc[mask, ["date", "instrument"]].copy()
            x["signal_date"] = pd.to_datetime(x["date"]).dt.normalize()
            x["date"] = x["signal_date"].map(nxt)
            x = x.dropna(subset=["date"])
            x["module"] = module
            x["side"] = side
            pieces.append(x[["date", "signal_date", "instrument", "module", "side"]])
    if not pieces:
        return pd.DataFrame(columns=["date", "signal_date", "instrument", "module", "side"])
    out = pd.concat(pieces, ignore_index=True).drop_duplicates()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out["signal_date"] = pd.to_datetime(out["signal_date"]).dt.normalize()
    return out


def write_paired_codes(frame: pd.DataFrame, sample_start: str) -> pd.DataFrame:
    rows = build_side_rows(frame)
    rows = rows[rows["date"] >= pd.Timestamp(sample_start)].copy()
    codes = sorted(rows["instrument"].astype(str).unique())
    OUT_DIR.mkdir(exist_ok=True)
    PAIRED_CODES.write_text("\n".join(codes) + "\n", encoding="utf-8")
    print("paired instruments", len(codes), flush=True)
    print("paired candidate-side rows", len(rows), flush=True)
    for module in MODULE_MAP:
        m = rows[rows["module"] == module]
        details = {
            side: {
                "rows": int(len(g)),
                "instruments": int(g["instrument"].nunique()),
                "dates": int(g["date"].nunique()),
            }
            for side, g in m.groupby("side")
        }
        print(module, json.dumps(details, ensure_ascii=False), flush=True)
    return rows


def _provider_minute(instrument: str) -> pd.DataFrame | None:
    frame = base._load_minute(instrument, {})
    if frame is None or frame.empty or "datetime" not in frame.columns:
        return None
    return frame


def _paired_history(instrument: str) -> pd.DataFrame | None:
    pieces = []
    for path in PAIRED_MINUTE_FILES:
        if not path.exists():
            continue
        try:
            p = pd.read_parquet(
                path,
                filters=[("instrument", "=", instrument)],
                columns=["instrument", "datetime", "open", "high", "low", "close", "volume", "amount", "source"],
            )
        except Exception as exc:
            print(f"paired TraderHarness read failed {instrument} {path.name}: {exc}", flush=True)
            continue
        if not p.empty:
            pieces.append(p)
    if not pieces:
        return None
    try:
        x = base._normalize_minute(pd.concat(pieces, ignore_index=True, sort=False))
    except Exception:
        return None
    return x if not x.empty else None


def load_minute(instrument: str, cache: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    if instrument in cache:
        x = cache[instrument]
        return x if not x.empty and "datetime" in x.columns else None
    hist = _paired_history(instrument)
    provider = _provider_minute(instrument)
    pieces = [x for x in (provider, hist) if x is not None and not x.empty and "datetime" in x.columns]
    if not pieces:
        cache[instrument] = pd.DataFrame()
        return None
    # Provider first, TraderHarness second => canonical TraderHarness wins on overlap,
    # while provider-only recent dates are retained.
    x = pd.concat(pieces, ignore_index=True, sort=False)
    x = x.drop_duplicates(subset=["datetime"], keep="last").sort_values("datetime")
    try:
        x = base._normalize_minute(x)
    except Exception:
        cache[instrument] = pd.DataFrame()
        return None
    cache[instrument] = x
    return x if not x.empty else None


def _prices_for_name(
    minute: pd.DataFrame,
    date: pd.Timestamp,
    next_date: pd.Timestamp,
    entry_time: str,
    exit_times: tuple[str, ...],
    cost: float,
) -> dict[str, float]:
    entry = base._bar_price(minute, date, entry_time, "entry")
    if entry is None or not np.isfinite(entry) or entry <= 0:
        return {}
    out: dict[str, float] = {}
    for exit_time in exit_times:
        px = base._bar_price(minute, next_date, exit_time, "exit")
        if px is not None and np.isfinite(px):
            out[exit_time] = float(px / entry - 1.0 - cost)
    return out


def _bootstrap(values: np.ndarray, n: int, seed: int) -> list[float | None]:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 8:
        return [None, None]
    rng = np.random.default_rng(seed)
    means = np.empty(n)
    for i in range(n):
        means[i] = rng.choice(x, size=len(x), replace=True).mean()
    return [float(np.quantile(means, .025)), float(np.quantile(means, .975))]


def _half_year_stats(dates: pd.Series, spreads: pd.Series) -> dict[str, Any]:
    d = pd.to_datetime(dates)
    labels = d.dt.year.astype(str) + "H" + np.where(d.dt.month <= 6, "1", "2")
    tmp = pd.DataFrame({"half": labels, "spread": pd.to_numeric(spreads, errors="coerce")}).dropna()
    means = tmp.groupby("half")["spread"].mean().to_dict()
    return {
        "means": {str(k): float(v) for k, v in means.items()},
        "positive": int(sum(v > 0 for v in means.values())),
        "total": int(len(means)),
    }


def _summary(df: pd.DataFrame, cfg: Config, seed: int) -> dict[str, Any]:
    if df.empty:
        return {
            "n_dates": 0,
            "mean_spread": None,
            "median_spread": None,
            "win_rate": None,
            "bootstrap95": [None, None],
        }
    x = pd.to_numeric(df["spread"], errors="coerce").dropna().to_numpy(float)
    return {
        "n_dates": int(len(df)),
        "mean_spread": float(np.mean(x)),
        "median_spread": float(np.median(x)),
        "win_rate": float(np.mean(x > 0)),
        "bootstrap95": _bootstrap(x, cfg.bootstrap_samples, seed),
        "selected_mean": float(df["selected_return"].mean()),
        "control_mean": float(df["control_return"].mean()),
        "selected_names_median": float(df["selected_n"].median()),
        "control_names_median": float(df["control_n"].median()),
        "half_year": _half_year_stats(df["date"], df["spread"]),
    }


def run(cfg: Config) -> dict[str, Any]:
    daily_cfg = base.Config(
        start=cfg.start,
        end=cfg.end,
        bootstrap_samples=cfg.bootstrap_samples,
        seed=cfg.seed,
    )
    frame = survivor.prepare(daily_cfg)
    side_rows = write_paired_codes(frame, cfg.sample_start)

    trading_dates = [pd.Timestamp(x).normalize() for x in sorted(pd.to_datetime(frame["date"]).dt.normalize().unique())]
    next_date = {trading_dates[i]: trading_dates[i + 1] for i in range(len(trading_dates) - 1)}
    cache: dict[str, pd.DataFrame] = {}
    cost = cfg.buy_cost + cfg.sell_cost
    report: dict[str, Any] = {
        "config": asdict(cfg),
        "methodology": {
            "signal_timing": "frozen X01/X02 selected and control masks evaluated on T-1, executed on T",
            "pairing": "same-date equal-weight selected return minus equal-weight control return",
            "coverage": "both sides independently require min_side_size complete names for the exact entry+exit window",
            "bootstrap_unit": "trade date",
            "cost_per_side": cost,
            "spread_cost_note": "identical round-trip cost is charged to both sides; therefore it cancels in selected-control spread but remains in side absolute returns",
            "availability_rule": "same TraderHarness/provider availability rule for both sides; no future-return-conditioned filtering",
        },
        "modules": {},
    }

    for mi, module in enumerate(MODULE_MAP):
        mrows = side_rows[side_rows["module"] == module].copy()
        groups = {pd.Timestamp(d).normalize(): g for d, g in mrows.groupby("date", sort=True)}
        eligible_dates = sorted(groups)
        module_out: dict[str, Any] = {
            "eligible_signal_dates": int(len(eligible_dates)),
            "thresholds": {str(t): {} for t in cfg.min_side_sizes},
        }

        # Compute each entry/exit/name observation once. Threshold sensitivity is
        # applied afterwards, not by recomputing the same minute prices.
        for ei, entry_time in enumerate(cfg.entry_times):
            records_by_exit: dict[str, list[dict[str, Any]]] = {x: [] for x in cfg.exit_times}
            for date in eligible_dates:
                nd = next_date.get(date)
                if nd is None:
                    continue
                day = groups[date]
                names_by_side = {
                    side: day.loc[day["side"] == side, "instrument"].astype(str).drop_duplicates().tolist()
                    for side in ("selected", "control")
                }
                returns: dict[str, dict[str, list[float]]] = {
                    exit_time: {"selected": [], "control": []}
                    for exit_time in cfg.exit_times
                }
                for side in ("selected", "control"):
                    for instrument in names_by_side[side]:
                        minute = load_minute(instrument, cache)
                        if minute is None:
                            continue
                        vals = _prices_for_name(minute, date, nd, entry_time, cfg.exit_times, cost)
                        for exit_time, ret in vals.items():
                            returns[exit_time][side].append(ret)
                for exit_time in cfg.exit_times:
                    sr = returns[exit_time]["selected"]
                    cr = returns[exit_time]["control"]
                    if not sr or not cr:
                        continue
                    records_by_exit[exit_time].append({
                        "date": str(date.date()),
                        "selected_return": float(np.mean(sr)),
                        "control_return": float(np.mean(cr)),
                        "spread": float(np.mean(sr) - np.mean(cr)),
                        "selected_n": int(len(sr)),
                        "control_n": int(len(cr)),
                        "selected_raw_n": int(len(names_by_side["selected"])),
                        "control_raw_n": int(len(names_by_side["control"])),
                    })

            for threshold in cfg.min_side_sizes:
                threshold_key = str(threshold)
                module_out["thresholds"][threshold_key].setdefault(entry_time, {})
                for xi, exit_time in enumerate(cfg.exit_times):
                    raw_df = pd.DataFrame(records_by_exit[exit_time])
                    if raw_df.empty:
                        df = raw_df
                    else:
                        df = raw_df[(raw_df["selected_n"] >= threshold) & (raw_df["control_n"] >= threshold)].copy()
                    stats = _summary(df, cfg, cfg.seed + mi * 1000 + threshold * 100 + ei * 10 + xi)
                    stats["coverage_fraction"] = float(len(df) / len(eligible_dates)) if eligible_dates else 0.0
                    module_out["thresholds"][threshold_key][entry_time][exit_time] = stats

            print(f"completed {module} entry={entry_time} cache={len(cache)}", flush=True)
        report["modules"][module] = module_out

    out = ROOT / cfg.output
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    concise: dict[str, Any] = {}
    for module, m in report["modules"].items():
        concise[module] = {}
        for threshold, entries in m["thresholds"].items():
            concise[module][threshold] = {
                f"{entry}->{exit_time}": stats
                for entry, exits in entries.items()
                for exit_time, stats in exits.items()
            }
    print(json.dumps(concise, ensure_ascii=False, indent=2), flush=True)
    return report


def parse_args() -> Config:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default=Config.start)
    p.add_argument("--end", default=Config.end)
    p.add_argument("--sample-start", default=Config.sample_start)
    p.add_argument("--entry-times", default=",".join(Config.entry_times))
    p.add_argument("--exit-times", default=",".join(Config.exit_times))
    p.add_argument("--min-side-sizes", default=",".join(map(str, Config.min_side_sizes)))
    p.add_argument("--bootstrap-samples", type=int, default=Config.bootstrap_samples)
    p.add_argument("--seed", type=int, default=Config.seed)
    p.add_argument("--output", default=Config.output)
    a = p.parse_args()
    return Config(
        start=a.start,
        end=a.end,
        sample_start=a.sample_start,
        entry_times=tuple(x.strip() for x in a.entry_times.split(",") if x.strip()),
        exit_times=tuple(x.strip() for x in a.exit_times.split(",") if x.strip()),
        min_side_sizes=tuple(int(x) for x in a.min_side_sizes.split(",") if x.strip()),
        bootstrap_samples=a.bootstrap_samples,
        seed=a.seed,
        output=a.output,
    )


if __name__ == "__main__":
    run(parse_args())
