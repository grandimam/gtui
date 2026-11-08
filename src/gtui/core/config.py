"""Paths and runtime configuration.

Profiles are stored globally (``~/.gtui``) so a capture is done once per machine and
reused across projects. Override with ``GTUI_HOME``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def gtui_home() -> Path:
    return Path(os.environ.get("GTUI_HOME", Path.home() / ".gtui")).expanduser()


@dataclass(frozen=True)
class Paths:
    home: Path

    @classmethod
    def default(cls) -> Paths:
        return cls(home=gtui_home())

    @property
    def captures(self) -> Path:
        return self.home / "captures"

    @property
    def profiles(self) -> Path:
        return self.home / "profiles"

    def capture_dir(self, name: str) -> Path:
        return self.captures / name

    def profile_dir(self, name: str) -> Path:
        return self.profiles / name

    def ensure(self) -> Paths:
        self.captures.mkdir(parents=True, exist_ok=True)
        self.profiles.mkdir(parents=True, exist_ok=True)
        return self


def slugify(value: str) -> str:
    """Turn a URL or free text into a safe profile name."""
    from urllib.parse import urlparse

    if "://" in value:
        host = urlparse(value).netloc.lower()
        for prefix in ("www.", "app."):
            if host.startswith(prefix):
                host = host[len(prefix) :]
        value = host.split(":")[0]
        parts = value.split(".")
        if len(parts) >= 2:
            value = parts[-2]
    out = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.lower()).strip("-")
    return out or "profile"
