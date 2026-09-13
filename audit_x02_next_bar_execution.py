"""Conservative next-bar execution audit for the frozen X02 reproduction.

This module does not search parameters and does not alter the legacy X02
selection. It freezes the Top-3 decision at the observed 14:45 close, then asks
whether each selected slot could still be filled at the open of the persisted
five-minute record labelled 14:50. The exact vendor wall-clock meaning of that
label is audited separately and is not assumed here.

Unfilled slots remain cash; they are never replaced with a lower-ranked stock
after seeing next-bar data. The heavy research engine is imported lazily so the
accounting rules can be unit-tested in a minimal CI environment.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from x02_provenance import require_reproduction_artifacts

OUT = Path("output/x02_reproduction_20260912")
NEXT_BAR_LABEL = "14:50"
TOP_N = 3
LIMIT_BUFFER = 0.005
VARIANTS = ("original_gate", "no_market_gate")
COSTS = ("BASE", "CONSERVATIVE")
PERIODS = {
    "all": (None, None),
    "development": (None, pd.Timestamp("2023-12-31")),
    "later": (pd.Timestamp("2024-01-01"), None),
}


def _engine() -> Any:
    import v4_3_long_only_portfolio as engine
    return engine


def select_legacy_top3(features: pd.DataFrame, variant: str) -> pd.DataFrame:
    engine = _engine()
    y = features[features["base_executable"] & features["limit_gap"].ge(LIMIT_BUFFER)].copy()
    if variant == "original_gate":
        y = y[y["breadth5"].fillna(-1).gt(0) & y["money_effect"].fillna(-1).gt(0)].copy()
    elif variant != "no_market_gate":
        raise ValueError(f"unknown variant: {variant}")
    y["score"] = y["clean_mom20_rank"].fillna(float("-inf"))
    return engine._select_top(y, TOP_N)


def extract_next_bar(selected: pd.DataFrame) -> pd.DataFrame:
    import duckdb

    engine = _engine()
    missing = [str(path) for path in engine.MINUTE_FILES if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing persisted minute files: {missing}")
    if selected.empty:
        return pd.DataFrame(
            columns=["trade_date", "instrument", "next_entry_open", "next_entry_volume", "next_entry_amount"]
        )

    keys = selected[["trade_date", "instrument"]].drop_duplicates().copy()
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.register("selected", keys)
    files_sql = ",".join("'" + str(p.resolve()).replace("'", "''") + "'" for p in engine.MINUTE_FILES)
    query = f"""
    SELECT
        CAST(s.trade_date AS DATE) AS trade_date,
        s.instrument,
        MAX(CASE WHEN strftime(m.datetime, '%H:%M')='{NEXT_BAR_LABEL}' THEN m.open END) AS next_entry_open,
        MAX(CASE WHEN strftime(m.datetime, '%H:%M')='{NEXT_BAR_LABEL}' THEN m.volume END) AS next_entry_volume,
        MAX(CASE WHEN strftime(m.datetime, '%H:%M')='{NEXT_BAR_LABEL}' THEN m.amount END) AS next_entry_amount
    FROM selected s
    LEFT JOIN read_parquet([{files_sql}]) m
      ON m.instrument = s.instrument
     AND CAST(m.datetime AS DATE) = CAST(s.trade_date AS DATE)
     AND strftime(m.datetime, '%H:%M') = '{NEXT_BAR_LABEL}'
    GROUP BY 1,2
    """
    out = con.execute(query).df()
    con.close()
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.normalize()
    return out


def strict_next_bar_portfolio(
    selected: pd.DataFrame,
    next_bar: pd.DataFrame,
    all_dates: list[pd.Timestamp],
    cost_name: str,
    top_n: int = TOP_N,
    limit_buffer: float = LIMIT_BUFFER,
) -> tuple[pd.Series, pd.DataFrame]:
    idx = pd.DatetimeIndex(pd.to_datetime(all_dates)).normalize()
    if selected.empty:
        return pd.Series(0.0, index=idx, name="net_return"), selected.copy()

    z = selected.merge(next_bar, on=["trade_date", "instrument"], how="left", validate="one_to_one").copy()
    counts = z.groupby("trade_date")["instrument"].size()
    bad_counts = counts[counts.ne(top_n)]
    if not bad_counts.empty:
        raise ValueError(f"frozen selection must contain exactly {top_n} slots per active day: {bad_counts.to_dict()}")

    z["next_bar_limit_gap"] = z["upper_limit"] / z["next_entry_open"] - 1.0
    z["next_bar_executable"] = (
        z["next_entry_open"].notna()
        & z["next_entry_volume"].fillna(0).gt(0)
        & z["next_entry_amount"].fillna(0).gt(0)
        & z["upper_limit"].notna()
        & z["next_bar_limit_gap"].ge(limit_buffer)
    )

    missing_exit = z["next_bar_executable"] & z["exit_1000"].isna()
    if bool(missing_exit.any()):
        offenders = z.loc[missing_exit, ["trade_date", "instrument"]].astype(str).to_dict("records")
        raise RuntimeError(f"filled next-bar positions have missing 10:00 exits: {offenders[:10]}")

    z["slot_return"] = 0.0
    filled = z["next_bar_executable"]
    if bool(filled.any()):
        engine = _engine()
        z.loc[filled, "slot_return"] = engine._net_return(
            z.loc[filled, "next_entry_open"], z.loc[filled, "exit_1000"], z.loc[filled, "trade_date"], cost_name
        )
    z["cash_slot"] = ~z["next_bar_executable"]

    daily = z.groupby("trade_date")["slot_return"].sum() / float(top_n)
    series = daily.reindex(idx, fill_value=0.0).rename("net_return")
    return series, z


def _period_slice(series: pd.Series, ledger: pd.DataFrame, start: pd.Timestamp | None, end: pd.Timestamp | None):
    s = series
    z = ledger
    if start is not None:
        s = s[s.index >= start]
        z = z[z["trade_date"] >= start]
    if end is not None:
        s = s[s.index <= end]
        z = z[z["trade_date"] <= end]
    return s, z


def _execution_stats(ledger: pd.DataFrame) -> dict[str, object]:
    if ledger.empty:
        return {"selection_rows": 0, "filled_rows": 0, "fill_rate": None, "cash_slots": 0,
                "active_selection_days": 0, "days_with_any_unfilled_slot": 0}
    filled = ledger[ledger["next_bar_executable"]]
    return {
        "selection_rows": int(len(ledger)),
        "filled_rows": int(len(filled)),
        "fill_rate": float(len(filled) / len(ledger)),
        "cash_slots": int(ledger["cash_slot"].sum()),
        "active_selection_days": int(ledger["trade_date"].nunique()),
        "days_with_any_unfilled_slot": int(ledger.groupby("trade_date")["cash_slot"].any().sum()),
    }


def main() -> None:
    engine = _engine()
    lineage = require_reproduction_artifacts(OUT, Path(engine.__file__))
    features_path = OUT / "features.parquet"
    legacy_report_path = OUT / "report.json"
    features = pd.read_parquet(features_path)
    legacy_report = json.loads(legacy_report_path.read_text(encoding="utf-8"))
    first = pd.Timestamp(legacy_report["coverage"]["first"])
    last = pd.Timestamp(legacy_report["coverage"]["last"])
    all_dates = [d for d in pd.to_datetime(engine._prepare_candidates()[1]) if first <= d <= last]

    report: dict[str, object] = {
        "audit": "X02_NEXT_BAR_EXECUTION_V2",
        "selection_frozen_at": "14:45 bar close",
        "fill_proxy": "open of persisted 5m record labelled 14:50",
        "bar_label_contract": (
            "14:50 is the next persisted five-minute label used after the frozen 14:45 decision; "
            "the separate structure audit may support end-labelling but cannot prove vendor wall-clock semantics"
        ),
        "inputs": lineage,
        "top_n": TOP_N,
        "limit_buffer": LIMIT_BUFFER,
        "parameter_search": False,
        "rank_replacement_after_next_bar": False,
        "unfilled_slot_policy": "cash; no reweighting and no replacement",
        "missing_exit_policy": "hard failure after a successful entry",
        "periods": {name: {"start": None if start is None else str(start.date()),
                           "end": None if end is None else str(end.date())}
                    for name, (start, end) in PERIODS.items()},
        "results": {},
        "limitations": [
            "This is an execution stress test, not a new strategy search.",
            "A next-record open is a causal stress proxy, not proof that a live order would fill at that exact price.",
            "Positive bar volume/amount is an ex-post executability check and does not imply guaranteed fill at the bar open.",
            "Vendor bar-label semantics require independent confirmation before live-trading interpretation.",
        ],
    }

    for variant in VARIANTS:
        selected = select_legacy_top3(features, variant)
        next_bar = extract_next_bar(selected)
        for cost in COSTS:
            series, ledger = strict_next_bar_portfolio(selected, next_bar, all_dates, cost)
            key = f"{variant}_{cost}"
            period_results = {}
            for period_name, (start, end) in PERIODS.items():
                period_series, period_ledger = _period_slice(series, ledger, start, end)
                period_filled = period_ledger[period_ledger["next_bar_executable"]]
                metrics = engine._metrics(period_series, period_filled)
                metrics.update(_execution_stats(period_ledger))
                period_results[period_name] = metrics
            report["results"][key] = period_results
            ledger.to_csv(OUT / f"{key}_next_bar_ledger.csv", index=False)
            series.to_csv(OUT / f"{key}_next_bar_daily.csv", header=True)

    (OUT / "next_bar_execution_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
