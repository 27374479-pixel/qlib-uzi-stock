from audit_x02_minute_bar_structure import build_report, classify_label_contract


def _record(counts, duplicate_keys=0):
    structure = classify_label_contract(counts, duplicate_keys)
    return {"duplicate_keys": duplicate_keys, "structure": structure}


def test_end_label_pattern_is_consistent_but_not_claimed_as_proof():
    result = classify_label_contract(
        {"09:30": 0, "09:35": 100, "14:45": 100, "14:50": 100, "15:00": 100},
        0,
    )
    assert result["pass"] is True
    assert result["inference"] == "CONSISTENT_WITH_END_LABELLED_5M_NOT_PROOF"
    assert "do not by themselves prove" in result["interpretation_boundary"]


def test_duplicate_timestamp_keys_fail_the_contract():
    result = classify_label_contract(
        {"09:35": 100, "14:45": 100, "14:50": 100, "15:00": 100},
        2,
    )
    assert result["pass"] is False
    assert any("duplicate" in failure for failure in result["failures"])


def test_0930_rows_make_label_semantics_ambiguous_without_failing_adjacency():
    result = classify_label_contract(
        {"09:30": 100, "09:35": 100, "14:45": 100, "14:50": 100, "15:00": 100},
        0,
    )
    assert result["pass"] is True
    assert result["inference"] == "LABEL_SEMANTICS_AMBIGUOUS"
    assert result["warnings"]


def test_missing_next_bar_label_fails():
    result = classify_label_contract(
        {"09:35": 100, "14:45": 100, "14:50": 0, "15:00": 100},
        0,
    )
    assert result["pass"] is False
    assert "14:50-labelled bars are absent" in result["failures"]


def test_report_requires_every_file_to_pass():
    good = _record({"09:35": 10, "14:45": 10, "14:50": 10, "15:00": 10})
    bad = _record({"09:35": 10, "14:45": 10, "14:50": 10, "15:00": 10}, duplicate_keys=1)
    report = build_report([good, bad])
    assert report["validation"]["pass"] is False
    assert report["validation"]["file_count"] == 2
