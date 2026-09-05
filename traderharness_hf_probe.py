from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from huggingface_hub import HfApi

REPO_ID = "ANTICH/traderharness-ashare-5y"
OUT = Path("output/traderharness_hf_probe.json")
OUT.parent.mkdir(exist_ok=True)

api = HfApi()
files = []
years: dict[str, dict[str, object]] = defaultdict(lambda: {"files": 0, "bytes": 0, "paths": []})

for item in api.list_repo_tree(
    repo_id=REPO_ID,
    repo_type="dataset",
    recursive=True,
    expand=True,
):
    path = getattr(item, "path", None)
    if not path or not str(path).startswith("5min_clean/") or not str(path).endswith(".parquet"):
        continue
    size = int(getattr(item, "size", 0) or 0)
    rec = {"path": str(path), "bytes": size}
    files.append(rec)
    year = "unknown"
    for part in str(path).split("/"):
        if part.startswith("year="):
            year = part.split("=", 1)[1]
            break
    years[year]["files"] = int(years[year]["files"]) + 1
    years[year]["bytes"] = int(years[year]["bytes"]) + size
    years[year]["paths"].append(str(path))

result = {
    "repo_id": REPO_ID,
    "five_minute_file_count": len(files),
    "five_minute_total_bytes": sum(x["bytes"] for x in files),
    "years": dict(sorted(years.items())),
    "target_2025_2026": {
        "files": int(years.get("2025", {}).get("files", 0)) + int(years.get("2026", {}).get("files", 0)),
        "bytes": int(years.get("2025", {}).get("bytes", 0)) + int(years.get("2026", {}).get("bytes", 0)),
        "paths": list(years.get("2025", {}).get("paths", [])) + list(years.get("2026", {}).get("paths", [])),
    },
}

OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in result.items() if k != "years"}, ensure_ascii=False, indent=2))
for year, info in result["years"].items():
    print(year, "files=", info["files"], "bytes=", info["bytes"])
print("saved", OUT)
