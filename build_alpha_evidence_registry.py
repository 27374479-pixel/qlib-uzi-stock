"""Synthesize independent screens into an auditable alpha-module registry.

This script does not optimize a strategy. It reads frozen outputs from:
- book_alpha_daily_screen_v3.json
- attention_timing_decomposition_v1.json
- external_challenger_daily_screen_v1.json

and turns them into promotion/rejection states for later minute validation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

BOOK_TO_MODULE = {
    "H01": "NO_TRADE_WEAK",
    "H02": "PANIC_REPAIR",
    "H03": "CLIMAX_AVOIDANCE",
    "H04": "NEW_EVENT_PROBE",
    "H05": "BREADTH_WITH_LEADER",
    "H06": "POST_DIVERGENCE_REPAIR",
    "H07": "DIVERGENCE_SURVIVOR",
    "H08": "ROLE_PERSISTENCE",
    "H10": "AMOUNT_ACCELERATION",
    "H11": "TURNOVER_SWEET_SPOT",
    "H13": "LOW_PRICE_PLACEBO",
    "H14": "HIGH_VOLUME_DIVERGENCE",
    "H15": "TREND_PULLBACK",
}

MINUTE_REQUIRED = {"H02", "H06", "H07", "H14", "H15"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def challenger_verdict(item: dict[str, Any]) -> str:
    oos = item.get("oos", {}).get("2d", {})
    selected = oos.get("selected", {})
    paired = oos.get("paired", {})
    n = int(selected.get("n", 0) or 0)
    days = int(paired.get("paired_days", 0) or 0)
    diff = paired.get("expected_signed_difference")
    ci = paired.get("bootstrap95_expected_signed_difference") or [None, None]
    if n < 50 or days < 20:
        return "INSUFFICIENT"
    if diff is None or diff <= 0:
        return "FAIL"
    if ci[0] is not None and ci[0] > 0:
        return "PASS"
    return "PROMISING"


def build(book: dict[str, Any], timing: dict[str, Any], external: dict[str, Any]) -> dict[str, Any]:
    modules: dict[str, Any] = {}
    for hypothesis_id, item in book.get("hypotheses", {}).items():
        module = BOOK_TO_MODULE.get(hypothesis_id, hypothesis_id)
        verdict = item.get("overall_verdict", "UNKNOWN")
        minute = bool(item.get("minute_required", hypothesis_id in MINUTE_REQUIRED))
        if verdict == "PASS":
            promotion = "MINUTE_VALIDATION_REQUIRED" if minute else "DAILY_PASS"
        elif verdict == "PROMISING":
            promotion = "PROMISING_RETEST"
        elif verdict.startswith("INSUFFICIENT"):
            promotion = "INSUFFICIENT"
        elif verdict.startswith("WEAK"):
            promotion = "WEAK_NOT_ADMITTED"
        else:
            promotion = "REJECTED"
        modules[module] = {
            "source": "48_trader_books",
            "hypothesis_id": hypothesis_id,
            "daily_verdict": verdict,
            "promotion": promotion,
            "minute_required": minute,
            "oos_2d": item.get("oos", {}).get("2d", {}),
        }

    challenger_modules = {
        "X01_attention_saturation": "ATTENTION_SATURATION_VETO",
        "X02_limit_adjusted_momentum": "LIMIT_ADJUSTED_MOMENTUM",
        "X04_lottery_crowding_veto": "LOTTERY_CROWDING_VETO",
    }
    for key, module in challenger_modules.items():
        item = external.get("challengers", {}).get(key, {})
        verdict = challenger_verdict(item) if item else "MISSING"
        modules[module] = {
            "source": "external_A_share_evidence_challenger",
            "challenger_id": key,
            "daily_verdict": verdict,
            "promotion": "DAILY_PASS" if verdict == "PASS" else ("PROMISING_RETEST" if verdict == "PROMISING" else "REJECTED"),
            "minute_required": False,
            "oos_2d": item.get("oos", {}).get("2d", {}) if item else {},
        }

    timing_map = {
        "current_touch_any": "LIMIT_TOUCH_STATE",
        "current_first_touch20": "FIRST_ATTENTION_STATE",
        "current_repeated_touch20_ge3": "REPEATED_ATTENTION_STATE",
        "current_seal": "SEALED_LIMIT_STATE",
        "active_core": "ACTIVE_CORE_STATE",
        "divergence_survivor": "DIVERGENCE_SURVIVOR_TIMING",
        "climax_core": "CLIMAX_CORE_TIMING",
        "repair_core": "REPAIR_CORE_TIMING",
    }
    timing_evidence: dict[str, Any] = {}
    for cohort, label in timing_map.items():
        item = timing.get("cohorts", {}).get(cohort, {}).get("oos", {})
        if not item:
            continue
        timing_evidence[label] = {
            "classification": item.get("timing_classification"),
            "overnight_gap": item.get("overnight_gap"),
            "post_open_1d": item.get("post_open_1d"),
        }

    # Timing evidence can veto a daily new-entry interpretation without saying
    # the state itself is useless. It may remain valuable for T-day existing
    # positions or for finding an earlier intraday trigger.
    for module_name in ("BREADTH_WITH_LEADER", "ROLE_PERSISTENCE", "AMOUNT_ACCELERATION"):
        if module_name not in modules:
            continue
        core_timing = timing_evidence.get("ACTIVE_CORE_STATE", {})
        if core_timing.get("classification") == "PRE_ENTRY_PREMIUM_ONLY" and modules[module_name]["promotion"] == "DAILY_PASS":
            modules[module_name]["promotion"] = "EARLIER_ENTRY_REQUIRED"
            modules[module_name]["timing_veto"] = "active-core edge appears before next executable open"

    admitted = [name for name, item in modules.items() if item["promotion"] in {"DAILY_PASS", "MINUTE_VALIDATION_REQUIRED", "EARLIER_ENTRY_REQUIRED"}]
    promising = [name for name, item in modules.items() if item["promotion"] == "PROMISING_RETEST"]
    rejected = [name for name, item in modules.items() if item["promotion"] in {"REJECTED", "WEAK_NOT_ADMITTED"}]
    return {
        "policy": {
            "people_are_provenance_not_votes": True,
            "daily_pass_does_not_equal_trade_ready": True,
            "minute_required_modules_must_pass_fixed_signal_execution": True,
            "pre_entry_premium_cannot_be_counted_as_next_open_entry_alpha": True,
        },
        "modules": modules,
        "timing_evidence": timing_evidence,
        "admitted_or_next_stage": admitted,
        "promising_retest": promising,
        "rejected": rejected,
    }


def markdown(registry: dict[str, Any]) -> str:
    lines = [
        "# Alpha Evidence Registry v1",
        "",
        "人物与书籍只记录来源，模块是否保留由样本外证据决定。日线通过不等于可实盘；需分钟执行的模块必须再通过真实成交测试。",
        "",
        "| Module | Source | Daily verdict | Promotion |",
        "|---|---|---|---|",
    ]
    for name, item in sorted(registry["modules"].items()):
        lines.append(f"| `{name}` | {item.get('source')} | {item.get('daily_verdict')} | **{item.get('promotion')}** |")
    lines.extend(["", "## Timing evidence", ""])
    for name, item in sorted(registry.get("timing_evidence", {}).items()):
        lines.append(f"- `{name}`: **{item.get('classification')}**")
    lines.extend([
        "",
        "## Next-stage modules",
        "",
        ", ".join(f"`{x}`" for x in registry.get("admitted_or_next_stage", [])) or "None",
        "",
        "## Promising but not admitted",
        "",
        ", ".join(f"`{x}`" for x in registry.get("promising_retest", [])) or "None",
        "",
        "## Rejected / weak",
        "",
        ", ".join(f"`{x}`" for x in registry.get("rejected", [])) or "None",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", type=Path, default=ROOT / "output/book_alpha_daily_screen_v3.json")
    parser.add_argument("--timing", type=Path, default=ROOT / "output/attention_timing_decomposition_v1.json")
    parser.add_argument("--external", type=Path, default=ROOT / "output/external_challenger_daily_screen_v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "output/alpha_evidence_registry_v1.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "output/alpha_evidence_registry_v1.md")
    args = parser.parse_args()
    registry = build(load(args.book), load(args.timing), load(args.external))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown.write_text(markdown(registry), encoding="utf-8")
    print(json.dumps({
        "next_stage": registry["admitted_or_next_stage"],
        "promising": registry["promising_retest"],
        "rejected": registry["rejected"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
