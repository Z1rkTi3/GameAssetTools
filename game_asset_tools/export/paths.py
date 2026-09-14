"""Predictable artifact paths with explicit overwrite behavior."""

import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4


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


REPORT_MODES = ("file", "stdout", "unique", "replace")


def write_validation_report(asset_id, output, report, *, mode="file", overwrite=False):
    """Return a report, optionally writing only a validation JSON artifact.

    ``stdout`` leaves output handling to the caller. ``unique`` exclusively creates
    a UUID-suffixed report. ``replace`` replaces the canonical report without
    granting overwrite permission to any .blend, preview, or export operation.
    ``file`` preserves the original explicit-overwrite contract.
    """
    if mode not in REPORT_MODES:
        raise ValueError(f"Unknown validation report mode {mode!r}; choose {REPORT_MODES}")
    result = dict(report)
    if mode == "stdout":
        return result
    path = artifact_path(output, "reports", asset_id, "_validation.json")
    if mode == "unique":
        for _ in range(10):
            candidate = path.with_name(f"{asset_id}_validation_{uuid4().hex}.json")
            try:
                result["report"] = write_json(candidate, report)
                return result
            except FileExistsError:
                continue
        raise FileExistsError("Could not allocate an unused validation report filename")
    result["report"] = write_json(path, report, overwrite=mode == "replace" or overwrite)
    return result
