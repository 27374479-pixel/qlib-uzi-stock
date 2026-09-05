"""Run v4 minute timing validation against the final v3 evidence-registry survivors."""
import json
from pathlib import Path
import pandas as pd
import v4_intraday_survivor_validation as v4
from attention_timing_decomposition import Config as TimingConfig, prepare as prepare_timing
from external_challenger_daily_screen import add_challenger_features, challenger_masks

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "output" / "alpha_evidence_registry_v1.json"
MAP = {
    "ATTENTION_SATURATION_VETO": "X01_attention_saturation",
    "LIMIT_ADJUSTED_MOMENTUM": "X02_limit_adjusted_momentum",
}


def load_modules():
    d = json.loads(REGISTRY.read_text(encoding="utf-8"))
    mods = [x for x in d.get("admitted_or_next_stage", []) if x in MAP]
    if set(mods) != set(MAP):
        raise RuntimeError(f"unexpected admitted modules: {mods}")
    return mods


def prepare(config):
    tc = TimingConfig(universe=config.universe, start=config.start, end=config.end,
                      oos_start="2023-01-01", round_trip_cost=0.0018,
                      bootstrap_samples=config.bootstrap_samples, seed=config.seed)
    return add_challenger_features(prepare_timing(tc), 0.0018)


def candidates(frame, modules):
    masks = challenger_masks(frame)
    parts = []
    for module in modules:
        m = masks[MAP[module]]["selected"].fillna(False)
        x = frame.loc[m, ["date", "instrument"]].copy()
        x["hypothesis_id"] = module
        parts.append(x)
    return pd.concat(parts, ignore_index=True).drop_duplicates()

v4._load_pass_ids = load_modules
v4._prepare_daily = prepare
v4._candidate_rows = candidates

if __name__ == "__main__":
    v4.run(v4.parse_args())
