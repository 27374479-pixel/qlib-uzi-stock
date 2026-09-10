from __future__ import annotations

import argparse
import glob
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

CANONICAL_EASTMONEY_SCHEMA = "v4.17-a.2"
CANONICAL_EASTMONEY_PROVIDER = "eastmoney"
CANONICAL_EASTMONEY_ENDPOINT = "akshare.stock_notice_report"
CANONICAL_EASTMONEY_EVENT_TYPE = "corporate_announcement"


def canonical_audit_title(value: object) -> str:
    """Normalize source presentation noise for COVERAGE AUDIT ONLY.

    This canonical form must never be used as a trading feature or as a
    profitability-selected event label. It intentionally removes issuer/ticker
    prefixes used by some vendors and punctuation/spacing differences so that
    the same disclosure can be matched across CNINFO and Eastmoney.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"\s+", "", text)

    # Eastmoney often prepends the short security name: "深振业A:公告正文标题".
    # Restrict stripping to a short prefix before the first colon so ordinary
    # colons later in a long legal title are not altered.
    if ":" in text:
        prefix, rest = text.split(":", 1)
        if 0 < len(prefix) <= 16 and len(rest) >= 6:
            text = rest

    # Remove presentation punctuation only. Chinese characters, latin letters
    # and digits remain; this keeps the matcher transparent and deterministic.
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text)
    return text.lower()


def _new_loader_diagnostics(source: str, pattern: str, paths: list[str]) -> dict[str, Any]:
    return {
        "source": source,
        "pattern": pattern,
        "discovered_parquet_files": len(paths),
        "readable_files": 0,
        "accepted_files": 0,
        "accepted_rows": 0,
        "empty_files": 0,
        "unreadable_files": [],
        "incompatible_files": [],
    }


def load_cninfo(pattern: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    paths = sorted(glob.glob(pattern, recursive=True))
    diagnostics = _new_loader_diagnostics("cninfo", pattern, paths)
    frames: list[pd.DataFrame] = []

    for path in paths:
        try:
            frame = pd.read_parquet(path)
        except Exception as exc:
            diagnostics["unreadable_files"].append({"path": path, "error": str(exc)[:240]})
            continue
        diagnostics["readable_files"] += 1
        if frame.empty:
            diagnostics["empty_files"] += 1
            continue

        required = {"security_code", "published_date", "title"}
        if not required.issubset(frame.columns):
            diagnostics["incompatible_files"].append(
                {"path": path, "columns": sorted(map(str, frame.columns))}
            )
            continue

        frame = frame.copy()
        frame["audit_source_path"] = path
        frame["audit_input_schema"] = "cninfo_notice"
        frames.append(frame)
        diagnostics["accepted_files"] += 1
        diagnostics["accepted_rows"] += int(len(frame))

    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return out, diagnostics


def _canonical_contract_violations(frame: pd.DataFrame) -> dict[str, int]:
    checks = {
        "schema_version": (frame["schema_version"].astype(str) != CANONICAL_EASTMONEY_SCHEMA),
        "source_provider": (frame["source_provider"].astype(str) != CANONICAL_EASTMONEY_PROVIDER),
        "source_endpoint": (frame["source_endpoint"].astype(str) != CANONICAL_EASTMONEY_ENDPOINT),
        "event_type": (frame["event_type"].astype(str) != CANONICAL_EASTMONEY_EVENT_TYPE),
    }
    return {name: int(mask.sum()) for name, mask in checks.items() if bool(mask.any())}


def load_eastmoney(pattern: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load Eastmoney audit evidence with canonical-year precedence.

    The production archive is V4.17-A and stores ``stock_code_raw`` rather than
    the older audit fixture's ``security_code``.  We explicitly normalize that
    canonical schema into the audit shape.

    Older monthly files containing ``security_code,published_date,title`` are
    retained only as compatibility fixtures for years that do not yet have a
    canonical annual partition.  Once a canonical year exists, legacy rows from
    the same year are excluded so two collectors cannot be mixed silently.

    Direct-source daily files with a different date/schema contract are not
    coerced into this audit and are reported as incompatible instead.
    """
    paths = sorted(glob.glob(pattern, recursive=True))
    diagnostics = _new_loader_diagnostics("eastmoney", pattern, paths)
    diagnostics.update(
        {
            "canonical_schema": CANONICAL_EASTMONEY_SCHEMA,
            "canonical_files": 0,
            "canonical_rows": 0,
            "canonical_years": [],
            "legacy_compatible_files": 0,
            "legacy_compatible_rows": 0,
            "legacy_rows_excluded_by_canonical_year": 0,
            "canonical_contract_violations": [],
        }
    )

    canonical_frames: list[pd.DataFrame] = []
    legacy_frames: list[pd.DataFrame] = []
    canonical_years: set[int] = set()

    canonical_required = {
        "schema_version",
        "source_provider",
        "source_endpoint",
        "event_type",
        "stock_code_raw",
        "published_date",
        "title",
    }
    legacy_required = {"security_code", "published_date", "title"}

    for path in paths:
        try:
            frame = pd.read_parquet(path)
        except Exception as exc:
            diagnostics["unreadable_files"].append({"path": path, "error": str(exc)[:240]})
            continue
        diagnostics["readable_files"] += 1
        if frame.empty:
            diagnostics["empty_files"] += 1
            continue

        columns = set(map(str, frame.columns))
        looks_like_canonical_path = bool(re.search(r"(?:^|/)year=\d{4}/notices_\d{4}\.parquet$", path))

        if canonical_required.issubset(columns):
            violations = _canonical_contract_violations(frame)
            if violations:
                diagnostics["canonical_contract_violations"].append(
                    {"path": path, "row_violations": violations}
                )
                continue

            normalized = frame.copy()
            normalized["security_code"] = (
                normalized["stock_code_raw"].astype(str).str.extract(r"(\d{6})", expand=False)
            )
            normalized["audit_source_path"] = path
            normalized["audit_input_schema"] = CANONICAL_EASTMONEY_SCHEMA
            normalized["_audit_input_kind"] = "canonical"
            years = pd.to_datetime(normalized["published_date"], errors="coerce").dt.year.dropna()
            canonical_years.update(int(y) for y in years.unique())
            canonical_frames.append(normalized)
            diagnostics["canonical_files"] += 1
            diagnostics["canonical_rows"] += int(len(normalized))
            diagnostics["accepted_files"] += 1
            continue

        # A file occupying the authoritative annual path must never fall back
        # to a legacy schema. Fail the loader loudly via diagnostics instead.
        if looks_like_canonical_path:
            diagnostics["canonical_contract_violations"].append(
                {
                    "path": path,
                    "missing_columns": sorted(canonical_required - columns),
                    "columns": sorted(columns),
                }
            )
            continue

        if legacy_required.issubset(columns):
            normalized = frame.copy()
            normalized["audit_source_path"] = path
            normalized["audit_input_schema"] = "legacy_eastmoney_audit_fixture"
            normalized["_audit_input_kind"] = "legacy"
            legacy_frames.append(normalized)
            diagnostics["legacy_compatible_files"] += 1
            diagnostics["legacy_compatible_rows"] += int(len(normalized))
            diagnostics["accepted_files"] += 1
            continue

        diagnostics["incompatible_files"].append(
            {"path": path, "columns": sorted(columns)}
        )

    diagnostics["canonical_years"] = sorted(canonical_years)

    parts: list[pd.DataFrame] = []
    if canonical_frames:
        parts.extend(canonical_frames)

    if legacy_frames:
        legacy = pd.concat(legacy_frames, ignore_index=True)
        legacy_year = pd.to_datetime(legacy["published_date"], errors="coerce").dt.year
        excluded = legacy_year.isin(canonical_years)
        diagnostics["legacy_rows_excluded_by_canonical_year"] = int(excluded.sum())
        legacy = legacy[~excluded].copy()
        if not legacy.empty:
            parts.append(legacy)

    if diagnostics["canonical_contract_violations"]:
        diagnostics["loader_validation_pass"] = False
    else:
        diagnostics["loader_validation_pass"] = True

    out = pd.concat(parts, ignore_index=True, sort=False) if parts else pd.DataFrame()
    diagnostics["accepted_rows"] = int(len(out))
    return out, diagnostics


