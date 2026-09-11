"""Filesystem discovery; importing the registry never imports Blender."""

from dataclasses import dataclass, field
import hashlib
import importlib.util
from pathlib import Path
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

    @property
    def config_path(self) -> Path:
        return self.path / "config.json"

    def load(self) -> AssetRecipe:
        """Load the recipe lazily; cache it for this registry entry's lifetime."""
        if self._recipe is not None:
            return self._recipe
        filename = self.path / "asset.py"
        digest = hashlib.sha256(str(filename.resolve()).encode()).hexdigest()[:16]
        module_name = f"_gat_recipe_{self.id}_{digest}"
        spec = importlib.util.spec_from_file_location(module_name, filename)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load recipe {self.id!r} from {filename}.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
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
            self._recipe = recipe
            return recipe
        except Exception as exc:
            sys.modules.pop(module_name, None)
            raise ValueError(f"Cannot load recipe {self.id!r}: {exc}") from exc

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "display_name": self.display_name, "category": self.category,
                "recipe_version": self.recipe_version, "supported_stages": list(self.supported_stages),
                "path": str(self.path), "config": str(self.config_path)}


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
            entries[asset_id] = RecipeEntry(asset_id, metadata["display_name"], metadata["category"],
                                             metadata["recipe_version"], stages, metadata_path.parent)
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
