from datetime import date
from unittest.mock import Mock

import pytest
import v4_17_point_in_time_announcement_backfill as collector


@pytest.mark.parametrize("payload,valid", [
    ({"success": 1, "error": "", "data": {"total_hits": 0, "list": []}}, True),
    ({"success": 0, "data": {"total_hits": 0, "list": []}}, False),
    ({"success": 1, "data": {"total_hits": 1, "list": []}}, False),
    ({"success": 1, "data": {"list": []}}, False),
    ({"success": 1, "data": {"total_hits": 0, "list": [{}]}}, False),
])
def test_only_explicit_successful_zero_is_empty(monkeypatch, payload, valid):
    response = Mock()
    response.json.return_value = payload
    monkeypatch.setattr(collector.requests, "get", Mock(return_value=response))
    if valid:
        frame = collector.verify_empty_archive(date(2021, 2, 12))
        assert frame.empty
        assert len(frame.attrs["empty_response_sha256"]) == 64
        assert frame.attrs["empty_response_json"]
    else:
        with pytest.raises(ValueError):
            collector.verify_empty_archive(date(2021, 2, 12))