def dedup_for_audit(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["security_code", "published_date", "canonical_title", "source"])
    out = frame[["security_code", "published_date", "title"]].copy()
    out["security_code"] = out["security_code"].astype(str).str.extract(r"(\d{6})", expand=False)
    out["published_date"] = pd.to_datetime(out["published_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["canonical_title"] = out["title"].map(canonical_audit_title)
    out["source"] = source
    out = out.dropna(subset=["security_code", "published_date"])
    out = out[out["canonical_title"].ne("")]
    return out.drop_duplicates(subset=["security_code", "published_date", "canonical_title"]).reset_index(drop=True)


def audit(cn: pd.DataFrame, em: pd.DataFrame) -> tuple[dict[str, object], pd.DataFrame]:
    cn = dedup_for_audit(cn, "cninfo")
    em = dedup_for_audit(em, "eastmoney")

    key = ["security_code", "published_date", "canonical_title"]
    exact = cn.merge(em[key], on=key, how="inner") if not cn.empty and not em.empty else pd.DataFrame(columns=cn.columns)

    cn_day = cn.groupby(["security_code", "published_date"]).size().rename("cninfo_rows") if not cn.empty else pd.Series(dtype="int64")
    em_day = em.groupby(["security_code", "published_date"]).size().rename("eastmoney_rows") if not em.empty else pd.Series(dtype="int64")
    days = pd.concat([cn_day, em_day], axis=1).fillna(0).astype(int).reset_index()
    both_days = days[(days["cninfo_rows"] > 0) & (days["eastmoney_rows"] > 0)].copy()

    if not both_days.empty:
        exact_day = (
            exact.groupby(["security_code", "published_date"]).size().rename("exact_title_matches").reset_index()
            if not exact.empty
            else pd.DataFrame(columns=["security_code", "published_date", "exact_title_matches"])
        )
        both_days = both_days.merge(exact_day, on=["security_code", "published_date"], how="left")
        both_days["exact_title_matches"] = both_days["exact_title_matches"].fillna(0).astype(int)
        both_days["cninfo_match_rate"] = both_days["exact_title_matches"] / both_days["cninfo_rows"].clip(lower=1)
        both_days["eastmoney_match_rate"] = both_days["exact_title_matches"] / both_days["eastmoney_rows"].clip(lower=1)
    else:
        both_days["exact_title_matches"] = pd.Series(dtype="int64")
        both_days["cninfo_match_rate"] = pd.Series(dtype="float64")
        both_days["eastmoney_match_rate"] = pd.Series(dtype="float64")

    summary: dict[str, object] = {
        "audit_only": True,
        "canonicalizer_used_for_trading_features": False,
        "cninfo_unique_notice_rows": int(len(cn)),
        "eastmoney_unique_notice_rows": int(len(em)),
        "exact_canonical_matches": int(len(exact)),
        "cninfo_stock_days": int(cn[["security_code", "published_date"]].drop_duplicates().shape[0]) if not cn.empty else 0,
        "eastmoney_stock_days": int(em[["security_code", "published_date"]].drop_duplicates().shape[0]) if not em.empty else 0,
        "overlap_stock_days": int(len(both_days)),
        "overlap_stock_days_with_any_exact_match": int((both_days["exact_title_matches"] > 0).sum()) if not both_days.empty else 0,
        "mean_cninfo_match_rate_on_overlap_days": float(both_days["cninfo_match_rate"].mean()) if not both_days.empty else None,
        "mean_eastmoney_match_rate_on_overlap_days": float(both_days["eastmoney_match_rate"].mean()) if not both_days.empty else None,
        "perfect_two_way_match_days": int(((both_days["cninfo_match_rate"] == 1.0) & (both_days["eastmoney_match_rate"] == 1.0)).sum()) if not both_days.empty else 0,
    }
    return summary, both_days


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit CNINFO vs Eastmoney historical notice coverage.")
    parser.add_argument("--cninfo", default="data_lake/raw/cninfo/notices/*.parquet")
    parser.add_argument("--eastmoney", default="data_lake/raw/eastmoney/notices/**/*.parquet")
    parser.add_argument("--output-json", default="output/v4_17_event_source_audit.json")
    parser.add_argument("--output-csv", default="output/v4_17_event_source_audit_stock_days.csv")
    args = parser.parse_args()

    cn, cn_diag = load_cninfo(args.cninfo)
    em, em_diag = load_eastmoney(args.eastmoney)
    summary, stock_days = audit(cn, em)
    summary["loader_diagnostics"] = {"cninfo": cn_diag, "eastmoney": em_diag}
    summary["source_loader_validation_pass"] = bool(
        em_diag.get("loader_validation_pass", True)
        and not cn_diag.get("unreadable_files")
    )

    out_json = Path(args.output_json)
    out_csv = Path(args.output_csv)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    stock_days.sort_values(["published_date", "security_code"]).to_csv(out_csv, index=False)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not stock_days.empty:
        print(stock_days.head(20).to_string(index=False))

    if not summary["source_loader_validation_pass"]:
        raise SystemExit("V4.17 event source audit loader validation failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
