"""Apply sample-size and stability gates to V4.1 paired execution results.

The effective independent sample is the paired TRADE DATE, not every stock,
because stocks on the same market date are strongly correlated. A pretty
mean/win-rate from too few dates is never allowed to become a PASS.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "output" / "v4_paired_execution.json"
OUTPUT = ROOT / "output" / "v4_paired_evidence_gate.json"

FORMAL_MIN_DATES = 120
SUGGESTIVE_MIN_DATES = 60
MIN_HALF_YEARS = 3
MIN_COVERAGE = 0.25


def classify(stats: dict) -> dict:
    n = int(stats.get("n_dates") or 0)
    win_rate = stats.get("win_rate")
    wins = int(round(n * float(win_rate))) if n and win_rate is not None else 0
    losses_or_ties = max(0, n - wins)
    ci = stats.get("bootstrap95") or [None, None]
    low = ci[0] if len(ci) > 0 else None
    high = ci[1] if len(ci) > 1 else None
    mean = stats.get("mean_spread")
    coverage = float(stats.get("coverage_fraction") or 0.0)
    half = stats.get("half_year") or {}
    half_total = int(half.get("total") or 0)
    half_positive = int(half.get("positive") or 0)
    required_positive_half = math.ceil((2.0 / 3.0) * half_total) if half_total else 0

    sample_tier = (
        "FORMAL" if n >= FORMAL_MIN_DATES
        else "SUGGESTIVE" if n >= SUGGESTIVE_MIN_DATES
        else "INSUFFICIENT"
    )

    hard_sample_ok = (
        n >= FORMAL_MIN_DATES
        and coverage >= MIN_COVERAGE
        and half_total >= MIN_HALF_YEARS
    )
    stability_ok = half_total >= MIN_HALF_YEARS and half_positive >= required_positive_half
    positive_ci = low is not None and float(low) > 0
    negative_ci = high is not None and float(high) < 0

    if not hard_sample_ok:
        verdict = "INSUFFICIENT_SAMPLE" if n < FORMAL_MIN_DATES else "INSUFFICIENT_COVERAGE"
    elif positive_ci and stability_ok and mean is not None and float(mean) > 0:
        verdict = "PASS"
    elif negative_ci and mean is not None and float(mean) < 0:
        verdict = "FAIL"
    else:
        verdict = "INCONCLUSIVE"

    return {
        "verdict": verdict,
        "sample_tier": sample_tier,
        "paired_dates": n,
        "positive_paired_dates": wins,
        "non_positive_paired_dates": losses_or_ties,
        "win_rate": win_rate,
        "coverage_fraction": coverage,
        "mean_spread": mean,
        "bootstrap95": ci,
        "half_year_positive": half_positive,
        "half_year_total": half_total,
        "minimums": {
            "formal_min_paired_dates": FORMAL_MIN_DATES,
            "suggestive_min_paired_dates": SUGGESTIVE_MIN_DATES,
            "min_half_years": MIN_HALF_YEARS,
            "min_coverage_fraction": MIN_COVERAGE,
        },
        "notes": [
            "paired trade dates are treated as the primary independent hit count",
            "same-day stock observations are not counted as independent hits",
            "results below 120 paired dates cannot PASS regardless of mean return or win rate",
        ],
    }


def main() -> None:
    report = json.loads(INPUT.read_text(encoding="utf-8"))
    out = {
        "source": str(INPUT.relative_to(ROOT)),
        "principle": "sample size first; no low-count result can be promoted to alpha",
        "gates": {
            "formal_min_paired_dates": FORMAL_MIN_DATES,
            "suggestive_min_paired_dates": SUGGESTIVE_MIN_DATES,
            "min_half_years": MIN_HALF_YEARS,
            "min_coverage_fraction": MIN_COVERAGE,
            "pass_requires": "formal sample + >=2/3 positive half-years + bootstrap95 lower bound > 0",
        },
        "modules": {},
    }
    for module, module_data in report.get("modules", {}).items():
        mout = {"eligible_signal_dates": module_data.get("eligible_signal_dates"), "thresholds": {}}
        for threshold, entries in module_data.get("thresholds", {}).items():
            tout = {}
            for entry_time, exits in entries.items():
                tout[entry_time] = {exit_time: classify(stats) for exit_time, stats in exits.items()}
            mout["thresholds"][threshold] = tout
        out["modules"][module] = mout

    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
