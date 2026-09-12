import pytest
from context_evidence_records import bind_claim


def test_quote_offsets_allow_layout_whitespace():
    result = bind_claim('甲 乙\n未完成', 'status', 'NOT_COMPLETE', '甲乙未完成')
    assert result['normalized_start'] == 0
    assert result['normalized_end'] == 5


@pytest.mark.parametrize('quote', ['', '已完成'])
def test_missing_or_opposite_evidence_is_rejected(quote):
    with pytest.raises(ValueError):
        bind_claim('交易未完成', 'status', 'COMPLETE', quote)
