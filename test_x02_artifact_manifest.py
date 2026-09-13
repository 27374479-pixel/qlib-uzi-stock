import json
from pathlib import Path

from bind_x02_execution_artifacts import build_manifest, expected_execution_files


def test_manifest_passes_when_all_outputs_exist(tmp_path: Path):
    audit = tmp_path / "next_bar_execution_audit.json"
    audit.write_text(json.dumps({"inputs": {"pass": True}}), encoding="utf-8")
    for name in expected_execution_files():
        (tmp_path / name).write_text("ok", encoding="utf-8")
    result = build_manifest(tmp_path, audit)
    assert result["pass"] is True
    assert result["audit_sha256"]


def test_manifest_fails_when_output_is_missing(tmp_path: Path):
    audit = tmp_path / "next_bar_execution_audit.json"
    audit.write_text(json.dumps({"inputs": {"pass": True}}), encoding="utf-8")
    names = expected_execution_files()
    for name in names[:-1]:
        (tmp_path / name).write_text("ok", encoding="utf-8")
    result = build_manifest(tmp_path, audit)
    assert result["pass"] is False
    assert any(names[-1] in item for item in result["failures"])
