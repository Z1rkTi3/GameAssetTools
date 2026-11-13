"""Filesystem discovery; importing the registry never imports Blender."""

from dataclasses import dataclass, field
import hashlib
import importlib.util
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys
from typing import Any

from .parameters import Parameter, read_json
from .recipe import AssetRecipe, STAGES, validate_stage

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass
class RecipeEntry:
    id: str
    display_name: str
    category: str
    recipe_version: int
    supported_stages: tuple[str, ...]
    path: Path
    _recipe: Any = field(default=None, repr=False, compare=False)
    project_root: Path | None = field(default=None, repr=False)
    source_files: tuple[str, ...] = ()
    _source_digest: str | None = field(default=None, repr=False, compare=False)
    _module_name: str | None = field(default=None, repr=False, compare=False)

    @property
    def config_path(self) -> Path:
        return self.path / "config.json"

    def _source_snapshot(self) -> list[tuple[str, bytes]]:
        """Проверяем пути при каждом чтении: symlink мог измениться после discovery."""
        if self.project_root is None:
            raise ValueError(f"Recipe {self.id!r} source_files requires a project root.")
        root = self.project_root.resolve()
        filename = self.path.absolute() / "asset.py"
        try:
            asset_name = filename.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(f"Recipe {self.id!r} asset.py is outside its project.") from exc
        names = (asset_name, *self.source_files)
        seen_names, seen_paths, sources = set(), set(), []
        for name in names:
            posix = PurePosixPath(name) if isinstance(name, str) else None
            windows = PureWindowsPath(name) if isinstance(name, str) else None
            if (not name or posix is None or "\\" in name or ":" in name
                    or "\x00" in name or posix.is_absolute() or windows.drive or windows.root
                    or any(part in (".", "..", "") for part in name.split("/"))
                    or posix.as_posix() != name):
                raise ValueError(f"Recipe {self.id!r} source_files requires canonical project-relative POSIX paths: {name!r}.")
            if name in seen_names:
                raise ValueError(f"Recipe {self.id!r} has duplicate source file {name!r}.")
            seen_names.add(name)
            try:
                source = (root / name).resolve(strict=True)
                source.relative_to(root)
            except (OSError, ValueError) as exc:
                raise ValueError(f"Recipe {self.id!r} source file is missing or outside its project: {name!r}.") from exc
            if not source.is_file():
                raise ValueError(f"Recipe {self.id!r} source file is not a file: {name!r}.")
            if source in seen_paths:
                raise ValueError(f"Recipe {self.id!r} has duplicate source file target {name!r}.")
            seen_paths.add(source)
            sources.append((name, source.read_bytes()))
        return sorted(sources)

    def source_digest(self) -> str:
        """Старые recipes сохраняют SHA asset.py; opt-in учитывает общие исходники."""
        if not self.source_files:
            return hashlib.sha256((self.path / "asset.py").read_bytes()).hexdigest()
        digest = hashlib.sha256(b"GAT-source-files-v1\0")
        for name, content in self._source_snapshot():
            encoded = name.encode("utf-8")
            # Длины отделяют имена и данные без неоднозначных разделителей.
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return digest.hexdigest()

    def load(self) -> AssetRecipe:
        """Cache legacy recipes; opted-in recipes reload when source bytes change."""
        source_digest = self.source_digest() if self.source_files else None
        if self._recipe is not None and (not self.source_files or self._source_digest == source_digest):
            return self._recipe
        filename = self.path / "asset.py"
        digest = hashlib.sha256(str(filename.resolve()).encode()).hexdigest()[:16]
        module_name = f"_gat_recipe_{self.id}_{digest}"
        if source_digest is not None:
            module_name += "_" + source_digest
        spec = importlib.util.spec_from_file_location(module_name, filename)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load recipe {self.id!r} from {filename}.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            if source_digest is None:
                spec.loader.exec_module(module)
            else:
                # importlib bytecode cache опирается на mtime/size и может выдать
                # старый код после быстрой правки того же размера. Читаем bytes.
                exec(compile(filename.read_bytes(), str(filename), "exec"), module.__dict__)
            if hasattr(module, "RECIPE"):
                recipe = module.RECIPE
            elif hasattr(module, "recipe"):
                recipe = module.recipe
            elif hasattr(module, "Recipe"):
                recipe = module.Recipe()
            elif hasattr(module, "create_recipe"):
                recipe = module.create_recipe()
            else:
                raise ValueError("asset.py must expose RECIPE, recipe, Recipe, or create_recipe().")
            if not isinstance(getattr(recipe, "parameters", None), tuple):
                raise ValueError("Recipe parameters must be a tuple of Parameter values.")
            if not all(isinstance(parameter, Parameter) for parameter in recipe.parameters):
                raise ValueError("Recipe parameters must contain only Parameter values.")
            for method in ("components", "build_component"):
                if not callable(getattr(recipe, method, None)):
                    raise ValueError(f"Recipe requires {method}().")
            if source_digest is not None and self.source_digest() != source_digest:
                raise ValueError("Recipe source files changed while importing; retry after saving them.")
            previous_module = self._module_name
            self._recipe, self._source_digest, self._module_name = recipe, source_digest, module_name
            if previous_module is not None and previous_module != module_name:
                sys.modules.pop(previous_module, None)
            return recipe
        except Exception as exc:
            sys.modules.pop(module_name, None)
            raise ValueError(f"Cannot load recipe {self.id!r}: {exc}") from exc

    def as_dict(self) -> dict[str, Any]:
        value = {"id": self.id, "display_name": self.display_name, "category": self.category,
                "recipe_version": self.recipe_version, "supported_stages": list(self.supported_stages),
                "path": str(self.path), "config": str(self.config_path)}
        if self.source_files:
            value["source_files"] = list(self.source_files)
        return value


