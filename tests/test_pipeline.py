import numpy as np
import pandas as pd
import pytest

from caribou import scenarios as S


@pytest.fixture(scope="module")
def table(world):
    from caribou.pixels import range_pixel_table
    # a small tile forces the multi-tile path (10 km / 3.2 km -> 4x4 tiles)
    d, ann = range_pixel_table("TT1", res=100.0, tile_px=32, verbose=False)
    return d, ann


def test_area_exact(table):
    d, _ = table
    assert d["n"].sum() == 100 * 100  # 10 km x 10 km at 100 m


def test_annual_burned(table):
    _, ann = table
    a = ann.set_index("year")["n"]
    assert a[1983] == 2000 and a[2000] == 1000 and a[2023] == 2000


def test_reproduction(table):
    d, _ = table
    assert S.share_undisturbed(d, S.official(d, 2020)) == pytest.approx(0.5)
    assert S.share_undisturbed(d, S.official(d, 2015)) == pytest.approx(0.6)
    assert S.share_undisturbed(d, S.rebuild(d, 2020, "cnfdb")) == pytest.approx(0.5)
    assert S.share_undisturbed(d, S.rebuild(d, 2015, "cnfdb")) == pytest.approx(0.6)
    assert S.share(d, S.official(d) == S.rebuild(d, 2020, "cnfdb")) == pytest.approx(1.0)
    assert S.share(d, S.unexplained(d)) == pytest.approx(0.0)


def test_last_fire_is_latest(table):
    d, _ = table
    # strip 5-6 burned 1983 and 2023: CNFDB last fire 1983, post-2020 last fire 2023
    both = d[(d["lf_c20"] == 1983) & (d["lf_post"] == 2023)]
    assert both["n"].sum() == 1000


@pytest.mark.parametrize("rule,expected", [
    ("official_adj", 0.5),   # 0-2 human, 4-6 new fire, 7-8 fire 2000 ; 6-7 aged out
    ("rebuild_cnfdb", 0.5),
    ("rebuild_nbac", 0.5),
    ("no_ageout", 0.4),      # 6-7 stays disturbed
])
def test_update_rules(table, rule, expected):
    d, _ = table
    assert S.share_undisturbed(d, S.disturbed(d, 2025, rule)) == pytest.approx(expected)


def test_human_only(table):
    d, _ = table
    assert S.share_undisturbed(d, S.disturbed(d, 2025, fire=False)) == pytest.approx(0.8)


def test_components(table):
    d, _ = table
    assert S.share(d, S.aged_out(d, 2025)) == pytest.approx(0.2)        # strips 5-7
    post = d["lf_post"] > 2020
    assert S.share(d, post & ~S.official(d)) == pytest.approx(0.1)      # strip 4-5


def test_state_table_matches_rule(table):
    d, _ = table
    for rule in ("official_adj", "rebuild_cnfdb", "rebuild_nbac", "no_ageout"):
        st = S.state_table(d, rule)
        assert st["share"].sum() == pytest.approx(1.0)
        for y in (2025, 2030, 2045, 2070):
            if rule == "no_ageout" and y != 2025:
                continue
            assert S.state_undisturbed(st, y) == pytest.approx(
                S.share_undisturbed(d, S.disturbed(d, y, rule))), (rule, y)


def test_recovery(table):
    from caribou.recovery import recovery_for_state
    d, _ = table
    st = S.state_table(d, "official_adj")
    rec = recovery_for_state(st, 0.65)
    # 2000 fire leaves the window in 2040 (60%), 2023 fire in 2063 (80%)
    assert rec["recovery_class"] == "recovers with time"
    assert rec["recovery_year"] == 2063
    assert rec["ceiling"] == pytest.approx(0.8)
    assert recovery_for_state(st, 0.85)["recovery_class"] == "needs restoration"
    assert recovery_for_state(st, 0.85)["restore_share"] == pytest.approx(0.05)
    assert recovery_for_state(st, 0.40)["recovery_class"] == "meets now"


def test_forecast_limits(table):
    from caribou.forecast import simulate
    d, _ = table
    st = S.state_table(d, "official_adj")
    # no fire, no industry: 2030 = 2025 value (nothing ages out 2026-2030 here)
    u = simulate(st, np.zeros(10), 0.0, n_runs=100)
    assert np.allclose(u, 0.5)
    # everything burns every year: nothing undisturbed
    u = simulate(st, np.ones(10), 0.0, n_runs=100)
    assert np.allclose(u, 0.0)
    # 10% burns each year: undisturbed shrinks by 0.9 per year
    u = simulate(st, np.full(10, 0.1), 0.0, n_runs=100)
    assert np.allclose(u, 0.5 * 0.9 ** 5)
    # industry only: 1% of the range per year for 5 years, drawn proportionally
    # from non-permanent ground (0.8 of the range): undisturbed x 0.75/0.8
    u = simulate(st, np.zeros(10), 0.01, n_runs=100, rate_spread=(1, 1))
    assert np.allclose(u, 0.5 * 0.75 / 0.8)
    # catch-up years apply the same rate before 2026
    u = simulate(st, np.zeros(10), 0.01, n_runs=100, rate_spread=(1, 1), catchup_years=5)
    assert np.allclose(u, 0.5 * 0.70 / 0.8)


def test_decode_roundtrip():
    from caribou.pixels import BIT_LAYERS, YEAR_LAYERS, decode_keys
    k = np.array([0b1011 | (83 << 8) | (115 << 16) | (100 << 24) | (123 << 32)], dtype=np.uint64)
    df = decode_keys(k, [])
    assert list(df.loc[0, [c for c, _ in BIT_LAYERS]]) == [1, 1, 0, 1]
    assert list(df.loc[0, [c[0] for c in YEAR_LAYERS]]) == [1983, 2015, 2000, 2023]
