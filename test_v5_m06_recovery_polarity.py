import pandas as pd
import v5_m06_recovery_polarity as m06


def sample():
    data = {"date": pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])}
    for name in m06.ORIENTATION:
        data[f"delta_{name}"] = [None, 0.1, -0.2]
    return pd.DataFrame(data)


def test_mapping_and_missingness():
    x = sample()
    out = m06.build_recovery_polarity(x)
    assert out.iloc[0].drop(labels=["date"]).isna().all()
    for name, direction in m06.ORIENTATION.items():
        assert out.loc[1, f"aligned_delta_{name}"] == 0.1 * direction
        assert out.loc[1, f"polarity_{name}"] == (1 if direction == 1 else -1)


def test_invariants_pass():
    x = sample()
    out = m06.build_recovery_polarity(x)
    assert not any(m06.invariant_failures(x, out).values())


def test_mutation_is_detected():
    x = sample()
    out = m06.build_recovery_polarity(x)
    out.loc[1, "polarity_advance_ratio"] = -1
    assert m06.invariant_failures(x, out)["polarity_sign_mismatch"] == 1


def test_future_change_does_not_change_past():
    x = sample()
    short = m06.build_recovery_polarity(x.iloc[:2].copy())
    x.loc[2, [c for c in x.columns if c.startswith("delta_")]] = 0.77
    full = m06.build_recovery_polarity(x)
    pd.testing.assert_frame_equal(short.reset_index(drop=True), full.iloc[:2].reset_index(drop=True))
