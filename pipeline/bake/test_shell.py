"""Tests for the empty-floor shell bake: photo lookup, wall outline, ceiling, walk mask, atlas. Synthetic, no network.

    python -m unittest pipeline.bake.test_shell        # needs numpy, scipy, opencv, Pillow
"""
import math
import unittest

try:
    import numpy as np
    from pipeline import floorprep
    from pipeline.bake import shell
except ImportError:          # the image stack is optional for the rest of the pipeline tests
    shell = None

IDENTITY = (0.0, 0.0, 0.0, 1.0)


def grid_for(w_m, h_m, x0=0.0, y0=0.0):
    return floorprep.Grid(x0, y0, int(w_m * floorprep.RES), int(h_m * floorprep.RES))


@unittest.skipIf(shell is None, "numpy / opencv not installed")
class PhotoLookup(unittest.TestCase):
    def face_of(self, d, q=IDENTITY):
        f, s, t = shell.cube_lookup((np.array([d], float)) @ shell.cube_matrix(q).T)
        return shell.FACE_ORDER[int(f[0])], float(s[0]), float(t[0])

    def test_down_is_the_floor_face_and_up_the_ceiling_face(self):
        self.assertEqual(self.face_of([0, 0, -1])[0], 5)
        self.assertEqual(self.face_of([0, 0, 1])[0], 0)

    def test_down_stays_down_whatever_the_heading(self):
        for yaw in (0, 0.7, 2.0, -2.5):
            q = (0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2))
            self.assertEqual(self.face_of([0, 0, -1], q)[0], 5)

    def test_horizontal_lands_mid_height_on_a_side_face(self):
        for d in ([1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0]):
            face, s, t = self.face_of(d)
            self.assertIn(face, (1, 2, 3, 4))
            self.assertAlmostEqual(t, 0.5, places=6)
            self.assertAlmostEqual(s, 0.5, places=6)

    def test_the_four_sides_are_four_different_faces(self):
        faces = {self.face_of(d)[0] for d in ([1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0])}
        self.assertEqual(faces, {1, 2, 3, 4})

    def test_higher_points_are_nearer_the_top_row(self):
        _, _, t_low = self.face_of([1, 0, -0.3])
        _, _, t_high = self.face_of([1, 0, 0.3])
        self.assertLess(t_high, 0.5)
        self.assertGreater(t_low, 0.5)

    def test_quaternion_matrix_is_a_rotation(self):
        q = np.array([0.1, -0.2, 0.7, 0.6])
        q = q / np.linalg.norm(q)
        R = shell.quat_matrix(*q)
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-9)
        self.assertAlmostEqual(np.linalg.det(R), 1.0, places=9)


@unittest.skipIf(shell is None, "numpy / opencv not installed")
class Smoothing(unittest.TestCase):
    def test_majority_removes_a_lone_flip(self):
        c = np.array([1, 1, 1, 1, 2, 1, 1, 1, 1])
        self.assertTrue((shell.majority(c, 5) == 1).all())

    def test_majority_fills_gaps(self):
        c = np.array([3, 3, -1, 3, 3])
        self.assertEqual(shell.majority(c, 3)[2], 3)

    def test_mirror_fill_copies_the_neighbouring_stretch(self):
        img = np.zeros((4, 10, 3), np.uint8)
        img[:, :5] = np.arange(5)[None, :, None] * 10
        bad = np.zeros(10, bool)
        bad[5:8] = True
        out = shell.mirror_fill(img.copy(), bad)
        self.assertEqual(list(out[0, 5:8, 0]), [40, 30, 20])          # mirrored about the join
        self.assertEqual(list(out[0, :5, 0]), [0, 10, 20, 30, 40])     # the good part untouched


