"""Compare the legacy X02 reproduction with the frozen next-bar execution audit.

This is descriptive reporting only. It does not search parameters, change the
selection rule, or decide a new strategy after observing the stress-test result.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

OUT = Path("output/x02_reproduction_20260912")
LEGACY = OUT / "report.json"
STRESS = OUT / "next_bar_execution_audit.json"
OUTPUT_JSON = OUT / "next_bar_execution_comparison.json"
OUTPUT_MD = OUT / "next_bar_execution_comparison.md"

CORE_METRICS = ("total_return", "cagr", "max_drawdown", "sharpe", "active_days")
EXECUTION_METRICS = (
    "selection_rows", "filled_rows", "fill_rate", "cash_slots",
    "active_selection_days", "days_with_any_unfilled_slot",
)


def _num(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta(after: object, before: object) -> float | None:
    a = _num(after)
    b = _num(before)
    return None if a is None or b is None else a - b


def _positive_retention(after: object, before: object) -> float | None:
    a = _num(after)
    b = _num(before)
    if a is None or b is None or b <= 0:
        return None
    return a / b


def validate_lineage(legacy: dict[str, Any], stress: dict[str, Any], legacy_sha256: str | None = None) -> dict[str, object]:
    failures: list[str] = []
    inputs = stress.get("inputs") or {}
    legacy_features = legacy.get("features_sha256")
    legacy_engine = legacy.get("engine_sha256")
    if not legacy_features:
        failures.append("legacy report lacks features_sha256")
    if inputs.get("features_sha256") != legacy_features:
        failures.append("stress audit features hash does not match legacy report")
    if inputs.get("engine_sha256") != legacy_engine:
        failures.append("stress audit engine hash does not match legacy report")
    if legacy_sha256 is not None and inputs.get("report_sha256") != legacy_sha256:
        failures.append("stress audit report hash does not match the report.json being compared")
    return {"pass": not failures, "failures": failures}


def build_comparison(
    legacy: dict[str, Any],
    stress: dict[str, Any],
    legacy_sha256: str | None = None,
) -> dict[str, Any]:
    lineage = validate_lineage(legacy, stress, legacy_sha256)
    if not lineage["pass"]:
        raise ValueError("input lineage mismatch: " + "; ".join(lineage["failures"]))

    legacy_results = legacy.get("results", {})
    stress_results = stress.get("results", {})
    keys = sorted(set(legacy_results).intersection(stress_results))
    if not keys:
        raise ValueError("legacy and next-bar reports have no common result keys")

    comparison: dict[str, Any] = {
        "comparison": "X02_LEGACY_1445_CLOSE_VS_NEXT_BAR_OPEN_V2",
        "descriptive_only": True,
        "parameter_search": False,
        "lineage": lineage,
        "legacy_entry": legacy.get("contract", {}).get("entry", "14:45 close"),
        "stress_entry": stress.get("fill_proxy"),
        "bar_label_contract": stress.get("bar_label_contract"),
        "results": {},
        "interpretation_boundary": (
            "Deltas and retention ratios describe execution sensitivity only. They must not be used to retune the frozen signal, "
            "market gate, Top-N, limit buffer, or exit after observing the result."
        ),
    }

    for key in keys:
        legacy_periods = legacy_results[key]
        stress_periods = stress_results[key]
        periods = sorted(set(legacy_periods).intersection(stress_periods))
        comparison["results"][key] = {}
        for period in periods:
            old = legacy_periods[period]
            new = stress_periods[period]
            comparison["results"][key][period] = {
                "legacy": {name: old.get(name) for name in CORE_METRICS},
                "next_bar": {name: new.get(name) for name in CORE_METRICS},
                "delta": {
                    "total_return": _delta(new.get("total_return"), old.get("total_return")),
                    "cagr": _delta(new.get("cagr"), old.get("cagr")),
                    "max_drawdown": _delta(new.get("max_drawdown"), old.get("max_drawdown")),
                    "sharpe": _delta(new.get("sharpe"), old.get("sharpe")),
                },
                "positive_metric_retention": {
                    "total_return": _positive_retention(new.get("total_return"), old.get("total_return")),
                    "cagr": _positive_retention(new.get("cagr"), old.get("cagr")),
                    "sharpe": _positive_retention(new.get("sharpe"), old.get("sharpe")),
                },
                "execution": {name: new.get(name) for name in EXECUTION_METRICS},
            }
    return comparison


def _pct(value: object) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number:.2%}"


def _ratio(value: object) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number:.2f}x"


def render_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# X02 next-bar execution comparison",
        "",
        "Descriptive execution-sensitivity report only; no parameter search or post-result retuning is authorized.",
        "",
        "| Spec | Period | Legacy CAGR | Next-bar CAGR | CAGR retained | Δ CAGR | Legacy MDD | Next-bar MDD | Fill rate | Cash slots |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, periods in comparison["results"].items():
        for period, row in periods.items():
            old = row["legacy"]
            new = row["next_bar"]
            delta = row["delta"]
            retention = row["positive_metric_retention"]
            execution = row["execution"]
            lines.append(
                "| " + " | ".join([
                    key, period, _pct(old.get("cagr")), _pct(new.get("cagr")),
                    _ratio(retention.get("cagr")), _pct(delta.get("cagr")),
                    _pct(old.get("max_drawdown")), _pct(new.get("max_drawdown")),
                    _pct(execution.get("fill_rate")), str(execution.get("cash_slots", "n/a")),
                ]) + " |"
            )
    lines.extend([
        "", "## Reading the deltas", "",
        "CAGR retained is shown only when legacy CAGR is positive; negative-development periods deliberately show n/a rather than a misleading ratio. "
        "A lower fill rate or many cash slots identifies where next-record executability, rather than signal ranking, removes exposure. "
        "Max-drawdown deltas use the legacy engine's metric definition for apples-to-apples comparison.", "",
    ])
    return "\n".join(lines)


def main() -> None:
    if not LEGACY.exists() or not STRESS.exists():
        raise SystemExit("run reproduce_x02_local.py and audit_x02_next_bar_execution.py first")
    legacy = json.loads(LEGACY.read_text(encoding="utf-8"))
    stress = json.loads(STRESS.read_text(encoding="utf-8"))
    comparison = build_comparison(legacy, stress, sha256_file(LEGACY))
    OUTPUT_JSON.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(render_markdown(comparison), encoding="utf-8")
    print(render_markdown(comparison))


if __name__ == "__main__":
    main()
