"""Проверяет RGBA в настоящем GLB, строгий отказ и передачу поля Blender UI."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import unittest
from unittest.mock import patch

import bpy

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT / "blender_addon")]
from game_asset_tools.asset.lifecycle import build
from game_asset_tools.asset.parameters import load_config
from game_asset_tools.asset.registry import Registry
from game_asset_tools.asset.scene import asset_objects, find_root
from game_asset_tools.export import export_asset
from game_asset_tools.operations import execute
from game_asset_tools.style import load_style

OUTPUT = PROJECT / "output/vertex_color_export/blender"
FIXTURE = OUTPUT / "project"
PALETTE = ((0.125, 0.25, 0.5, 0.0), (0.25, 0.5, 0.75, 0.65),
           (0.5, 0.25, 0.125, 0.75), (0.75, 0.125, 0.25, 1.0))
REPORTS = []


def glb_payload(path):
    """Читает контейнер без повторного импорта и преобразований цветового слоя."""
    data = Path(path).read_bytes()
    magic, version, length = struct.unpack_from("<4sII", data)
    assert magic == b"glTF" and version == 2 and length == len(data)
    content, binary = None, None
    offset = 12
    while offset < len(data):
        size, kind = struct.unpack_from("<I4s", data, offset)
        block = data[offset + 8:offset + 8 + size]
        if kind == b"JSON":
            content = json.loads(block)
        elif kind == b"BIN\0":
            binary = block
        offset += 8 + size
    assert content is not None and binary is not None
    return content, binary


def colors(content, binary, index):
    accessor = content["accessors"][index]
    # Проверяется четвёртый канал, а не только наличие ключа COLOR_0.
    assert accessor["type"] == "VEC4" and not accessor.get("sparse")
    view = content["bufferViews"][accessor["bufferView"]]
    assert view.get("buffer", 0) == 0
    code, size, scale = {5121: ("B", 1, 255), 5123: ("H", 2, 65535), 5126: ("f", 4, 1)}[accessor["componentType"]]
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride", size * 4)
    divisor = scale if accessor.get("normalized") else 1
    return [tuple(value / divisor for value in struct.unpack_from("<4" + code, binary, start + stride * row))
            for row in range(accessor["count"])]


def scene_state(objects):
    """Экспорт не должен менять выбор, кадр, активный слой или исходные RGBA."""
    return {
        "selected": [obj.name for obj in bpy.context.selected_objects],
        "active": bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
        "frame": (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe),
        "scale": bpy.context.scene.unit_settings.scale_length,
        "objects": {obj.name: {
            "visibility": (obj.hide_get(), obj.hide_viewport, obj.hide_select),
            "active_color": obj.data.color_attributes.active_color_index,
            "render_color": obj.data.color_attributes.render_color_index,
            "attributes": [(layer.name, layer.domain, layer.data_type,
                             [tuple(value.color) for value in layer.data])
                            for layer in obj.data.color_attributes],
        } for obj in objects},
    }


class VertexColorExportBlenderTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        target = FIXTURE / "game_assets/tests/rig_fixture"
        shutil.copytree(PROJECT / "tests/fixtures/animated_rig", target, dirs_exist_ok=True)
        shutil.copyfile(PROJECT / "game_style.json", FIXTURE / "game_style.json")
        self.entry = Registry(FIXTURE).get("rig_fixture")
        build(self.entry, load_config(self.entry), load_style(FIXTURE))
        self.meshes = [obj for obj in asset_objects(find_root(self.entry.id), helpers=False) if obj.type == "MESH"]
        self.assertEqual(len(self.meshes), 2)
        for index, obj in enumerate(self.meshes):
            white = obj.data.color_attributes.new(name="SourceWhite", type="FLOAT_COLOR", domain="CORNER")
            for value in white.data:
                value.color = (1, 1, 1, 1)
            named = obj.data.color_attributes.new(name="OutlineWeight", type="FLOAT_COLOR",
                                                   domain="POINT" if index else "CORNER")
            for row, value in enumerate(named.data):
                value.color = PALETTE[row % len(PALETTE)]
            obj.data.color_attributes.active_color_index = 0
            obj.data.color_attributes.render_color_index = 0
            self.assertEqual(obj.data.color_attributes.active_color.name, "SourceWhite")
            for slot in obj.material_slots:
                self.assertFalse(any(node.type in {"ATTRIBUTE", "VERTEX_COLOR"} for node in slot.material.node_tree.nodes))
        # Чужая геометрия без цветового слоя не должна попадать в preflight ассета.
        unmanaged = bpy.data.objects.new("UnmanagedMesh", bpy.data.meshes.new("UnmanagedData"))
        unmanaged.data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        bpy.context.scene.collection.objects.link(unmanaged)
        bpy.context.scene.frame_set(7, subframe=0.25)
        bpy.context.scene.unit_settings.scale_length = 0.5
        self.meshes[0].hide_set(True)

    def check_payload(self, result):
        content, binary = glb_payload(result["glb"])
        checked = []
        self.assertEqual(len(content["meshes"]), 2)
        for mesh in content["meshes"]:
            for primitive in mesh["primitives"]:
                attributes = primitive["attributes"]
                self.assertIn("COLOR_0", attributes)
                self.assertNotIn("COLOR_1", attributes)
                values = colors(content, binary, attributes["COLOR_0"])
                # Все исходные RGBA должны присутствовать; белый active layer
                # или MATERIAL fallback не проходят эту проверку alpha/RGB.
                for expected in PALETTE:
                    self.assertTrue(any(max(abs(a - b) for a, b in zip(value, expected)) < 0.005
                                        for value in values), (mesh.get("name"), expected, values[:8]))
                self.assertTrue(all(any(max(abs(a - b) for a, b in zip(value, expected)) < 0.005
                                            for expected in PALETTE) for value in values))
                checked.append({"mesh": mesh.get("name"), "vertices": len(values),
                                "rgba": sorted(set(tuple(round(v, 5) for v in row) for row in values))})
        REPORTS.append({"glb": result["glb"], "sha256": hashlib.sha256(Path(result["glb"]).read_bytes()).hexdigest(),
                        "animations": result["animations_requested"], "colors": checked})

    def test_named_rgba_survives_static_and_animated_export_without_active_or_material_use(self):
        before = scene_state(self.meshes)
        for animated in (False, True):
            result = execute({"project": str(FIXTURE), "action": "export", "asset": self.entry.id,
                              "output": str(OUTPUT / ("named_animated" if animated else "named_static")),
                              "overwrite": True, "animations": animated, "vertex_color_name": "OutlineWeight"})
            self.check_payload(result)
            self.assertEqual(result["vertex_color_name"], "OutlineWeight")
            self.assertEqual(before, scene_state(self.meshes))

    def test_missing_one_mesh_refuses_before_selection_or_delivery_change(self):
        output = OUTPUT / "atomic"
        good = export_asset(self.entry.id, output, entry=self.entry, overwrite=True,
                            vertex_color_name="OutlineWeight")
        path = Path(good["glb"])
        previous = path.read_bytes()
        missing = self.meshes[-1]
        missing.data.color_attributes.remove(missing.data.color_attributes["OutlineWeight"])
        before = scene_state(self.meshes)
        with self.assertRaisesRegex(ValueError, "'OutlineWeight'.*" + missing.name):
            export_asset(self.entry.id, output, entry=self.entry, overwrite=True,
                         vertex_color_name="OutlineWeight")
        self.assertEqual(previous, path.read_bytes())
        self.assertEqual(before, scene_state(self.meshes))
        self.assertFalse(list(path.parent.glob(".rig_fixture_*.glb")))

    def test_empty_name_keeps_the_default_export(self):
        before = scene_state(self.meshes)
        default = export_asset(self.entry.id, OUTPUT / "default", entry=self.entry, overwrite=True)
        empty = export_asset(self.entry.id, OUTPUT / "empty", entry=self.entry, overwrite=True, vertex_color_name="")
        self.assertEqual(default["vertex_color_name"], "")
        self.assertEqual(Path(default["glb"]).read_bytes(), Path(empty["glb"]).read_bytes())
        self.assertEqual(before, scene_state(self.meshes))

    def test_real_ui_field_defaults_empty_forwards_export_only_and_exports_rgba(self):
        import game_asset_tools_addon as addon
        from game_asset_tools_addon import operators
        addon.register()
        try:
            settings = bpy.context.scene.game_asset_tools
            self.assertEqual(settings.export_vertex_color_name, "")
            self.assertEqual(settings.bl_rna.properties["export_vertex_color_name"].default, "")
            settings.project = str(FIXTURE)
            settings.output = str(OUTPUT / "ui")
            settings.overwrite = True
            bpy.ops.game_asset_tools.refresh()
            operators.properties.select_asset(settings, self.entry.id, bpy.context)
            for name in ("", "OutlineWeight"):
                settings.export_vertex_color_name = name
                with patch("game_asset_tools.operations.execute", return_value={"status": "exported"}) as dispatch:
                    self.assertEqual(bpy.ops.game_asset_tools.action(action="export"), {"FINISHED"})
                self.assertEqual(dispatch.call_args.args[0]["vertex_color_name"], name)
            for action in ("save", "inspect", "validate", "preview"):
                self.assertNotIn("vertex_color_name", operators.operation_request(settings, action))
            settings.export_animations = True
            before = scene_state(self.meshes)
            self.assertEqual(bpy.ops.game_asset_tools.action(action="export"), {"FINISHED"})
            result = json.loads(bpy.data.texts[settings.report_text].as_string())
            self.check_payload(result)
            self.assertEqual(before, scene_state(self.meshes))
        finally:
            addon.unregister()


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(VertexColorExportBlenderTests))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"project_root": str(PROJECT), "utc": datetime.now(timezone.utc).isoformat(),
              "blender": bpy.app.version_string, "status": "pass" if result.wasSuccessful() else "fail",
              "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "exports": REPORTS}
    (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("GAT_VERTEX_COLOR_EXPORT_OK", result.testsRun, OUTPUT / "report.json")