@unittest.skipIf(shell is None, "numpy / opencv not installed")
class Outline(unittest.TestCase):
    def test_inward_normal_points_into_the_floor(self):
        g = grid_for(20, 10)
        poly = [(0, 0), (20, 0), (20, 10), (0, 10)]
        plate = shell.raster_polygon(poly, g)
        np.testing.assert_allclose(shell.inward_normal((0, 0), (20, 0), plate, g), [0, 1])
        np.testing.assert_allclose(shell.inward_normal((20, 10), (0, 10), plate, g), [0, -1])
        np.testing.assert_allclose(shell.inward_normal((0, 10), (0, 0), plate, g), [1, 0])

    def test_window_line_ignores_reflection_streaks_and_an_unscanned_room(self):
        g = grid_for(40, 24, -2, -2)
        floor = shell.raster_polygon([(0, 0), (36, 0), (36, 20), (0, 20)], g)
        mask = floor.copy()
        room = shell.raster_polygon([(10, 17.5), (12.5, 17.5), (12.5, 20), (10, 20)], g)
        mask &= ~room                                                         # a room nobody walked into
        c, r = g.to_px(np.linspace(36, 37.8, 40), np.full(40, 10.0))
        mask[np.round(r).astype(int), np.round(c).astype(int)] = True        # a thin reflection streak
        wl = shell.window_line(mask, g)
        xs, ys = [p[0] for p in wl], [p[1] for p in wl]
        self.assertEqual(len(wl), 4)
        self.assertAlmostEqual(min(xs), 0, delta=0.25)
        self.assertAlmostEqual(max(xs), 36, delta=0.25)
        self.assertAlmostEqual(max(ys), 20, delta=0.25)
        self.assertAlmostEqual(shell.polygon_area(wl), 720, delta=22)          # within 3%: the edge is traced on pixel centres

    def test_main_axis_follows_the_long_walls(self):
        a = math.radians(12)
        rot = lambda x, y: (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))
        poly = [rot(*p) for p in [(0, 0), (30, 0), (30, 12), (0, 12)]]
        self.assertAlmostEqual(shell.main_axis_deg(poly), 12, delta=1)

    def test_clean_scene_outline_is_kept(self):
        g = grid_for(40, 24, -2, -2)
        rect = [(0, 0), (36, 0), (36, 20), (0, 20)]
        scene = {"outline": [list(a) + list(b) for a, b in zip(rect, rect[1:] + rect[:1])]}
        poly, src = shell.choose_outline(scene, shell.raster_polygon(rect, g), g)
        self.assertEqual(src, "scene")
        self.assertEqual(poly, rect)

    def test_bulging_scene_outline_gives_way_to_the_window_line(self):
        g = grid_for(48, 30, -6, -6)
        rect = [(0, 0), (36, 0), (36, 20), (0, 20)]
        bulgy = [(0, 0), (12, -4), (24, 0), (36, 0), (40, 6), (36, 12), (36, 20), (24, 24), (12, 20), (0, 20), (-4, 10)]
        scene = {"outline": [list(a) + list(b) for a, b in zip(bulgy, bulgy[1:] + bulgy[:1])]}
        poly, src = shell.choose_outline(scene, shell.raster_polygon(rect, g), g)
        self.assertEqual(src, "window line")
        self.assertAlmostEqual(shell.polygon_area(poly), 720, delta=22)


@unittest.skipIf(shell is None, "numpy / opencv not installed")
class Ceiling(unittest.TestCase):
    def test_fitted_ceiling_keeps_ceil_y(self):
        rng = np.random.default_rng(1)
        V = np.c_[rng.random((5000, 2)), np.r_[rng.normal(2.6, 0.01, 4000), rng.random(1000) * 2.6]]
        self.assertEqual(shell.ceiling_height(V, {"ceilY": 2.6}), (2.6, "scene"))

    def test_exposed_deck_raises_the_walls(self):
        rng = np.random.default_rng(2)
        V = np.c_[rng.random((6000, 2)), np.r_[rng.normal(3.8, 0.01, 4000), rng.normal(2.69, 0.01, 300),
                                                rng.random(1700) * 2.6]]
        z1, src = shell.ceiling_height(V, {"ceilY": 2.69})
        self.assertEqual(src, "exposed deck")
        self.assertAlmostEqual(z1, 3.8, delta=0.03)


@unittest.skipIf(shell is None, "numpy / opencv not installed")
class WalkAndAtlas(unittest.TestCase):
    def test_walk_mask_row_zero_is_north_and_columns_are_kept_off(self):
        scene = {"bandRect": [0, 0, 20, 10]}
        img = shell.walk_mask(scene, [(0, 0), (20, 0), (20, 10), (0, 10)],
                              [{"outer": [[0, 7], [5, 7], [5, 10], [0, 10]], "holes": []}],
                              [{"x": 15, "y": 5, "size": 0.6, "grade": "probable"}])
        P = shell.WALK_PX_PER_M
        self.assertEqual(img.shape, (10 * P, 20 * P))
        px = lambda x, y: img[int((10 - y) * P), int(x * P)]
        self.assertEqual(px(2, 9), 0)            # the core block is in the north-west corner: top-left of the image
        self.assertEqual(px(2, 1), 255)          # the south-west is open floor
        self.assertEqual(px(15, 5), 0)           # the column
        self.assertEqual(px(15, 6.2), 255)       # clear of it beyond size/2 + 0.3 m
        self.assertEqual(px(10, 0.1), 0)         # kept off the outer wall

    def test_pack_places_every_piece_without_overlap(self):
        imgs = [np.full((40, w, 3), i, np.uint8) for i, w in enumerate([5000, 4000, 3000, 8192, 100], start=1)]
        atlas, places = shell.pack(imgs)
        self.assertEqual(atlas.shape[1], shell.ATLAS_W)
        for img, (x, y) in zip(imgs, places):
            self.assertTrue(x + img.shape[1] <= shell.ATLAS_W)
            np.testing.assert_array_equal(atlas[y:y + 40, x:x + img.shape[1]], img)


if __name__ == "__main__":
    unittest.main()
