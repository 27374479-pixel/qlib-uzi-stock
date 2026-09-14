import pandas as pd
import v5_m06_recovery_direction_semantics as m06
from v5_m05_recovery_dynamics import LEVEL_COLUMNS


def _frame():
    rows=[]
    for i,date in enumerate(pd.to_datetime(["2026-01-05","2026-01-06","2026-01-07"])):
        row={"date":date}
        for c in LEVEL_COLUMNS:
            if i==0:
                row[f"delta_{c}"]=None
            elif i==1:
                row[f"delta_{c}"]=0.1 if m06.POLARITY[c]==1 else -0.1
            else:
                row[f"delta_{c}"]=-0.1 if m06.POLARITY[c]==1 else 0.1
        rows.append(row)
    return pd.DataFrame(rows)


def test_polarity_exactly_covers_frozen_m05_levels():
    m06.validate_polarity()
    assert set(m06.POLARITY)==set(LEVEL_COLUMNS)


def test_direction_mapping_and_counts():
    out=m06.build_direction_semantics(_frame())
    assert out.iloc[0]["available_dimension_n"]==0
    assert out.iloc[0]["unavailable_dimension_n"]==len(LEVEL_COLUMNS)
    assert out.iloc[1]["improving_dimension_n"]==len(LEVEL_COLUMNS)
    assert out.iloc[2]["deteriorating_dimension_n"]==len(LEVEL_COLUMNS)
    assert not any(m06.invariant_failures(out).values())


def test_missing_delta_stays_unavailable_not_zero():
    frame=_frame()
    frame.loc[1,"delta_prior_seal_mean_return"]=None
    out=m06.build_direction_semantics(frame)
    assert pd.isna(out.loc[1,"direction_prior_seal_mean_return"])
    assert out.loc[1,"available_dimension_n"]==len(LEVEL_COLUMNS)-1


def test_zero_delta_is_unchanged():
    frame=_frame()
    for c in LEVEL_COLUMNS:
        frame.loc[1,f"delta_{c}"]=0.0
    out=m06.build_direction_semantics(frame)
    assert out.loc[1,"unchanged_dimension_n"]==len(LEVEL_COLUMNS)


def test_contract_forbids_classifier_and_trading_promotion():
    c=m06.CONTRACT
    assert c["parameter_search"] is False
    assert c["aggregate_recovery_score_authorized"] is False
    assert c["market_state_label_authorized"] is False
    assert c["w01_return_screen_authorized"] is False
    assert c["x02_change_authorized"] is False
    assert c["portfolio_combination_authorized"] is False
    assert c["paper_trading_authorized"] is False
    assert c["live_trading_authorized"] is False
