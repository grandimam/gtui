"""Profile exports. The IR is the source of truth; these are projections of it."""

from __future__ import annotations

import json
from pathlib import Path

from gtui.export.design_md import render_design_md
from gtui.export.dtcg import render_dtcg
from gtui.export.preview import render_preview
from gtui.export.theme import render_css, render_shadcn, render_tailwind
from gtui.ir.schema import AestheticProfile

FORMATS = {
    "css": ("theme.css", lambda p: render_css(p)),
    "tailwind": ("tailwind.css", lambda p: render_tailwind(p)),
    "shadcn": ("shadcn.css", lambda p: render_shadcn(p)),
    "dtcg": ("tokens.dtcg.json", lambda p: render_dtcg(p)),
    "preview": ("preview.html", lambda p: render_preview(p)),
    "design-md": ("design.md", lambda p: render_design_md(p)),
}


def render(profile: AestheticProfile, fmt: str) -> str:
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; choose from {', '.join(FORMATS)}")
    return FORMATS[fmt][1](profile)


def write_profile_bundle(profile: AestheticProfile, directory: Path) -> dict[str, Path]:
    """Write aesthetic.json, design.md, tokens.json, components.json and all exports."""
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    p = directory / "aesthetic.json"
    p.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    written["aesthetic.json"] = p
    p = directory / "design.md"
    p.write_text(render_design_md(profile), encoding="utf-8")
    written["design.md"] = p
    p = directory / "tokens.json"
    p.write_text(json.dumps(profile.tokens.model_dump(mode="json"), indent=2), encoding="utf-8")
    written["tokens.json"] = p
    p = directory / "components.json"
    p.write_text(json.dumps([c.model_dump(mode="json") for c in profile.components], indent=2), encoding="utf-8")
    written["components.json"] = p
    exports = directory / "exports"
    exports.mkdir(exist_ok=True)
    for fmt, (filename, fn) in FORMATS.items():
        if fmt == "design-md":
            continue
        p = exports / filename
        p.write_text(fn(profile), encoding="utf-8")
        written[f"exports/{filename}"] = p
    manifest = {
        "name": profile.metadata.name,
        "version": profile.metadata.version,
        "schema_version": profile.schema_version,
        "source": profile.metadata.source,
        "captured_at": profile.metadata.captured_at.isoformat(),
        "extracted_at": profile.metadata.extracted_at.isoformat(),
        "gtui_version": profile.metadata.gtui_version,
        "license": profile.metadata.license,
        "attribution": profile.metadata.attribution,
        "description": profile.metadata.description,
        "coverage": profile.coverage.model_dump(mode="json"),
        "confidence": profile.confidence,
        "files": sorted(written.keys()),
    }
    p = directory / "manifest.json"
    p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    written["manifest.json"] = p
    return written


__all__ = [
    "FORMATS",
    "render",
    "write_profile_bundle",
    "render_css",
    "render_tailwind",
    "render_shadcn",
    "render_dtcg",
    "render_preview",
    "render_design_md",
]