class Registry:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self._entries: dict[str, RecipeEntry] | None = None

    def refresh(self) -> None:
        self._entries = None

    def _discover(self) -> dict[str, RecipeEntry]:
        entries: dict[str, RecipeEntry] = {}
        for metadata_path in sorted((self.project_root / "game_assets").rglob("metadata.json")):
            metadata = read_json(metadata_path)
            if type(metadata.get("schema_version")) is not int or metadata["schema_version"] != 1:
                raise ValueError(f"Unsupported metadata schema_version in {metadata_path}; expected 1.")
            asset_id = metadata.get("id")
            if not isinstance(asset_id, str) or not IDENTIFIER.fullmatch(asset_id):
                raise ValueError(f"Invalid asset id in {metadata_path}; use lower_case_names.")
            if asset_id in entries:
                raise ValueError(f"Duplicate asset id {asset_id!r}: {entries[asset_id].path} and {metadata_path.parent}.")
            for name in ("asset.py", "config.json"):
                if not (metadata_path.parent / name).is_file():
                    raise ValueError(f"Recipe {asset_id!r} is missing {name}.")
            stages = metadata.get("supported_stages", list(STAGES))
            if not isinstance(stages, list) or not stages or not all(isinstance(s, str) for s in stages):
                raise ValueError(f"Invalid supported_stages for {asset_id!r}.")
            stages = tuple(validate_stage(stage) for stage in stages)
            if len(stages) != len(set(stages)):
                raise ValueError(f"Duplicate supported_stages for {asset_id!r}.")
            for key in ("display_name", "category"):
                if not isinstance(metadata.get(key), str) or not metadata[key]:
                    raise ValueError(f"Recipe {asset_id!r} requires a nonempty {key}.")
            if type(metadata.get("recipe_version")) is not int or metadata["recipe_version"] < 1:
                raise ValueError(f"Recipe {asset_id!r} requires a positive integer recipe_version.")
            source_files = metadata.get("source_files", ())
            if "source_files" in metadata and (not isinstance(source_files, list) or not source_files
                    or any(not isinstance(name, str) for name in source_files)):
                raise ValueError(f"Recipe {asset_id!r} source_files requires a nonempty list of paths.")
            entry = RecipeEntry(asset_id, metadata["display_name"], metadata["category"],
                                metadata["recipe_version"], stages, metadata_path.parent,
                                project_root=self.project_root, source_files=tuple(source_files))
            if source_files:
                entry.source_digest()
            entries[asset_id] = entry
        return entries

    def list(self) -> list[RecipeEntry]:
        if self._entries is None:
            self._entries = self._discover()
        return [self._entries[key] for key in sorted(self._entries)]

    def get(self, asset_id: str) -> RecipeEntry:
        self.list()
        if self._entries is None or asset_id not in self._entries:
            raise ValueError(f"Asset recipe {asset_id!r} not found under {self.project_root / 'game_assets'}.")
        return self._entries[asset_id]
