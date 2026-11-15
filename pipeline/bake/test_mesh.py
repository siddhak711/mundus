"""Tests for the floor mesh bake's classification and uv packing. Synthetic data only.

    python -m unittest pipeline.bake.test_mesh        # needs numpy, scipy and pillow
"""
import unittest

try:
    import numpy as np
    from pipeline.bake import mesh as M
except ImportError:
    M = None

# a 20 x 10 m plate on a GRID px/m frame, with a 4 x 2 m core in the middle
W, H = 20, 10


def frame_and_masks():
    f = M.Frame(0.0, 0.0, W, H)
    plate = np.ones((f.h, f.w), bool)
    core = np.zeros_like(plate)
    r0, c0 = f.px(np.array([8.0]), np.array([6.0]))
    r1, c1 = f.px(np.array([12.0]), np.array([4.0]))
    core[r0[0]:r1[0], c0[0]:c1[0]] = True
    return f, plate, core


@unittest.skipIf(M is None, "numpy, scipy and pillow are needed for the mesh bake")
class Classify(unittest.TestCase):
    def setUp(self):
        self.frame, self.plate, self.core = frame_and_masks()

    def cls(self, x, y, z, n):
        return M.classify(np.array([[x, y, z]], float), np.array([n], float), 0.0, 2.6, self.plate, self.core, self.frame)[0]

    def test_partition_deep_inside_sinks(self):
        self.assertEqual(self.cls(4.0, 5.0, 1.2, [1, 0, 0]), M.INTERIOR)

    def test_floor_and_ceiling_stay(self):
        self.assertEqual(self.cls(4.0, 5.0, 0.05, [0, 0, 1]), M.SHELL)
        self.assertEqual(self.cls(4.0, 5.0, 2.55, [0, 0, -1]), M.SHELL)

    def test_outer_wall_stays(self):
        self.assertEqual(self.cls(0.2, 5.0, 1.2, [1, 0, 0]), M.SHELL)    # within 0.4 m of the outside

    def test_core_wall_stays(self):
        self.assertEqual(self.cls(7.8, 5.0, 1.2, [1, 0, 0]), M.SHELL)    # beside the core

    def test_desk_top_sinks(self):
        self.assertEqual(self.cls(4.0, 5.0, 0.75, [0, 0, 1]), M.INTERIOR)   # facing up but well above the floor


@unittest.skipIf(M is None, "numpy, scipy and pillow are needed for the mesh bake")
class AtlasUV(unittest.TestCase):
    def test_tile_corners_stay_inside_the_tile(self):
        slot = (0, 3, 2, M.ATLAS)          # atlas 0, column 3, row 2, full-height atlas
        uv = M.atlas_uv(np.array([[0.0, 0.0], [1.0, 1.0]]), slot)
        u0, u1 = 3 * M.TILE / M.ATLAS, 4 * M.TILE / M.ATLAS
        self.assertTrue(u0 < uv[0, 0] < uv[1, 0] < u1)
        top, bottom = 1 - 2 * M.TILE / M.ATLAS, 1 - 3 * M.TILE / M.ATLAS    # row 2 counted from the top, v up
        self.assertTrue(bottom < uv[0, 1] < uv[1, 1] < top)


if __name__ == "__main__":
    unittest.main()
