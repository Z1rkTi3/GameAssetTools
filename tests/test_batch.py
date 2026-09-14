"""Batch manifests, common camera math and portable comparison artifacts."""

import base64
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from game_asset_tools.batch import common_framing, read_batch_config, write_comparison, _preflight


class BatchContractTests(unittest.TestCase):
    def manifest(self, directory, variants, **updates):
        path = Path(directory) / "variants.json"
        path.write_text(json.dumps({"schema_version": 1, "variants": variants, **updates}), encoding="utf-8")
        return path

    def test_manifest_accepts_independent_geometry_and_material_variants(self):
        variants = [{"name": "wide", "config": {"parameters": {"body": {"width": 4}}}},
                    {"name": "red", "action": "recolor", "materials": {"Painted_Metal": {"base_color": [1, 0, 0, 1]}},
                     "components": ["Body"], "objects": ["example_Body_Block"]}]
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(read_batch_config(self.manifest(directory, variants)), variants)

    def test_manifest_rejects_paths_duplicates_unknown_keys_and_conflicting_actions(self):
        bad = [[{"name": "../escape"}], [{"name": "con"}], [{"name": "a"}, {"name": "a"}],
               [{"name": "a", "action": "save"}], [{"name": "a", "config": "elsewhere.json"}],
               [{"name": "a", "materials": {}}], [{"name": "a", "action": "recolor"}],
               [{"name": "a", "action": "recolor", "materials": {"Paint": {}}, "config": {"asset": "other"}}],
               [{"name": "a", "components": ["Body", "Body"]}], [{"name": "a", "overwrite": True}], []]
        with tempfile.TemporaryDirectory() as directory:
            for variants in bad:
                with self.subTest(variants=variants), self.assertRaises(ValueError):
                    read_batch_config(self.manifest(directory, variants))
            for version in (True, 2):
                with self.assertRaises(ValueError):
                    read_batch_config(self.manifest(directory, [{"name": "a"}], schema_version=version))

    def test_common_frame_encloses_shifted_and_resized_variants(self):
        boxes = [{"min": [-1, -1, 0], "max": [1, 1, 2]}, {"min": [-2, -3, 0], "max": [5, 3, 7]}]
        frame = common_framing(boxes, 1.2)
        self.assertEqual(frame, common_framing(boxes[::-1], 1.2))
        self.assertEqual(frame["center"], [1.5, 0, 3.5])
        self.assertAlmostEqual(frame["ortho_scale"], frame["radius"] * 2.4)
        for box in boxes:
            for x in (box["min"][0], box["max"][0]):
                for y in (box["min"][1], box["max"][1]):
                    for z in (box["min"][2], box["max"][2]):
                        self.assertLessEqual(sum((a-b)**2 for a, b in zip((x, y, z), frame["center"])), frame["radius"]**2 + 1e-9)
        self.assertIsNone(common_framing([]))

    def test_comparison_embeds_images_and_marks_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            image = directory / "front.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nexample")
            target = directory / "comparison.svg"
            variants = [{"name": "red", "status": "passed", "preview": {"paths": {"front": str(image)}}},
                        {"name": "bad", "status": "failed", "error": "Invalid <dimension> & geometry"}]
            write_comparison(target, variants, ["front"], 256)
            root = ET.parse(target).getroot()
            images = root.findall(".//{http://www.w3.org/2000/svg}image")
            self.assertEqual(len(images), 1)
            self.assertEqual(base64.b64decode(images[0].attrib["href"].split(",")[1]), image.read_bytes())
            self.assertIn("bad — failed", target.read_text(encoding="utf-8"))
            self.assertNotIn(str(directory), target.read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                write_comparison(target, variants, ["front"], 256)

    def test_preflight_protects_all_outputs_and_inputs_without_creating_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            absent = directory / "new" / "first.png"
            existing = directory / "last.png"
            existing.write_bytes(b"original")
            with self.assertRaises(FileExistsError):
                _preflight([absent, existing], overwrite=False, protected=set())
            self.assertFalse(absent.parent.exists())
            with self.assertRaises(ValueError):
                _preflight([existing], overwrite=True, protected={existing.resolve()})
            self.assertEqual(existing.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
