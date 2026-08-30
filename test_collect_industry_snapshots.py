from collect_industry_snapshots import baostock_to_qlib, industry_code


def test_industry_normalization():
    assert baostock_to_qlib("sh.600000") == "SH600000"
    assert baostock_to_qlib("sz.000001") == "SZ000001"
    assert industry_code("C15酒、饮料和精制茶制造业") == "C15"
    assert industry_code("J66货币金融服务") == "J66"
