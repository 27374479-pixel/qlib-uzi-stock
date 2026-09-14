"""Fail-closed W03 source-readiness gate for W01 absolute-leader identity."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_W03_ABSOLUTE_LEADER_SOURCE_REVIEW.md"
W02_RESULT = ROOT / "V5_W02_RESULT.md"
M02_RESULT = ROOT / "V5_M02_RESULT.md"
LEDGER = ROOT / "V5_BOOK_EVIDENCE_LEDGER.md"
OUT = ROOT / "output" / "v5_w03_absolute_leader_source_readiness"
REPORT = OUT / "report.json"

REQUIRED = (
    "w01_to_market_total_leader_semantic_bridge",
    "eligible_universe",
    "trait_set_transcription",
    "trait_necessity_or_combination_rule",
    "major_theme_definition",
    "news_fermentation_definition",
    "historical_high_volume_window",
    "board_turnover_accessibility_rule",
    "index_adjustment_end_rule",
    "unique_selection_or_ranking_rule",
    "tie_break_rule",
    "identity_known_time",
    "no_retroactive_identity_rule",
    "independent_validation_or_source_basis",
    "upstream_lineage_binding",
)

CONTRACT = {
    "version": "V5_W03_ABSOLUTE_LEADER_SOURCE_READINESS_V1",
    "mode": "SOURCE_READINESS_ONLY",
    "source_traits": [
        "persistent_major_theme_and_strong_logic",
        "continuing_news_fermentation",
        "three_board_launch",
        "first_wave_disagreement_historical_high_volume",
        "board_by_board_turnover_accessibility",
        "disagreement_turnover_ge_1bn_cny",
        "launch_before_end_of_index_adjustment",
        "launch_price_lt_10_cny",
    ],
    "direct_numeric_or_literal_traits": {
        "three_board_launch": True,
        "disagreement_turnover_cny_floor": 1_000_000_000,
        "launch_price_cny_ceiling_exclusive": 10.0,
    },
    "parameter_search": False,
    "absolute_leader_preregistration_authorized": False,
    "w01_event_preregistration_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "w01_to_market_total_leader_semantic_bridge": {
            "ready": False,
            "detail": "source does not explicitly prove lower-volume absolute leader is identical to upper-volume market total leader",
        },
        "eligible_universe": {
            "ready": False,
            "detail": "source does not authorize CSI800 as a substitute for the market-wide total-leader candidate universe",
        },
        "trait_set_transcription": {
            "ready": True,
            "detail": "upper-volume market-total-leader characteristic list is frozen verbatim at the semantic-item level",
        },
        "trait_necessity_or_combination_rule": {
            "ready": False,
            "detail": "source does not state whether traits are mandatory, common, alternative, scored or weighted",
        },
        "major_theme_definition": {"ready": False, "detail": "major theme / strong logic is not machine-defined"},
        "news_fermentation_definition": {"ready": False, "detail": "continuing news fermentation is not machine-defined"},
        "historical_high_volume_window": {"ready": False, "detail": "historically high volume has no exact backward window"},
        "board_turnover_accessibility_rule": {"ready": False, "detail": "board-by-board turnover/accessibility has no exact mechanical rule"},
        "index_adjustment_end_rule": {"ready": False, "detail": "end of index adjustment has no deterministic causal definition"},
        "unique_selection_or_ranking_rule": {"ready": False, "detail": "source provides no exact one-leader selection/ranking rule"},
        "tie_break_rule": {"ready": False, "detail": "source provides no deterministic tie break"},
        "identity_known_time": {
            "ready": False,
            "detail": "some leader traits are only observed after first-wave disagreement, so earliest causal identity time is unspecified",
        },
        "no_retroactive_identity_rule": {
            "ready": False,
            "detail": "source does not state how to prevent future confirmation from relabelling earlier decisions",
        },
        "independent_validation_or_source_basis": {
            "ready": False,
            "detail": "no non-P&L basis resolves the remaining semantic choices",
        },
        "upstream_lineage_binding": {
            "ready": True,
            "detail": "W03 can bind frozen W02/M02 results, source review and evidence ledger",
        },
    }


def evaluate(e: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [field for field in REQUIRED if field not in e]
    not_ready = [
        {"field": field, "detail": e[field].get("detail")}
        for field in REQUIRED
        if field in e and not bool(e[field].get("ready"))
    ]
    ready = not missing and not not_ready
    return {
        "status": "READY_FOR_ABSOLUTE_LEADER_PREREGISTRATION" if ready else "DEFER_ABSOLUTE_LEADER_PREREGISTRATION",
        "ready": ready,
        "missing_fields": missing,
        "not_ready": not_ready,
        "absolute_leader_preregistration_authorized": ready,
        "w01_event_preregistration_authorized": False,
        "w01_return_screen_authorized": False,
        "effective_action": "WRITE_SEPARATE_ABSOLUTE_LEADER_PREREGISTRATION" if ready else "SOURCE_AND_REPRESENTATION_RESEARCH_ONLY",
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    for path in (SOURCE_REVIEW, W02_RESULT, M02_RESULT, LEDGER):
        if not path.exists():
            raise FileNotFoundError(path)
    report = {
        "contract": CONTRACT,
        "lineage": {
            "source_review_sha256": sha256_file(SOURCE_REVIEW),
            "w02_result_sha256": sha256_file(W02_RESULT),
            "m02_result_sha256": sha256_file(M02_RESULT),
            "evidence_ledger_sha256": sha256_file(LEDGER),
        },
        "evidence": evidence(),
    }
    report["decision"] = evaluate(report["evidence"])
    report["interpretation_boundary"] = (
        "The books provide market-total-leader traits, not a unique causal classifier. W03 freezes the traits but refuses "
        "to infer conjunction, ranking, tie-break or retroactive identity from strategy returns."
    )
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
