"""Run leakage-safe v4 minute timing validation against final v3 survivors.

The external challenger selectors are daily-close definitions. For an entry
on trading day T they are therefore evaluated on T-1 and carried forward to T.
This makes every 14:xx entry causal: no T close, high, limit-touch or cross-
sectional rank is used before it exists.
"""
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
    tc = TimingConfig(
        universe=config.universe,
        start=config.start,
        end=config.end,
        oos_start="2023-01-01",
        round_trip_cost=0.0018,
        bootstrap_samples=config.bootstrap_samples,
        seed=config.seed,
    )
    return add_challenger_features(prepare_timing(tc), 0.0018)


def _next_trading_date_map(frame):
    dates = sorted(pd.to_datetime(frame["date"]).dt.normalize().drop_duplicates())
    return {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}


def candidates(frame, modules):
    """Generate T candidates from selectors known after T-1 close."""
    masks = challenger_masks(frame)
    next_date = _next_trading_date_map(frame)
    parts = []
    for module in modules:
        m = masks[MAP[module]]["selected"].fillna(False)
        x = frame.loc[m, ["date", "instrument"]].copy()
        x["signal_date"] = pd.to_datetime(x["date"]).dt.normalize()
        x["date"] = x["signal_date"].map(next_date)
        x = x.dropna(subset=["date"])
        x["hypothesis_id"] = module
        parts.append(x[["date", "instrument", "hypothesis_id"]])
    if not parts:
        return pd.DataFrame(columns=["date", "instrument", "hypothesis_id"])
    return pd.concat(parts, ignore_index=True).drop_duplicates()


# The base loader caches a missing file as an empty DataFrame. On the next
# access that empty frame used to escape as if it were valid and later caused
# KeyError('datetime'). Normalize cached empties back to None.
_base_load_minute = v4._load_minute

def safe_load_minute(instrument, cache):
    frame = _base_load_minute(instrument, cache)
    if frame is None or frame.empty or "datetime" not in frame.columns:
        return None
    return frame


v4._load_pass_ids = load_modules
v4._prepare_daily = prepare
v4._candidate_rows = candidates
v4._load_minute = safe_load_minute

if __name__ == "__main__":
    v4.run(v4.parse_args())
