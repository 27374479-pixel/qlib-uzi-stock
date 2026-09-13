"""Resume the full canonical archive in an isolated local staging directory.

No outcome tests run here. Progress and logs survive the terminal session.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
STAGE = ROOT / "data_lake/local_rebuild_20260911"
OUT = ROOT / "output/local_event_rebuild_20260911"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Refuse simultaneous writers; an interrupted process leaves a visible lock
    # for inspection rather than allowing concurrent parquet replacement.
    lock = OUT / "writer.lock"
    with lock.open("x", encoding="utf-8") as fh:
        import os
        fh.write(str(os.getpid()))
    state = {"status": "RUNNING", "completed_years": [], "start": "2021-01-01", "end": "2026-07-16"}

    def save():
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        temporary = OUT / "progress.tmp"
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(OUT / "progress.json")

    def run(script, arguments):
        state["step"] = script
        save()
        with (OUT / "run.log").open("a", encoding="utf-8") as log:
            subprocess.run([sys.executable, "-u", str(ROOT / script), *arguments],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=6 * 3600)

    roots = ["--event-root", str(STAGE / "notices"), "--manifest-root", str(STAGE / "manifests")]
    try:
        for year in range(2021, 2027):
            state["year"] = year
            window = ["--start", f"{year}-01-01", "--end", f"{year}-12-31" if year < 2026 else "2026-07-16"]
            run("v4_17_point_in_time_announcement_backfill.py", window + [
                "--output-root", str(STAGE / "notices"), "--manifest-root", str(STAGE / "manifests"),
                "--resume", "--max-retries", "5",
            ])
            validation = str(OUT / f"validation_{year}.json")
            run("v4_17_validate_event_lake.py", window + roots + ["--output", validation])
            run("v4_17_full_backfill_gate.py", window + roots + ["--validation", validation, "--output", str(OUT / f"gate_{year}.json")])
            state["completed_years"].append(year)
            save()
        window = ["--start", state["start"], "--end", state["end"]]
        validation = str(OUT / "validation_full.json")
        run("v4_17_validate_event_lake.py", window + roots + ["--output", validation])
        run("v4_17_full_backfill_gate.py", window + roots + ["--validation", validation, "--output", str(OUT / "gate_full.json")])
        state["status"] = "FULL_ARCHIVE_PASS_REQUIRES_SOURCE_AUDIT"
    except BaseException as exc:
        state["status"] = "FAILED"
        state["error"] = str(exc)
        raise
    finally:
        save()
        lock.unlink()


if __name__ == "__main__":
    main()
