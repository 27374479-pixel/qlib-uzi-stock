"""Anti-overfit diagnostics for persisted minute-backtest JSON outputs.

The report deliberately asks whether an apparent edge survives removing the
best trades, resampling uncertainty, different half-years, doubled costs and
execution delays.  It is a research diagnostic, not a performance optimizer.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HORIZONS = ("1d", "2d", "5d")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _trades(payload: dict[str, Any]) -> pd.DataFrame:
    frame = pd.DataFrame(payload.get("trades", []))
    if frame.empty:
        return frame
    frame["signal_date"] = pd.to_datetime(frame.get("signal_date"), errors="coerce").dt.normalize()
    for horizon in HORIZONS:
        column = f"return_{horizon}"
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _bootstrap_ci(values: np.ndarray, seed: int = 20260904, draws: int = 4000) -> list[float | None]:
    values = values[np.isfinite(values)]
    if len(values) < 5:
        return [None, None]
    rng = np.random.default_rng(seed)
    means = np.empty(draws, dtype=float)
    # Chunked indexing keeps memory small even when the final sample grows.
    for i in range(draws):
        means[i] = rng.choice(values, size=len(values), replace=True).mean()
    low, high = np.quantile(means, [0.025, 0.975])
    return [float(low), float(high)]


def _half_year(date: pd.Timestamp) -> str:
    return f"{date.year}-H{1 if date.month <= 6 else 2}"


def _series_stats(values: pd.Series, dates: pd.Series) -> dict[str, Any]:
    clean = pd.DataFrame({"value": pd.to_numeric(values, errors="coerce"), "date": dates}).dropna()
    if clean.empty:
        return {"count": 0}
    ordered = clean["value"].sort_values().reset_index(drop=True)
    n = len(ordered)
    remove_n = max(1, int(np.ceil(n * 0.05))) if n >= 10 else 1
    trimmed_best = ordered.iloc[: max(0, n - remove_n)]
    drop_best_one = ordered.iloc[:-1]
    positives = ordered.loc[ordered > 0]
    best5 = ordered.nlargest(min(5, n))

    buckets: dict[str, Any] = {}
    clean["half"] = clean["date"].map(_half_year)
    for label, group in clean.groupby("half", sort=True):
        buckets[str(label)] = {
            "count": int(len(group)),
            "mean": float(group["value"].mean()),
            "median": float(group["value"].median()),
            "win_rate": float((group["value"] > 0).mean()),
        }

    loo_means: list[float] = []
    for _, group in clean.groupby("date", sort=False):
        remaining = clean.drop(index=group.index)
        if not remaining.empty:
            loo_means.append(float(remaining["value"].mean()))

    half_means = [item["mean"] for item in buckets.values() if item["count"] >= 3]
    return {
        "count": n,
        "mean": float(ordered.mean()),
        "median": float(ordered.median()),
        "win_rate": float((ordered > 0).mean()),
        "worst": float(ordered.iloc[0]),
        "best": float(ordered.iloc[-1]),
        "bootstrap_mean_95ci": _bootstrap_ci(ordered.to_numpy(float)),
        "remove_best_5pct_count": int(remove_n),
        "mean_without_best_5pct": None if trimmed_best.empty else float(trimmed_best.mean()),
        "mean_without_best_trade": None if drop_best_one.empty else float(drop_best_one.mean()),
        "top5_share_of_positive_sum": (
            float(best5.clip(lower=0).sum() / positives.sum()) if positives.sum() > 0 else None
        ),
        "leave_one_signal_day_out_mean_min": min(loo_means) if loo_means else None,
        "leave_one_signal_day_out_mean_max": max(loo_means) if loo_means else None,
        "half_years": buckets,
        "half_years_with_3plus": len(half_means),
        "positive_half_year_share": (
            float(np.mean(np.asarray(half_means) > 0)) if half_means else None
        ),
    }


def _summarize(payload: dict[str, Any]) -> dict[str, Any]:
    frame = _trades(payload)
    result: dict[str, Any] = {
        "data_quality": payload.get("data_quality", {}),
        "methodology": payload.get("methodology", {}),
        "styles": {},
    }
    if frame.empty:
        return result
    for style, group in frame.groupby("style", sort=True):
        style_result: dict[str, Any] = {}
        for horizon in HORIZONS:
            column = f"return_{horizon}"
            if column in group:
                style_result[horizon] = _series_stats(group[column], group["signal_date"])
        result["styles"][str(style)] = style_result
    return result


def _label_path(text: str) -> tuple[str, Path]:
    if "=" not in text:
        raise argparse.ArgumentTypeError("variant must be LABEL=PATH")
    label, raw = text.split("=", 1)
    return label.strip(), Path(raw)


def _verdict(stats: dict[str, Any], variants: dict[str, dict[str, Any]], style: str, horizon: str) -> dict[str, Any]:
    base = stats.get("styles", {}).get(style, {}).get(horizon, {})
    n = int(base.get("count", 0) or 0)
    if n < 30:
        return {"rating": "INSUFFICIENT", "reason": "fewer than 30 executed trades"}
    ci = base.get("bootstrap_mean_95ci", [None, None])
    lower = ci[0] if isinstance(ci, list) and ci else None
    checks = {
        "baseline_mean_positive": (base.get("mean") or 0) > 0,
        "median_positive": (base.get("median") or 0) > 0,
        "bootstrap_lower_positive": lower is not None and lower > 0,
        "without_best_5pct_positive": (base.get("mean_without_best_5pct") or 0) > 0,
        "majority_half_years_positive": (base.get("positive_half_year_share") or 0) >= 0.60,
    }
    variant_means: dict[str, float | None] = {}
    for label, summary in variants.items():
        value = summary.get("styles", {}).get(style, {}).get(horizon, {}).get("mean")
        variant_means[label] = value
        if any(token in label.lower() for token in ("delay", "cost")):
            checks[f"{label}_positive"] = value is not None and value > 0
    passed = sum(bool(v) for v in checks.values())
    if all(checks.values()) and len(checks) >= 7:
        rating = "PASS"
    elif passed >= max(4, int(np.ceil(len(checks) * 0.65))):
        rating = "WEAK"
    else:
        rating = "FAIL"
    return {"rating": rating, "checks": checks, "variant_means": variant_means}


def main() -> None:
    parser = argparse.ArgumentParser(description="Robustness diagnostics for minute-backtest JSON")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--variant", action="append", default=[], type=_label_path)
    parser.add_argument("--focus-style", default="yangjia")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    baseline = _summarize(_load(args.baseline))
    variants: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for label, path in args.variant:
        if not path.exists():
            missing.append(f"{label}={path}")
            continue
        variants[label] = _summarize(_load(path))

    verdicts = {
        horizon: _verdict(baseline, variants, args.focus_style, horizon)
        for horizon in HORIZONS
        if horizon in baseline.get("styles", {}).get(args.focus_style, {})
    }
    report = {
        "baseline": str(args.baseline),
        "focus_style": args.focus_style,
        "baseline_summary": baseline,
        "variants": variants,
        "missing_variants": missing,
        "focus_verdicts": verdicts,
        "interpretation": {
            "PASS": "positive edge survives resampling, best-trade removal, time splits, cost and delay stresses",
            "WEAK": "some positive evidence exists but one or more robustness checks fail",
            "FAIL": "apparent edge does not survive basic anti-overfit checks",
            "INSUFFICIENT": "sample is too small for a serious claim",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"focus_verdicts": verdicts, "missing_variants": missing}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
