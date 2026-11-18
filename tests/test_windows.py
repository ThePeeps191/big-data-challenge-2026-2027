"""Pure functions of the open-data window detector (no network)."""

import numpy as np
import pytest


def test_dequantize_unit_vectors_and_nodata():
    from caribou.detector.windows import dequantize
    rng = np.random.default_rng(0)
    a = rng.integers(-127, 128, size=(64, 4, 4)).astype(np.int8)
    a[:, 0, 0] = -128                                   # masked pixel: all channels
    v, valid = dequantize(a)
    assert not valid[0, 0] and valid[1:, :].all()
    assert np.allclose(np.linalg.norm(v[:, valid], axis=0), 1.0, atol=1e-5)
    # Google's formula, up to the renormalization: (x / 127.5)^2 * sign(x)
    x = a[:, 1, 1].astype(np.float64)
    ref = (x / 127.5) ** 2 * np.sign(x)
    assert np.allclose(v[:, 1, 1], ref / np.linalg.norm(ref), atol=1e-5)


def test_components_drop_patches_under_2ha():
    from caribou.detector.windows import MIN_PX, components
    m = np.zeros((60, 60), bool)
    m[0:10, 0:10] = True            # 100 px = 1 ha at 10 m: dropped
    m[20:40, 20:40] = True          # 400 px = 4 ha: kept
    lab, n = components(m)
    assert MIN_PX == 200 and n == 1
    assert (lab > 0).sum() == 400


def test_classify_components():
    from caribou.detector.windows import classify_components
    from caribou.detector import windows as W
    shape = (80, 80)
    det = np.zeros(shape, bool)
    det[0:20, 0:20] = True          # on a federal polygon -> known
    det[0:20, 40:60] = True         # mostly inside a fire -> burn
    det[40:60, 0:20] = True         # nothing -> new
    det[40:60, 40:60] = True        # already "new" in 2020 -> not new again
    det[60:80, 60:80] = True        # half on a mapped polygon: the other half is new
    lay = {"poly_any": np.zeros(shape, np.uint8), "fire_2016_2025": np.zeros(shape, np.uint8)}
    lay["poly_any"][0:20, 0:20] = 1
    lay["poly_any"][60:80, 60:70] = 1
    lay["fire_2016_2025"][0:20, 40:55] = 1
    prior = np.zeros(shape, bool)
    prior[50, 50] = True
    parts = classify_components(det, lay, 2025, prior_new=prior)
    assert parts["known"][0:20, 0:20].all() and parts["known"].sum() == 400 + 200
    assert parts["burn"][0:20, 40:60].all() and parts["burn"].sum() == 400
    assert parts["new"][40:60, 0:20].all()
    # the extension of a mapped cutblock: 20 x 10 px minus the 2-px edge margin = 160 px
    # (< 2 ha) is dropped; a wider extension would be kept
    assert parts["new"][60:80, 60:80].sum() == 0
    det2, lay2 = det.copy(), {k: v.copy() for k, v in lay.items()}
    lay2["poly_any"][60:80, 60:80] = 0
    lay2["poly_any"][60:80, 60:62] = 1
    parts2 = classify_components(det2, lay2, 2025, prior_new=prior)
    assert parts2["new"][60:80, 64:80].all()          # 20 x 16 = 320 px >= 2 ha: kept
    assert parts["new"].sum() == 400
    assert W.MIN_PX <= 400


def test_buffer_is_500m():
    from caribou.detector.windows import BUFFER_PX, buffer
    m = np.zeros((201, 201), bool)
    m[100, 100] = True
    b = buffer(m)
    assert BUFFER_PX == 50
    assert b[100, 150] and not b[100, 151]
    assert b.sum() == pytest.approx(np.pi * 50 ** 2, rel=0.02)
