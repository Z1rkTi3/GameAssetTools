"""Строгое чтение versioned metadata без Blender; это не проверка .blend структуры."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from game_asset_tools.assembly.contracts import ContractError, part_from_dict
from game_asset_tools.assembly.library import LibraryError, read_part, _manifest, _publish_directory
from test_assembly_contracts import fixture


class AssemblyLibraryMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gat_library_metadata_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.part = part_from_dict(fixture("foot")[0])
        self.directory = self.root / self.part.id / "1"
        self.directory.mkdir(parents=True)
        # Intentional stub: read_part обещает только manifest/hash, без Blender pass.
        payload = b"metadata-only-test-payload"
        (self.directory / "payload.blend").write_bytes(payload)
        self.document = _manifest(self.part, hashlib.sha256(payload).hexdigest())
        self.write(self.document)

    def write(self, value):
        (self.directory / "manifest.json").write_text(json.dumps(value), encoding="utf-8")

    def read(self):
        return read_part(self.root, self.part.id, 1)

    def test_roundtrip_is_explicit_about_manifest_only_and_does_not_mutate_files(self):
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        entry = self.read()
        self.assertEqual(entry.part, self.part)
        self.assertEqual(entry.directory, self.directory)
        self.assertEqual(entry.payload_sha256, self.document["payload"]["sha256"])
        self.assertEqual({p.name: p.read_bytes() for p in self.directory.iterdir()}, before)

    def test_invalid_paths_and_windows_reserved_names(self):
        for identity in ("../outside", "/outside", "x/y", "x\\y", "CON", "nul", "COM1", "a" * 101):
            with self.subTest(identity=identity), self.assertRaises(LibraryError):
                read_part(self.root, identity, 1)
        for revision in (True, 0, -1, 1.0, "../2"):
            with self.subTest(revision=revision), self.assertRaises(LibraryError):
                read_part(self.root, self.part.id, revision)

    def test_schema_identity_and_explicit_roles_are_strict(self):
        for change in (lambda d: d.update(schema_version=True), lambda d: d.update(schema_version=2),
                       lambda d: d.update(extra=True), lambda d: d["part"].update(id="different"),
                       lambda d: d["part"].update(revision=2), lambda d: d["payload"].update(file="../other.blend"),
                       lambda d: d["payload"].update(sha256="invalid"), lambda d: d["objects"].append(d["objects"][0]),
                       lambda d: d["objects"][0].update(role="socket"), lambda d: d["part"].update(coordinates={})):
            with self.subTest(change=change):
                document = deepcopy(self.document)
                change(document)
                self.write(document)
                with self.assertRaises((LibraryError, ContractError)):
                    self.read()

    def test_duplicate_json_keys_nonfinite_and_malformed_unicode_are_rejected(self):
        path = self.directory / "manifest.json"
        for content in (b'{"schema_version":1,"schema_version":1}', b'{"value":NaN}', b'\xff', b'{'):
            with self.subTest(content=content):
                path.write_bytes(content)
                with self.assertRaises(LibraryError):
                    self.read()

    def test_missing_extra_files_and_payload_hash_failure(self):
        extra = self.directory / "unexpected.txt"
        extra.write_text("unlisted", encoding="utf-8")
        with self.assertRaises(LibraryError) as error:
            self.read()
        self.assertEqual(error.exception.issues[0].code, "library_files")
        extra.unlink()
        (self.directory / "payload.blend").write_bytes(b"changed")
        with self.assertRaises(LibraryError) as error:
            self.read()
        self.assertEqual(error.exception.issues[0].code, "library_hash")
        (self.directory / "payload.blend").unlink()
        with self.assertRaises(LibraryError):
            self.read()

    def test_symlinked_library_is_rejected(self):
        alias = self.root / "alias"
        try:
            alias.symlink_to(self.directory.parent, target_is_directory=True)
        except OSError as error:
            if os.name != "nt":
                self.skipTest(f"Создание symlink недоступно: {error}")
            # Windows без SeCreateSymbolicLinkPrivilege разрешает directory junction.
            import _winapi
            _winapi.CreateJunction(str(self.directory.parent), str(alias))
            self.addCleanup(alias.rmdir)
        with self.assertRaises(LibraryError) as error:
            read_part(self.root, "alias", 1)
        self.assertEqual(error.exception.issues[0].code, "library_path")

    def test_atomic_publish_never_replaces_even_empty_existing_revision(self):
        stage = self.root / "staging"
        stage.mkdir()
        (stage / "proof.txt").write_text("candidate", encoding="utf-8")
        target = self.root / "existing_empty"
        target.mkdir()
        with self.assertRaises(LibraryError) as error:
            _publish_directory(stage, target)
        self.assertEqual(error.exception.issues[0].code, "revision_exists")
        self.assertEqual(list(target.iterdir()), [])
        self.assertTrue((stage / "proof.txt").is_file())


if __name__ == "__main__":
    unittest.main()
