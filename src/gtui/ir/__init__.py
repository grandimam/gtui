from pathlib import Path

from gtui.ir.schema import (
    SCHEMA_VERSION,
    AestheticProfile,
    Character,
    ColorToken,
    ComponentRecipe,
    Principle,
    Tokens,
    Unknown,
    is_unknown,
    unknown,
)


def load_profile(path: Path) -> AestheticProfile:
    return AestheticProfile.model_validate_json(Path(path).read_text(encoding="utf-8"))


def save_profile(profile: AestheticProfile, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    return path


__all__ = [
    "SCHEMA_VERSION",
    "AestheticProfile",
    "Character",
    "ColorToken",
    "ComponentRecipe",
    "Principle",
    "Tokens",
    "Unknown",
    "is_unknown",
    "unknown",
    "load_profile",
    "save_profile",
]
