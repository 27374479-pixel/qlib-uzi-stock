from __future__ import annotations

import argparse
import glob
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd


def audit_title(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text)
    return text.lower()


def load(pattern: str) -> pd.DataFrame:
    paths = sorted(glob.glob(pattern, recursive=True))
    frames: list[pd.DataFrame] = []
    for path in paths:
        frame = pd.read_parquet(path)
        if frame.empty:
            continue
        frame = frame.copy()
        frame["_path"] = path
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main() -> int:
    parser = argparse.ArgumentParser(description="Identity/text QA for the canonical V4.17 event lake.")
    parser.add_argument("--input", default="data_lake/raw/cninfo/notices/*.parquet")
    parser.add_argument("--output-json", default="output/v4_17_event_lake_qa.json")
    parser.add_argument("--multi-doc-csv", default="output/v4_17_event_lake_multi_stock_documents.csv")
    parser.add_argument("--repeated-title-csv", default="output/v4_17_event_lake_repeated_titles.csv")
    args = parser.parse_args()

    frame = load(args.input)
    if frame.empty:
        raise SystemExit("no event-lake rows")

    required = {
        "event_id", "source_event_id", "security_code", "title", "published_date",
        "eligible_from_date", "event_time_precision", "knowledge_policy", "schema_version"
    }
    missing = required.difference(frame.columns)
    if missing:
        raise SystemExit(f"missing required columns: {sorted(missing)}")

    frame["security_code"] = frame["security_code"].astype(str).str.zfill(6)
    frame["published_ts"] = pd.to_datetime(frame["published_date"], errors="raise")
    frame["eligible_ts"] = pd.to_datetime(frame["eligible_from_date"], errors="raise")
    frame["source_event_id"] = frame["source_event_id"].fillna("").astype(str).str.strip()
    frame["audit_title"] = frame["title"].map(audit_title)

    if frame["event_id"].duplicated().any():
        raise AssertionError("global event_id duplication")
    if not (frame["eligible_ts"] > frame["published_ts"]).all():
        raise AssertionError("causal date violation")

    nonempty_sid = frame[frame["source_event_id"].ne("")].copy()
    if nonempty_sid.empty:
        multi_docs = pd.DataFrame(columns=["source_event_id", "published_date", "stock_count", "row_count", "security_codes", "titles"])
        source_doc_count = 0
    else:
        source_doc_count = int(nonempty_sid["source_event_id"].nunique())
        doc = nonempty_sid.groupby("source_event_id", sort=False).agg(
            published_date=("published_date", "min"),
            stock_count=("security_code", "nunique"),
            row_count=("event_id", "size"),
            security_codes=("security_code", lambda x: "|".join(sorted(set(x)))),
            titles=("title", lambda x: " || ".join(sorted(set(map(str, x))))),
        ).reset_index()
        multi_docs = doc[doc["stock_count"] > 1].sort_values(["stock_count", "published_date", "source_event_id"], ascending=[False, True, True]).reset_index(drop=True)

    title_groups = frame[frame["audit_title"].ne("")].groupby("audit_title", sort=False).agg(
        stock_count=("security_code", "nunique"),
        row_count=("event_id", "size"),
        first_date=("published_date", "min"),
        last_date=("published_date", "max"),
        example_title=("title", "first"),
    ).reset_index()
    repeated_titles = title_groups[title_groups["stock_count"] > 1].sort_values(
        ["stock_count", "row_count", "audit_title"], ascending=[False, False, True]
    ).reset_index(drop=True)

    year_counts = frame["published_ts"].dt.year.value_counts().sort_index().astype(int)
    per_stock = frame.groupby("security_code").size()
    direct_multi_rows = set(multi_docs["source_event_id"]) if not multi_docs.empty else set()
    direct_multi_frame = nonempty_sid[nonempty_sid["source_event_id"].isin(direct_multi_rows)] if direct_multi_rows else nonempty_sid.iloc[0:0]

    summary = {
        "qa_only": True,
        "used_for_trading_feature_selection": False,
        "schema_versions": sorted(map(str, frame["schema_version"].dropna().unique())),
        "total_rows": int(len(frame)),
        "unique_event_ids": int(frame["event_id"].nunique()),
        "unique_security_codes": int(frame["security_code"].nunique()),
        "min_published_date": frame["published_ts"].min().date().isoformat(),
        "max_published_date": frame["published_ts"].max().date().isoformat(),
        "rows_by_year": {str(int(k)): int(v) for k, v in year_counts.items()},
        "source_event_id_nonempty_rows": int(len(nonempty_sid)),
        "source_event_id_nonempty_fraction": float(len(nonempty_sid) / len(frame)),
        "unique_source_documents": source_doc_count,
        "direct_multi_stock_source_documents": int(len(multi_docs)),
        "direct_multi_stock_document_rows": int(len(direct_multi_frame)),
        "direct_multi_stock_unique_stocks": int(direct_multi_frame["security_code"].nunique()) if not direct_multi_frame.empty else 0,
        "max_stocks_on_one_source_document": int(multi_docs["stock_count"].max()) if not multi_docs.empty else 0,
        "canonical_titles_shared_across_stocks": int(len(repeated_titles)),
        "max_stocks_sharing_one_canonical_title": int(repeated_titles["stock_count"].max()) if not repeated_titles.empty else 0,
        "per_stock_row_quantiles": {
            "min": int(per_stock.min()),
            "p25": float(per_stock.quantile(0.25)),
            "median": float(per_stock.median()),
            "p75": float(per_stock.quantile(0.75)),
            "max": int(per_stock.max()),
        },
        "interpretation_guardrails": {
            "direct_multi_stock_source_document": "clean structural seed only; still requires point-in-time membership and book hypothesis validation",
            "repeated_canonical_title": "QA diagnostic only; generic legal/administrative titles must not be treated as themes",
            "future_returns_used": False,
            "current_concept_membership_used": False,
        },
    }

    out_json = Path(args.output_json)
    out_multi = Path(args.multi_doc_csv)
    out_repeat = Path(args.repeated_title_csv)
    for p in (out_json, out_multi, out_repeat):
        p.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    multi_docs.to_csv(out_multi, index=False)
    repeated_titles.head(500).to_csv(out_repeat, index=False)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not multi_docs.empty:
        print("\nTop direct multi-stock source documents:")
        print(multi_docs.head(20).to_string(index=False))
    print("\nTop cross-stock repeated canonical titles (QA only):")
    print(repeated_titles.head(20).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
