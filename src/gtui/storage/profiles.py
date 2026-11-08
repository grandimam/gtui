"""Local store: captures (raw, rebuildable) and profiles (distilled, shareable)."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from gtui.core.config import Paths
from gtui.ir import AestheticProfile, load_profile
from gtui.observations.models import ObservationSet


@dataclass
class ProfileStore:
    paths: Paths

    @classmethod
    def default(cls) -> ProfileStore:
        return cls(Paths.default().ensure())

    # -- captures ---------------------------------------------------------------------------------

    def capture_dir(self, name: str) -> Path:
        return self.paths.capture_dir(name)

    def save_capture(self, obs: ObservationSet) -> Path:
        d = self.capture_dir(obs.name)
        d.mkdir(parents=True, exist_ok=True)
        return obs.save(d / "observations.json")

    def load_capture(self, name: str) -> ObservationSet:
        p = self.capture_dir(name) / "observations.json"
        if not p.exists():
            raise FileNotFoundError(f"no capture named {name!r} (looked in {p.parent}). Run `gtui capture` first.")
        return ObservationSet.load(p)

    def has_capture(self, name: str) -> bool:
        return (self.capture_dir(name) / "observations.json").exists()

    # -- profiles ---------------------------------------------------------------------------------

    def profile_dir(self, name: str) -> Path:
        return self.paths.profile_dir(name)

    def has_profile(self, name: str) -> bool:
        return (self.profile_dir(name) / "aesthetic.json").exists()

    def load_profile(self, name: str) -> AestheticProfile:
        p = self.profile_dir(name) / "aesthetic.json"
        if not p.exists():
            raise FileNotFoundError(
                f"no profile named {name!r} (looked in {p.parent}). Run `gtui extract {name}` first."
            )
        return load_profile(p)

    def copy_evidence(self, name: str) -> None:
        """Copy screenshots into the profile as evidence (opt-in; keeps profiles small otherwise)."""
        src = self.capture_dir(name) / "screenshots"
        dst = self.profile_dir(name) / "evidence" / "screenshots"
        if src.exists():
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.glob("*.png"):
                shutil.copy2(f, dst / f.name)

    def list_profiles(self) -> list[dict]:
        out = []
        for d in sorted(self.paths.profiles.glob("*/")):
            m = d / "manifest.json"
            if m.exists():
                try:
                    out.append(json.loads(m.read_text()))
                except json.JSONDecodeError:
                    out.append({"name": d.name, "error": "bad manifest"})
            elif (d / "aesthetic.json").exists():
                out.append({"name": d.name})
        return out

    def list_captures(self) -> list[str]:
        return sorted(d.name for d in self.paths.captures.glob("*/") if (d / "observations.json").exists())
