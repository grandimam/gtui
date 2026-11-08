"""W3C Design Tokens (DTCG) JSON export — for Style Dictionary, Tokens Studio, Figma variables."""

from __future__ import annotations

import json

from gtui.ir.schema import AestheticProfile, is_unknown


def render_dtcg(profile: AestheticProfile) -> str:
    t = profile.tokens
    doc: dict = {
        "$schema": "https://tr.designtokens.org/format/",
        "color": {},
        "font": {},
        "fontSize": {},
        "lineHeight": {},
        "letterSpacing": {},
        "spacing": {},
        "radius": {},
        "shadow": {},
        "duration": {},
        "$extensions": {
            "gtui": {
                "profile": profile.metadata.name,
                "source": profile.metadata.source,
                "schema_version": profile.schema_version,
            }
        },
    }
    for role, tok in t.colors.items():
        node = doc["color"]
        parts = role.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = {
            "$type": "color",
            "$value": tok.value,
            "$description": tok.note or "",
            "$extensions": {
                "gtui": {
                    "confidence": tok.confidence,
                    "usage_count": tok.usage_count,
                    "source_names": tok.source_names,
                    "scope": tok.scope,
                }
            },
        }
    for name, fam in t.typography.families.items():
        if not is_unknown(fam):
            doc["font"][name] = {"$type": "fontFamily", "$value": fam.stack}  # type: ignore[union-attr]
    for key, step in t.typography.scale.items():
        doc["fontSize"][key] = {"$type": "dimension", "$value": f"{step.size:g}px"}
        if not is_unknown(step.line_height):
            doc["lineHeight"][key] = {"$type": "number", "$value": step.line_height}
        if not is_unknown(step.letter_spacing):
            doc["letterSpacing"][key] = {"$type": "dimension", "$value": f"{step.letter_spacing:g}em"}
    for v in t.spacing.scale:
        doc["spacing"][str(v)] = {"$type": "dimension", "$value": f"{v}px"}
    for key, tok in t.radius.items():
        doc["radius"][key] = {"$type": "dimension", "$value": "9999px" if key == "full" else f"{tok.value:g}px"}
    for key, tok in t.shadows.items():
        doc["shadow"][key] = {"$type": "shadow", "$value": tok.value, "$description": "raw CSS box-shadow"}
    if not is_unknown(t.motion.durations):
        for k, ms in t.motion.durations.items():  # type: ignore[union-attr]
            doc["duration"][k] = {"$type": "duration", "$value": f"{ms}ms"}
    return json.dumps({k: v for k, v in doc.items() if v or k.startswith("$")}, indent=2)
