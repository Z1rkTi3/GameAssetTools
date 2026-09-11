"""Predictable artifact paths with explicit overwrite behavior."""

import json
import os
from pathlib import Path
import re
import tempfile


def artifact_path(output, kind, asset_id, suffix):
    if kind not in ("blend", "glb", "reports", "previews"):
        raise ValueError(f"Unknown output kind {kind!r}")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", asset_id):
        raise ValueError("Invalid asset identifier for output path")
    return Path(output).expanduser().resolve() / kind / (asset_id + suffix)


def prepare_path(path, *, overwrite=False):
    path = Path(path).expanduser().resolve()
    if path.exists() and (not overwrite or not path.is_file()):
        raise FileExistsError(f"Output exists: {path}; explicitly request overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path, data, *, overwrite=False):
    path = prepare_path(path, overwrite=overwrite)
    # Exclusive creation also guards against a concurrent writer without --overwrite.
    with path.open("w" if overwrite else "x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return str(path)
