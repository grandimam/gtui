"""Stable identifier helpers.

Identifiers are content-derived so repeated captures of the same state produce the same ids,
which keeps evidence references stable across runs.
"""

from __future__ import annotations

import hashlib


def short_hash(*parts: object, length: int = 10) -> str:
    h = hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return h[:length]


def page_id(url: str, viewport: tuple[int, int]) -> str:
    return f"page-{short_hash(url, viewport[0], viewport[1])}"


def observation_id(page: str, element_key: str, state: str = "default") -> str:
    return f"obs-{short_hash(page, element_key, state)}"
