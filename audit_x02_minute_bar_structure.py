"""Local data-contract audit for the five-minute bars used by X02."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MINUTE_FILES = tuple(ROOT / "data_lake" / "raw" / "traderharness" / f"paired_ext_5min_{year}.parquet" for year in range(2021, 2027))
OUT = ROOT / "output" / "x02_reproduction_20260912" / "minute_bar_structure_audit.json"
KEY_LABELS = ("09:30", "09:35", "14:45", "14:50", "15:00")


def classify_label_contract(label_counts: dict[str, int], duplicate_keys: int) -> dict:
    counts = {label: int(label_counts.get(label, 0)) for label in KEY_LABELS}
    failures = []
    warnings = []
    if duplicate_keys:
        failures.append(f"duplicate instrument/datetime keys: {duplicate_keys}")
    for label in ("14:45", "14:50", "15:00"):
        if counts[label] <= 0:
            failures.append(f"{label}-labelled bars are absent")
    end_label_evidence = counts["09:35"] > 0 and counts["09:30"] == 0 and counts["15:00"] > 0
    if counts["09:30"] > 0:
        warnings.append("09:30-labelled rows exist; start-vs-end labelling is ambiguous")
    elif counts["09:35"] <= 0:
        warnings.append("09:35-labelled rows are absent")
    inference = "CONSISTENT_WITH_END_LABELLED_5M_NOT_PROOF" if end_label_evidence else "LABEL_SEMANTICS_AMBIGUOUS"
    return {
        "pass": not failures,
        "inference": inference,
        "key_label_counts": counts,
        "failures": failures,
        "warnings": warnings,
        "interpretation_boundary": "Labels and adjacency do not by themselves prove vendor wall-clock interval semantics.",
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _scan(path: Path) -> dict:
    import duckdb

    con = duckdb.connect()
    relation = con.read_parquet(str(path))
    relation.create_view("bars", replace=True)
    columns = {row[0] for row in con.execute("DESCRIBE bars").fetchall()}
    required = {"instrument", "datetime", "open", "close", "volume", "amount"}
    missing = sorted(required - columns)
    if missing:
        con.close()
        raise RuntimeError(f"{path.name} missing required columns: {missing}")
    rows, instruments, first_dt, last_dt = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT instrument), MIN(datetime), MAX(datetime) FROM bars"
    ).fetchone()
    labels = dict(con.execute(
        "SELECT strftime(datetime, '%H:%M'), COUNT(*) FROM bars "
        "WHERE strftime(datetime, '%H:%M') IN ('09:30','09:35','14:45','14:50','15:00') GROUP BY 1"
    ).fetchall())
    duplicate_keys = int(con.execute(
        "SELECT COUNT(*) FROM (SELECT instrument, datetime FROM bars GROUP BY instrument, datetime HAVING COUNT(*) > 1)"
    ).fetchone()[0])
    con.close()
    structure = classify_label_contract(labels, duplicate_keys)
    return {
        "path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size,
        "rows": int(rows), "instruments": int(instruments), "first_datetime": str(first_dt),
        "last_datetime": str(last_dt), "duplicate_keys": duplicate_keys, "structure": structure,
    }


def build_report(records: list[dict]) -> dict:
    counts = {label: 0 for label in KEY_LABELS}
    duplicates = 0
    for record in records:
        duplicates += int(record["duplicate_keys"])
        for label in KEY_LABELS:
            counts[label] += int(record["structure"]["key_label_counts"].get(label, 0))
    aggregate = classify_label_contract(counts, duplicates)
    return {
        "audit": "X02_MINUTE_BAR_STRUCTURE_V1", "data_only": True, "strategy_parameters_read": False,
        "files": records, "aggregate": aggregate,
        "validation": {"pass": bool(records) and aggregate["pass"] and all(r["structure"]["pass"] for r in records), "file_count": len(records)},
    }


def main() -> None:
    missing = [str(p) for p in MINUTE_FILES if not p.exists()]
    if missing:
        raise SystemExit(f"missing persisted minute files: {missing}")
    report = build_report([_scan(path) for path in MINUTE_FILES])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["validation"]["pass"]:
        raise SystemExit("minute-bar structure audit failed")


if __name__ == "__main__":
    main()
