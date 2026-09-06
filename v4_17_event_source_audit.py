from __future__ import annotations

import argparse
import glob
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd


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


def load_cninfo(pattern: str) -> pd.DataFrame:
    paths = sorted(glob.glob(pattern, recursive=True))
    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if frame.empty:
            continue
        required = {"security_code", "published_date", "title"}
        if not required.issubset(frame.columns):
            continue
        frame = frame.copy()
        frame["audit_source_path"] = path
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_eastmoney(pattern: str) -> pd.DataFrame:
    return load_cninfo(pattern)


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

    cn = load_cninfo(args.cninfo)
    em = load_eastmoney(args.eastmoney)
    summary, stock_days = audit(cn, em)

    out_json = Path(args.output_json)
    out_csv = Path(args.output_csv)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    stock_days.sort_values(["published_date", "security_code"]).to_csv(out_csv, index=False)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not stock_days.empty:
        print(stock_days.head(20).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
