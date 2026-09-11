"""Naming remains usable outside Blender and preserves semantic identities."""

import unittest

from game_asset_tools.core.naming import semantic_name


class NamingTests(unittest.TestCase):
    def test_meaningful_parts(self):
        self.assertEqual(semantic_name("Mech", "Leg - Left", "Upper"), "Mech_Leg_Left_Upper")
        self.assertEqual(semantic_name("Tower", None, 1), "Tower_1")

    def test_empty_rejected(self):
        for parts in [(), (None,), (" ! - ",)]:
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                semantic_name(*parts)

    def test_unicode_and_length(self):
        self.assertEqual(semantic_name("Բազուկ", "Left"), "Բազուկ_Left")
        self.assertEqual(semantic_name("ＡＢＣ"), "ABC")
        a = semantic_name("Մ" * 60, "Left")
        b = semantic_name("Մ" * 60, "Right")
        self.assertLessEqual(len(a.encode("utf-8")), 63)
        self.assertNotEqual(a, b)
        self.assertEqual(a, semantic_name("Մ" * 60, "Left"))


if __name__ == "__main__":
    unittest.main()
