"""Tests for the daylight measurement. Synthetic masks only.

    python -m unittest pipeline.test_daylight        # needs numpy and scipy
"""
import unittest

try:
    import numpy as np
    import scipy  # noqa: F401
    from pipeline import daylight as dl
except ImportError:          # the screen's own tests still run without the image stack
    dl = None

RES = 20.0  # px per metre


def plate_mask(w_m=40, h_m=20, core=(8, 4), speck=False):
    """A w x h metre floor, unscanned core in the middle, optional stray speck outside the facade."""
    pad = 10
    m = np.zeros((int((h_m + 2 * pad) * RES), int((w_m + 2 * pad) * RES)), bool)
    y0, x0 = int(pad * RES), int(pad * RES)
    m[y0:y0 + int(h_m * RES), x0:x0 + int(w_m * RES)] = True
    if core:
        cy, cx = y0 + int((h_m - core[1]) / 2 * RES), x0 + int((w_m - core[0]) / 2 * RES)
        m[cy:cy + int(core[1] * RES), cx:cx + int(core[0] * RES)] = False
    if speck:
        m[5:9, 5:9] = True        # 0.2 m reflection fleck in the corner
    return m


@unittest.skipIf(dl is None, "numpy and scipy are needed for the daylight measurement")
class Plate(unittest.TestCase):
    def test_core_is_filled_and_speck_dropped(self):
        plate = dl.floor_plate(plate_mask(speck=True), RES)
        self.assertAlmostEqual(plate.sum() / RES ** 2, 800, delta=8)     # the whole 40 x 20 m plate
        self.assertFalse(plate[6, 6])

    def test_measures(self):
        out = dl.measure(plate_mask(), RES)
        self.assertAlmostEqual(out["plateSf"], 800 * dl.SF_PER_M2, delta=100)
        self.assertAlmostEqual(out["scannedSf"], (800 - 32) * dl.SF_PER_M2, delta=100)
        self.assertAlmostEqual(out["deepestFt"], 10 * dl.FT_PER_M, delta=0.5)        # half the 20 m depth
        # every point is within 10 m (32.8 ft) of the facade: all within 35 ft, some beyond 30 ft
        self.assertEqual(out["within35ft"], 1.0)
        self.assertGreater(out["within30ft"], 0.9)
        self.assertLess(out["within30ft"], 1.0)

    def test_high_resolution_plans_are_resampled(self):
        hi = np.kron(plate_mask(core=None), np.ones((5, 5), bool))       # same floor at 100 px/m
        out = dl.measure(hi, RES * 5)
        self.assertAlmostEqual(out["plateSf"], 800 * dl.SF_PER_M2, delta=100)

    def test_best_plan_picks_sharpest_alpha_png(self):
        model = {"assets": {"floorplans": [
            {"format": "jpg", "flags": ["photogramy"], "resolution": 100, "width": 10, "url": "a"},
            {"format": "png", "flags": ["photogramy", "alpha"], "resolution": 28, "width": 10, "url": "b"},
            {"format": "png", "flags": ["photogramy", "alpha"], "resolution": 100, "width": 10, "url": "c"},
            {"format": "png", "flags": ["photogramy", "alpha"], "resolution": 200, "url": "d"},     # no width: skipped
        ]}}
        self.assertEqual(dl.best_plan(model)["url"], "c")


if __name__ == "__main__":
    unittest.main()
