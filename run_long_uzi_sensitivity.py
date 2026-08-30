"""Compare pre-declared book-derived rule profiles without retuning the test set."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

import long_uzi_state_backtest as model


def _period(signals: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    part = signals.loc[
        pd.to_datetime(signals["signal_date"]).between(start, end)
        & signals["entry_filled"].astype(bool)
    ]
    portfolio = model._portfolio(part, "dynamic_return", "target_exposure")
    return {
        "start": str(start.date()),
        "end": str(end.date()),
        "signals": int(len(part)),
        "event": model._summary(part["dynamic_return"] if "dynamic_return" in part else pd.Series(dtype=float)),
        "portfolio": portfolio,
    }


def evaluate(asof: pd.DataFrame, market: pd.DataFrame, profile: str, top_n: int) -> dict:
    scored = model._score_snapshots(asof, market, profile)
    signals = model._select_signals(scored, top_n)
    if signals.empty:
        return {"profile": profile, "top_n": top_n, "signals": 0}
    dates = pd.to_datetime(signals["signal_date"]).dt.normalize().drop_duplicates().sort_values()
    split = dates.iloc[max(0, len(dates) * 3 // 5 - 1)] if len(dates) >= 5 else dates.iloc[-1]
    development = _period(signals, dates.iloc[0], split)
    oos_start = split + pd.Timedelta(days=1)
    oos = _period(signals, oos_start, dates.iloc[-1]) if oos_start <= dates.iloc[-1] else {"signals": 0}
    event = model._summary(signals.loc[signals["entry_filled"].astype(bool), "dynamic_return"])
    return {
        "profile": profile,
        "top_n": top_n,
        "signals": int(len(signals)),
        "signal_days": int(signals["signal_date"].nunique()),
        "event": event,
        "portfolio": model._portfolio(signals, "dynamic_return", "target_exposure"),
        "development": development,
        "out_of_sample": oos,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sensitivity report for long_uzi_state_backtest")
    parser.add_argument("--output", default="output/long_uzi_sensitivity_latest.json")
    parser.add_argument("--start", default=model.Config.start)
    parser.add_argument("--end", default=model.Config.end)
    parser.add_argument("--top-ns", default="3,5,8")
    parser.add_argument("--universes", default="csi300_start,csi500_start,csi800_start")
    parser.add_argument("--refresh-cache", action="store_true")
    args = parser.parse_args()
    top_ns = [max(1, int(value.strip())) for value in args.top_ns.split(",") if value.strip()]
    universes = [value.strip() for value in args.universes.split(",") if value.strip()]
    rows = []
    cache_meta = {}
    for universe in universes:
        config = model.Config(
            start=args.start,
            end=args.end,
            universe=universe,
            refresh_cache=args.refresh_cache,
        )
        _, market, asof, cache_meta[universe] = model.build_cache(config)
        for profile in model.PROFILE_LIBRARY:
            for top_n in top_ns:
                item = evaluate(asof, market, profile, top_n)
                item["universe"] = universe
                rows.append(item)
    config = model.Config(start=args.start, end=args.end)
    result = {
        "model": model.MODEL_NAME,
        "config": asdict(config),
        "cache": cache_meta,
        "selection_rule": "只允许开发段比较；最后40%为冻结样本外，不按其结果回改profile",
        "profiles": rows,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(model._safe_json(result), ensure_ascii=False, indent=2), encoding="utf-8")
    compact = [
        {
            "universe": row["universe"],
            "profile": row["profile"],
            "top_n": row["top_n"],
            "signals": row.get("signals", 0),
            "oos_event_mean": row.get("out_of_sample", {}).get("event", {}).get("mean"),
            "oos_event_win": row.get("out_of_sample", {}).get("event", {}).get("win_rate"),
            "oos_portfolio_total": row.get("out_of_sample", {}).get("portfolio", {}).get("total_return"),
        }
        for row in rows
    ]
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
