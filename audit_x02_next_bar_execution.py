"""Conservative next-record execution audit for the frozen X02 reproduction.

This module never rebuilds or re-ranks the legacy selection. The exact Top-3
rows written by ``reproduce_x02_local.py`` are cryptographically bound in the
legacy report and loaded here. Each frozen slot is then tested against the
persisted five-minute record labelled 14:50. Vendor wall-clock label semantics
are audited separately and are not assumed here.

Unfilled slots remain cash; they are never replaced or reweighted after
next-record information becomes available.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from x02_provenance import SELECTION_FILES, require_reproduction_artifacts

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
LEDGER_EXECUTION_COLUMNS = (
    "next_bar_rows", "next_entry_open", "next_entry_volume", "next_entry_amount",
    "next_bar_limit_gap", "entry_slippage_vs_1445", "next_bar_executable",
    "unfilled_reason", "slot_return", "cash_slot",
)


def _engine() -> Any:
    import v4_3_long_only_portfolio as engine
    return engine


def _validate_frozen_prices(selected: pd.DataFrame) -> None:
    for column, label in (("entry_1445", "14:45 entries"), ("exit_1000", "10:00 exits")):
        values = pd.to_numeric(selected[column], errors="coerce")
        invalid = values.isna() | values.le(0)
        if bool(invalid.any()):
            offenders = selected.loc[invalid, ["trade_date", "instrument", column]].astype(str).to_dict("records")
            raise RuntimeError(f"frozen selected rows have invalid {label}: {offenders[:10]}")


def load_frozen_selection(variant: str) -> pd.DataFrame:
    if variant not in SELECTION_FILES:
        raise ValueError(f"unknown variant: {variant}")
    path = OUT / SELECTION_FILES[variant]
    selected = pd.read_parquet(path)
    required = {"trade_date", "instrument", "entry_1445", "exit_1000", "upper_limit"}
    missing = sorted(required - set(selected.columns))
    if missing:
        raise RuntimeError(f"frozen selection {path.name} is missing columns: {missing}")
    selected = selected.copy()
    selected["trade_date"] = pd.to_datetime(selected["trade_date"]).dt.normalize()
    if selected.empty:
        raise RuntimeError(f"frozen selection is empty for {variant}")
    if selected.duplicated(["trade_date", "instrument"]).any():
        raise RuntimeError(f"frozen selection has duplicate trade_date/instrument keys for {variant}")
    counts = selected.groupby("trade_date")["instrument"].size()
    bad = counts[counts.ne(TOP_N)]
    if not bad.empty:
        raise RuntimeError(f"frozen selection must contain exactly {TOP_N} slots per active day for {variant}")
    _validate_frozen_prices(selected)
    return selected


def extract_next_bar(selected: pd.DataFrame) -> pd.DataFrame:
    import duckdb

    engine = _engine()
    missing = [str(path) for path in engine.MINUTE_FILES if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing persisted minute files: {missing}")
    if selected.empty:
        return pd.DataFrame(columns=[
            "trade_date", "instrument", "next_bar_rows", "next_entry_open",
            "next_entry_volume", "next_entry_amount",
        ])

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
        COUNT(m.datetime) AS next_bar_rows,
        MAX(m.open) AS next_entry_open,
        MAX(m.volume) AS next_entry_volume,
        MAX(m.amount) AS next_entry_amount
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
    duplicate = out["next_bar_rows"].fillna(0).gt(1)
    if bool(duplicate.any()):
        offenders = out.loc[duplicate, ["trade_date", "instrument", "next_bar_rows"]].astype(str).to_dict("records")
        raise RuntimeError(f"duplicate {NEXT_BAR_LABEL} minute records for selected slots: {offenders[:10]}")
    return out


def _empty_execution_ledger(selected: pd.DataFrame) -> pd.DataFrame:
    ledger = selected.copy()
    for column in LEDGER_EXECUTION_COLUMNS:
        if column not in ledger.columns:
            ledger[column] = pd.Series(dtype="object")
    return ledger


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
        return pd.Series(0.0, index=idx, name="net_return"), _empty_execution_ledger(selected)

    _validate_frozen_prices(selected)
    z = selected.merge(next_bar, on=["trade_date", "instrument"], how="left", validate="one_to_one").copy()
    counts = z.groupby("trade_date")["instrument"].size()
    bad_counts = counts[counts.ne(top_n)]
    if not bad_counts.empty:
        raise ValueError(f"frozen selection must contain exactly {top_n} slots per active day: {bad_counts.to_dict()}")
    if "next_bar_rows" in z.columns:
        duplicate = z["next_bar_rows"].fillna(0).gt(1)
        if bool(duplicate.any()):
            offenders = z.loc[duplicate, ["trade_date", "instrument", "next_bar_rows"]].astype(str).to_dict("records")
            raise RuntimeError(f"duplicate next-bar records reached accounting: {offenders[:10]}")

    z["next_bar_limit_gap"] = z["upper_limit"] / z["next_entry_open"] - 1.0
    z["entry_slippage_vs_1445"] = z["next_entry_open"] / z["entry_1445"] - 1.0
    has_record = z["next_bar_rows"].fillna(0).eq(1) & z["next_entry_open"].notna()
    has_liquidity = z["next_entry_volume"].fillna(0).gt(0) & z["next_entry_amount"].fillna(0).gt(0)
    has_limit = z["upper_limit"].notna()
    limit_ok = z["next_bar_limit_gap"].ge(limit_buffer)
    z["next_bar_executable"] = has_record & has_liquidity & has_limit & limit_ok

    z["unfilled_reason"] = "filled"
    z.loc[~has_record, "unfilled_reason"] = "missing_next_record"
    z.loc[has_record & ~has_liquidity, "unfilled_reason"] = "nonpositive_liquidity"
    z.loc[has_record & has_liquidity & ~has_limit, "unfilled_reason"] = "missing_upper_limit"
    z.loc[has_record & has_liquidity & has_limit & ~limit_ok, "unfilled_reason"] = "limit_buffer_fail"

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
        return {
            "selection_rows": 0, "filled_rows": 0, "fill_rate": None, "cash_slots": 0,
            "active_selection_days": 0, "days_with_any_unfilled_slot": 0,
            "observed_next_record_rows": 0,
            "mean_entry_slippage_vs_1445": None, "median_entry_slippage_vs_1445": None,
            "p90_entry_slippage_vs_1445": None, "worst_entry_slippage_vs_1445": None,
            "unfilled_reasons": {},
        }
    filled = ledger[ledger["next_bar_executable"]]
    observed_slippage = pd.to_numeric(ledger["entry_slippage_vs_1445"], errors="coerce").dropna()
    filled_slippage = pd.to_numeric(filled["entry_slippage_vs_1445"], errors="coerce").dropna()
    reasons = ledger.loc[ledger["cash_slot"], "unfilled_reason"].value_counts().to_dict()
    return {
        "selection_rows": int(len(ledger)),
        "filled_rows": int(len(filled)),
        "fill_rate": float(len(filled) / len(ledger)),
        "cash_slots": int(ledger["cash_slot"].sum()),
        "active_selection_days": int(ledger["trade_date"].nunique()),
        "days_with_any_unfilled_slot": int(ledger.groupby("trade_date")["cash_slot"].any().sum()),
        "observed_next_record_rows": int(len(observed_slippage)),
        "mean_entry_slippage_vs_1445": float(filled_slippage.mean()) if len(filled_slippage) else None,
        "median_entry_slippage_vs_1445": float(filled_slippage.median()) if len(filled_slippage) else None,
        "p90_entry_slippage_vs_1445": float(filled_slippage.quantile(0.90)) if len(filled_slippage) else None,
        "worst_entry_slippage_vs_1445": float(filled_slippage.max()) if len(filled_slippage) else None,
        "unfilled_reasons": {str(k): int(v) for k, v in reasons.items()},
    }


def main() -> None:
    engine = _engine()
    lineage = require_reproduction_artifacts(OUT, Path(engine.__file__))
    legacy_report_path = OUT / "report.json"
    legacy_report = json.loads(legacy_report_path.read_text(encoding="utf-8"))
    first = pd.Timestamp(legacy_report["coverage"]["first"])
    last = pd.Timestamp(legacy_report["coverage"]["last"])
    all_dates = [d for d in pd.to_datetime(engine._prepare_candidates()[1]) if first <= d <= last]

    report: dict[str, object] = {
        "audit": "X02_NEXT_BAR_EXECUTION_V4",
        "selection_source": "exact frozen selection parquet artifacts from legacy reproduction",
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
        "missing_exit_policy": "hard failure for any frozen selected row",
        "invalid_price_policy": "hard failure for missing/nonpositive frozen 14:45 entries or 10:00 exits",
        "duplicate_next_bar_policy": "hard failure; duplicates may not be collapsed by MAX/MIN",
        "slippage_stat_policy": "entry slippage summary statistics use filled slots only; observed_next_record_rows is reported separately",
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
        selected = load_frozen_selection(variant)
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
