"""Compare the legacy X02 reproduction with the frozen next-bar execution audit.

This is descriptive reporting only. It does not search parameters, change the
selection rule, or decide a new strategy after observing the stress-test result.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path("output/x02_reproduction_20260912")
LEGACY = OUT / "report.json"
STRESS = OUT / "next_bar_execution_audit.json"
OUTPUT_JSON = OUT / "next_bar_execution_comparison.json"
OUTPUT_MD = OUT / "next_bar_execution_comparison.md"

CORE_METRICS = ("total_return", "cagr", "max_drawdown", "sharpe", "active_days")
EXECUTION_METRICS = (
    "selection_rows",
    "filled_rows",
    "fill_rate",
    "cash_slots",
    "active_selection_days",
    "days_with_any_unfilled_slot",
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


def build_comparison(legacy: dict[str, Any], stress: dict[str, Any]) -> dict[str, Any]:
    legacy_results = legacy.get("results", {})
    stress_results = stress.get("results", {})
    keys = sorted(set(legacy_results).intersection(stress_results))
    if not keys:
        raise ValueError("legacy and next-bar reports have no common result keys")

    comparison: dict[str, Any] = {
        "comparison": "X02_LEGACY_1445_CLOSE_VS_NEXT_BAR_OPEN_V1",
        "descriptive_only": True,
        "parameter_search": False,
        "legacy_entry": legacy.get("contract", {}).get("entry", "14:45 close"),
        "stress_entry": stress.get("fill_proxy"),
        "bar_label_contract": stress.get("bar_label_contract"),
        "results": {},
        "interpretation_boundary": (
            "Deltas describe execution sensitivity only. They must not be used to retune the frozen signal, "
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
            row: dict[str, Any] = {
                "legacy": {name: old.get(name) for name in CORE_METRICS},
                "next_bar": {name: new.get(name) for name in CORE_METRICS},
                "delta": {
                    "total_return": _delta(new.get("total_return"), old.get("total_return")),
                    "cagr": _delta(new.get("cagr"), old.get("cagr")),
                    "max_drawdown": _delta(new.get("max_drawdown"), old.get("max_drawdown")),
                    "sharpe": _delta(new.get("sharpe"), old.get("sharpe")),
                },
                "execution": {name: new.get(name) for name in EXECUTION_METRICS},
            }
            comparison["results"][key][period] = row
    return comparison


def _pct(value: object) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number:.2%}"


def _flt(value: object) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number:.3f}"


def render_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# X02 next-bar execution comparison",
        "",
        "Descriptive execution-sensitivity report only; no parameter search or post-result retuning is authorized.",
        "",
        "| Spec | Period | Legacy CAGR | Next-bar CAGR | Δ CAGR | Legacy MDD | Next-bar MDD | Fill rate | Cash slots |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, periods in comparison["results"].items():
        for period, row in periods.items():
            old = row["legacy"]
            new = row["next_bar"]
            delta = row["delta"]
            execution = row["execution"]
            lines.append(
                "| " + " | ".join(
                    [
                        key,
                        period,
                        _pct(old.get("cagr")),
                        _pct(new.get("cagr")),
                        _pct(delta.get("cagr")),
                        _pct(old.get("max_drawdown")),
                        _pct(new.get("max_drawdown")),
                        _pct(execution.get("fill_rate")),
                        str(execution.get("cash_slots", "n/a")),
                    ]
                ) + " |"
            )
    lines.extend(
        [
            "",
            "## Reading the deltas",
            "",
            "A more negative Δ CAGR means the legacy result was sensitive to the 14:45-close fill assumption. "
            "A lower fill rate or many cash slots identifies where next-bar executability, rather than signal ranking, "
            "is removing exposure. Max-drawdown deltas use the legacy engine's metric definition for apples-to-apples comparison.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    if not LEGACY.exists() or not STRESS.exists():
        raise SystemExit("run reproduce_x02_local.py and audit_x02_next_bar_execution.py first")
    legacy = json.loads(LEGACY.read_text(encoding="utf-8"))
    stress = json.loads(STRESS.read_text(encoding="utf-8"))
    comparison = build_comparison(legacy, stress)
    OUTPUT_JSON.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(render_markdown(comparison), encoding="utf-8")
    print(render_markdown(comparison))


if __name__ == "__main__":
    main()
