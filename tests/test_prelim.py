"""Preliminary 2026 update on the synthetic world (see conftest.py for the strips)."""

import pytest

from caribou import scenarios as S


@pytest.fixture(scope="module")
def prelim_table(world):
    from caribou.pixels import load_table
    from caribou.prelim import TAG, _pixel_job
    _pixel_job("TT1", 100.0)
    return load_table("TT1", 100.0, TAG)


def test_extra_masks(prelim_table):
    d = prelim_table
    assert S.share(d, d["f26"] == 1) == pytest.approx(0.2)
    assert S.share(d, d["c2124"] == 1) == pytest.approx(0.2)


def test_cnfdb_post_rule(prelim_table):
    from caribou.prelim import cnfdb_post_rule
    d = prelim_table
    # disturbed: 0-2 human, 4-5 CNFDB 2023, 7-8 fire 2000, 8-9 CNFDB 2022;
    # 5-6 (NBAC 2023 reburn) is not in CNFDB 2021-2024, 6-7 aged out
    assert S.share_undisturbed(d, cnfdb_post_rule(d, 2025)) == pytest.approx(0.5)
    assert S.share(d, cnfdb_post_rule(d, 2025) & (d["c2124"] == 1) & ~S.disturbed(d, 2025)) \
        == pytest.approx(0.1)  # strip 8-9: the fire only CNFDB has


def test_score_2026(prelim_table):
    from caribou.prelim import score
    k = {"central": 0.8, "lo": 0.5, "hi": 1.0}
    r = score("TT1", 0.65, k, n_runs=200)
    # no 2026 fire: same as 2025 (nothing ages out in 2026 here)
    assert r["u2026_nofire_official_adj"] == pytest.approx(0.5)
    # only strip 3-4 is new ground under the estimate
    assert r["new2026_est_official_adj"] == pytest.approx(0.1)
    assert r["central_2026"] == pytest.approx(0.5 - 0.8 * 0.1)
    # band: lowest = no_ageout (0.4) - 0.1; highest = cnfdb_post (0.5, strip 5-6
    # undisturbed but 8-9 disturbed; its new 2026 ground is 3-4) - 0.5 * 0.1
    assert r["band_lo_2026"] == pytest.approx(0.4 - 0.1)
    assert r["band_hi_2026"] == pytest.approx(0.5 - 0.5 * 0.1)
    assert r["status_2026"] == "below"
    # recovery from 2026 with the estimate at face value: the 2023 burn leaves the
    # window in 2063 (0.6), the 2026 burns in 2066 (0.8)
    assert r["recovery_class_from2026"] == "recovers with time"
    assert r["recovery_year_from2026"] == 2066
    assert r["undisturbed_now_from2026"] == pytest.approx(0.4)
