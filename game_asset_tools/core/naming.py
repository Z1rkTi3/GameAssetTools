"""Deterministic semantic names independent of Blender-generated suffixes."""

import hashlib
import re
import unicodedata


def semantic_name(*parts: object) -> str:
    """Join meaningful parts with underscores, bounded to 63 UTF-8 bytes.

    Whitespace and punctuation become underscores. Long names retain a stable
    digest so distinct semantic identities do not collapse to the same prefix.
    Blender may append an occurrence suffix; identity belongs in asset metadata.
    """
    tokens = []
    for part in parts:
        if part is None:
            continue
        normalized = unicodedata.normalize("NFKC", str(part))
        token = re.sub(r"[^\w]+", "_", normalized, flags=re.UNICODE)
        token = re.sub(r"_+", "_", token).strip("_")
        if token:
            tokens.append(token)
    name = "_".join(tokens)
    if not name:
        raise ValueError("A semantic name needs at least one meaningful part")
    encoded = name.encode("utf-8")
    if len(encoded) > 63:
        digest = hashlib.sha256(encoded).hexdigest()[:10]
        prefix = encoded[:52].decode("utf-8", errors="ignore").rstrip("_")
        name = f"{prefix}_{digest}"
    return name
