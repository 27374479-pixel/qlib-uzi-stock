import pytest
from fetch_context_body_pilot import validate_page


def test_page_validates_identity_date_and_body():
    data = dict(art_code='AN1', notice_date='2021-01-01', notice_content='正文', page_size=2)
    assert validate_page({'data': data}, 'AN1', '2021-01-01')[1] == 2
    for field, value in [('art_code', 'AN2'), ('notice_date', '2022-01-01'), ('notice_content', ''), ('page_size', 0)]:
        with pytest.raises(ValueError):
            validate_page({'data': dict(data, **{field: value})}, 'AN1', '2021-01-01')
