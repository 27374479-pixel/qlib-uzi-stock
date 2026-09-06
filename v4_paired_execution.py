"""V4.1 leakage-safe paired 5-minute execution validation.

This tests the exact quantity that made the two v3 challengers pass:
selected minus control, not selected-side absolute return.

For an executable entry on trading day T, both frozen daily masks are evaluated
on T-1 and carried forward to T.  Both sides must meet the same minute-data
coverage threshold.  Returns are equal-weighted within side, then paired by
trade date and bootstrapped by date.
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
    return pd.concat(pieces, ignore_index=True).drop_duplicates()


def write_paired_codes(frame: pd.DataFrame, sample_start: str) -> pd.DataFrame:
    rows = build_side_rows(frame)
    rows = rows[pd.to_datetime(rows["date"]) >= pd.Timestamp(sample_start)].copy()
    codes = sorted(rows["instrument"].astype(str).unique())
    OUT_DIR.mkdir(exist_ok=True)
    PAIRED_CODES.write_text("\n".join(codes) + "\n", encoding="utf-8")
    print("paired instruments", len(codes), flush=True)
    print("paired candidate-side rows", len(rows), flush=True)
    for module in MODULE_MAP:
        m = rows[rows["module"] == module]
        print(module, {
            side: {"rows": int(len(g)), "instruments": int(g["instrument"].nunique()), "dates": int(g["date"].nunique())}
            for side, g in m.groupby("side")
        }, flush=True)
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
        except Exception:
            continue
        if not p.empty:
            pieces.append(p)
    if not pieces:
        return None
    try:
        return base._normalize_minute(pd.concat(pieces, ignore_index=True, sort=False))
    except Exception:
        return None


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
    # Provider first, canonical TraderHarness second on overlap; provider can extend recent dates.
    x = pd.concat(pieces, ignore_index=True, sort=False)
    x = x.drop_duplicates(subset=["datetime"], keep="last").sort_values("datetime")
    try:
        x = base._normalize_minute(x)
    except Exception:
        cache[instrument] = pd.DataFrame()
        return None
    cache[instrument] = x
    return x


def _return_for_name(minute: pd.DataFrame, date: pd.Timestamp, next_date: pd.Timestamp,
                     entry_time: str, exit_time: str, cost: float) -> float | None:
    entry = base._bar_price(minute, date, entry_time, "entry")
    exit_price = base._bar_price(minute, next_date, exit_time, "exit")
    if entry is None or exit_price is None or not np.isfinite(entry) or not np.isfinite(exit_price) or entry <= 0:
        return None
    return float(exit_price / entry - 1.0 - cost)


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
        return {"n_dates": 0}
    x = df["spread"].to_numpy(float)
    out = {
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
    return out


def run(cfg: Config) -> dict[str, Any]:
    # survivor.prepare is the canonical frozen daily challenger frame.
    daily_cfg = base.Config(start=cfg.start, end=cfg.end, bootstrap_samples=cfg.bootstrap_samples, seed=cfg.seed)
    frame = survivor.prepare(daily_cfg)
    side_rows = write_paired_codes(frame, cfg.sample_start)

    dates = [pd.Timestamp(x).normalize() for x in sorted(pd.to_datetime(frame["date"]).dt.normalize().unique())]
    nxt = {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}
    cache: dict[str, pd.DataFrame] = {}
    cost = cfg.buy_cost + cfg.sell_cost
    report: dict[str, Any] = {
        "config": asdict(cfg),
        "methodology": {
            "signal_timing": "frozen X01/X02 selected and control masks evaluated on T-1, executed on T",
            "pairing": "equal-weight selected minus equal-weight control on the same trade date",
            "coverage": "both sides must independently have at least min_side_size complete entry+exit names",
            "bootstrap_unit": "trade date",
            "cost_per_side": cost,
            "availability_rule": "same TraderHarness/provider availability rule for both sides; no return-conditioned filtering",
        },
        "modules": {},
    }

    for mi, module in enumerate(MODULE_MAP):
        module_rows = side_rows[side_rows["module"] == module]
        eligible_dates = sorted(pd.to_datetime(module_rows["date"]).dt.normalize().unique())
        module_out: dict[str, Any] = {"eligible_signal_dates": int(len(eligible_dates)), "thresholds": {}}
        for threshold in cfg.min_side_sizes:
            threshold_out: dict[str, Any] = {}
            for ei, entry_time in enumerate(cfg.entry_times):
                entry_out: dict[str, Any] = {}
                for xi, exit_time in enumerate(cfg.exit_times):
                    records = []
                    for raw_date in eligible_dates:
                        date = pd.Timestamp(raw_date).normalize()
                        next_date = nxt.get(date)
                        if next_date is None:
                            continue
                        day_rows = module_rows[pd.to_datetime(module_rows["date"]).dt.normalize() == date]
                        side_returns: dict[str, list[float]] = {"selected": [], "control": []}
                        raw_counts = {"selected": 0, "control": 0}
                        for side in ("selected", "control"):
                            names = day_rows.loc[day_rows["side"] == side, "instrument"].astype(str).drop_duplicates().tolist()
                            raw_counts[side] = len(names)
                            for instrument in names:
                                minute = load_minute(instrument, cache)
                                if minute is None:
                                    continue
                                ret = _return_for_name(minute, date, next_date, entry_time, exit_time, cost)
                                if ret is not None and np.isfinite(ret):
                                    side_returns[side].append(ret)
                        ns, nc = len(side_returns["selected"]), len(side_returns["control"])
                        if ns < threshold or nc < threshold:
                            continue
                        sr, cr = float(np.mean(side_returns["selected"])), float(np.mean(side_returns["control"]))
                        records.append({
                            "date": str(date.date()),
                            "selected_return": sr,
                            "control_return": cr,
                            "spread": sr - cr,
                            "selected_n": ns,
                            "control_n": nc,
                            "selected_raw_n": raw_counts["selected"],
                            "control_raw_n": raw_counts["control"],
                        })
                    df = pd.DataFrame(records)
                    summary = _summary(df, cfg, cfg.seed + mi * 1000 + threshold * 100 + ei * 10 + xi)
                    summary["coverage_fraction"] = float(len(df) / len(eligible_dates)) if eligible_dates else 0.0
                    entry_out[exit_time] = summary
                threshold_out[entry_time] = entry_out
            module_out["thresholds"][str(threshold)] = threshold_out
        report["modules"][module] = module_out

    out = ROOT / cfg.output
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    concise = {}
    for module, m in report["modules"].items():
        concise[module] = {}
        for threshold, tt in m["thresholds"].items():
            concise[module][threshold] = {
                f"{entry}->{exit_}": stats
                for entry, exits in tt.items() for exit_, stats in exits.items()
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
