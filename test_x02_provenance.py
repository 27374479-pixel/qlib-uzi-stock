import json
from pathlib import Path

from x02_provenance import SELECTION_FILES, sha256_file, validate_reproduction_artifacts


def _fixture(tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    engine = tmp_path / "engine.py"
    engine.write_text("x = 1\n", encoding="utf-8")
    features = out / "features.parquet"
    features.write_bytes(b"feature-data")

    selection_artifacts = {}
    for variant, filename in SELECTION_FILES.items():
        path = out / filename
        path.write_bytes((variant + "-selection").encode("utf-8"))
        selection_artifacts[variant] = {
            "filename": filename,
            "sha256": sha256_file(path),
            "rows": 3,
            "active_days": 1,
        }

    report = {
        "engine_sha256": sha256_file(engine),
        "features_sha256": sha256_file(features),
        "selection_artifacts": selection_artifacts,
        "contract": {
            "top_n": 3,
            "rank": "clean_mom20_rank",
            "entry": "14:45 close",
            "exit": "next session 10:00",
            "limit_buffer": 0.005,
            "parameter_search": False,
            "announcements_used": False,
        },
    }
    (out / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return out, engine


def test_matching_lineage_passes(tmp_path: Path):
    out, engine = _fixture(tmp_path)
    result = validate_reproduction_artifacts(out, engine)
    assert result["pass"] is True
    assert result["report_sha256"]
    assert set(result["selection_sha256"]) == set(SELECTION_FILES)


def test_changed_features_fail_lineage(tmp_path: Path):
    out, engine = _fixture(tmp_path)
    (out / "features.parquet").write_bytes(b"other-data")
    result = validate_reproduction_artifacts(out, engine)
    assert result["pass"] is False
    assert any("features_sha256" in item for item in result["failures"])


def test_changed_frozen_selection_fails_lineage(tmp_path: Path):
    out, engine = _fixture(tmp_path)
    path = out / SELECTION_FILES["original_gate"]
    path.write_bytes(b"tampered-selection")
    result = validate_reproduction_artifacts(out, engine)
    assert result["pass"] is False
    assert any("selection artifact hash mismatch for original_gate" in item for item in result["failures"])


def test_report_without_features_hash_fails_lineage(tmp_path: Path):
    out, engine = _fixture(tmp_path)
    path = out / "report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report.pop("features_sha256")
    path.write_text(json.dumps(report), encoding="utf-8")
    result = validate_reproduction_artifacts(out, engine)
    assert result["pass"] is False


def test_report_without_selection_hash_fails_lineage(tmp_path: Path):
    out, engine = _fixture(tmp_path)
    path = out / "report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["selection_artifacts"]["no_market_gate"].pop("sha256")
    path.write_text(json.dumps(report), encoding="utf-8")
    result = validate_reproduction_artifacts(out, engine)
    assert result["pass"] is False


def test_contract_difference_fails_lineage(tmp_path: Path):
    out, engine = _fixture(tmp_path)
    path = out / "report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["contract"]["top_n"] = 5
    path.write_text(json.dumps(report), encoding="utf-8")
    result = validate_reproduction_artifacts(out, engine)
    assert result["pass"] is False
