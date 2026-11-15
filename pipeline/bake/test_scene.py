"""Tests for the walkthrough scene bake: outline, corner squaring, daylight band. Synthetic floors, no network.

    python -m unittest pipeline.bake.test_scene        # needs numpy, scipy, opencv, Pillow
"""
import math
import unittest

try:
    import numpy as np
    from pipeline.bake import scene
except ImportError:          # the image stack is optional for the rest of the pipeline tests
    scene = None

RES = 20.0


class FakePlate:
    """A Plate built from a raster we draw, origin at (0, 0), RES px/m."""

    def __init__(self, plate, scanned=None):
        self.plate = plate
        self.scanned = plate if scanned is None else scanned
        h, w = plate.shape
        self.mx = self.my = 1 / RES
        self.ox, self.oy = 0.0, 0.0
        self.top = h / RES

    def to_m(self, col, row):
        return self.ox + col * self.mx, self.top - row * self.my

    def distance_m(self):
        return scene.Plate.distance_m(self)


def rect_plate(w_m=40, h_m=20, pad_m=3, chamfer_m=0.0):
    w, h, pad = int(w_m * RES), int(h_m * RES), int(pad_m * RES)
    m = np.zeros((h + 2 * pad, w + 2 * pad), bool)
    m[pad:pad + h, pad:pad + w] = True
    c = int(chamfer_m * RES)
    for i in range(c):                                   # cut the top-left corner diagonally
        m[pad + i, pad:pad + c - i] = False
    return m


@unittest.skipIf(scene is None, "numpy, scipy and opencv are needed for the scene bake")
class Outline(unittest.TestCase):
    def test_rectangle_with_noisy_corner_becomes_four_square_walls(self):
        segs = scene.outline("x", FakePlate(rect_plate(chamfer_m=1.2)))
        self.assertEqual(len(segs), 4)
        for x1, y1, x2, y2 in segs:                          # every wall exactly horizontal or vertical
            self.assertTrue(abs(x1 - x2) < 1e-6 or abs(y1 - y2) < 1e-6, (x1, y1, x2, y2))
        xs = sorted({round(v, 1) for s in segs for v in (s[0], s[2])})
        ys = sorted({round(v, 1) for s in segs for v in (s[1], s[3])})
        self.assertAlmostEqual(xs[-1] - xs[0], 40, delta=0.3)
        self.assertAlmostEqual(ys[-1] - ys[0], 20, delta=0.3)

    def test_segments_close_the_loop(self):
        segs = scene.outline("x", FakePlate(rect_plate()))
        for a, b in zip(segs, segs[1:] + segs[:1]):
            self.assertAlmostEqual(a[2], b[0], places=6)
            self.assertAlmostEqual(a[3], b[1], places=6)

    def test_a_real_angled_wall_is_kept(self):
        m = rect_plate(40, 20, chamfer_m=8)                  # an 11 m diagonal: a real wall, not noise
        segs = scene.outline("x", FakePlate(m))
        diagonal = [s for s in segs if abs(s[0] - s[2]) > 1 and abs(s[1] - s[3]) > 1]
        self.assertEqual(len(diagonal), 1)
        self.assertGreater(math.hypot(diagonal[0][2] - diagonal[0][0], diagonal[0][3] - diagonal[0][1]), 8)


@unittest.skipIf(scene is None, "numpy, scipy and opencv are needed for the scene bake")
class Band(unittest.TestCase):
    def test_share_and_colours(self):
        # 40 x 20 m: every point is within 10 m of a wall, so all within 30 ft (9.14 m) except a 1.7 x 21.7 m strip
        rect, share, img = scene.band("x", FakePlate(rect_plate()))
        expected = 1 - (20 - 2 * 9.144) * (40 - 2 * 9.144) / (40 * 20)
        self.assertAlmostEqual(share, expected, delta=0.01)
        a = np.array(img)
        amber = (a[..., 0] == 255) & (a[..., 3] > 0)
        blue = (a[..., 2] == 140) & (a[..., 3] > 0)
        self.assertGreater(amber.sum(), 0)
        self.assertGreater(blue.sum(), 0)
        self.assertEqual(a[0, 0, 3], 0)                      # outside the floor: transparent

    def test_rect_covers_plate_with_margin_and_matches_image(self):
        rect, _, img = scene.band("x", FakePlate(rect_plate(pad_m=3)))
        x, y, w, h = rect
        self.assertAlmostEqual(w, 40 + 2 * scene.BAND_MARGIN_M, delta=0.1)
        self.assertAlmostEqual(h, 20 + 2 * scene.BAND_MARGIN_M, delta=0.1)
        self.assertAlmostEqual(img.width / w, RES, delta=0.5)
        self.assertAlmostEqual(img.height / h, RES, delta=0.5)

    def test_band_over_a_given_rect_matches_the_plate_band(self):
        fp = FakePlate(rect_plate(pad_m=3))
        rect, share, img = scene.band("x", fp)
        r2, s2, img2 = scene.band("x", fp, rect)                # the same rectangle, drawn the other way
        self.assertAlmostEqual(share, s2, places=3)
        self.assertEqual(r2, rect)
        a, b = np.array(img)[..., 3] > 0, np.array(img2.resize(img.size))[..., 3] > 0
        self.assertGreater((a == b).mean(), 0.99)


if __name__ == "__main__":
    unittest.main()
