"""Turn an ObservationSet into an AestheticProfile."""

from __future__ import annotations

from datetime import UTC, datetime

from gtui import __version__
from gtui.inference.colors import ColorInference
from gtui.inference.common import Palette
from gtui.inference.components import infer_components
from gtui.inference.geometry import infer_borders, infer_motion, infer_radius, infer_shadows, infer_spacing
from gtui.inference.principles import infer_character, infer_composition, infer_principles
from gtui.inference.typography import infer_typography
from gtui.ir.schema import AestheticProfile, Brand, Coverage, Metadata, Tokens, is_unknown
from gtui.observations.models import ObservationSet

_EXPECTED_ROLES = [
    "surface.base",
    "surface.raised",
    "text.primary",
    "text.secondary",
    "accent.primary",
    "border.subtle",
    "border.focus",
    "status.danger",
]


def synthesize(obs: ObservationSet, *, license: str | None = None, attribution: str | None = None) -> AestheticProfile:
    unknowns: list[str] = []
    brand = Brand()

    # Tokens ---------------------------------------------------------------------------------
    colors = ColorInference(obs)
    color_tokens = colors.infer()
    unknowns += colors.notes
    for role in _EXPECTED_ROLES:
        if role not in color_tokens:
            unknowns.append(f"color {role}: not observed")
    typography, brand_notes, typo_unknowns = infer_typography(obs)
    brand.notes += brand_notes
    unknowns += typo_unknowns
    spacing = infer_spacing(obs)
    radius, dominant_radius = infer_radius(obs)
    shadows = infer_shadows(obs)
    palette = Palette({r: t.value for r, t in color_tokens.items()})
    borders = infer_borders(obs, palette)
    motion = infer_motion(obs)
    if is_unknown(motion.durations):
        unknowns.append("motion: " + motion.durations.reason)  # type: ignore[union-attr]
    if is_unknown(spacing.base):
        unknowns.append("spacing: " + spacing.base.reason)  # type: ignore[union-attr]
    if not shadows:
        unknowns.append("shadows: none observed (may be genuinely flat)")

    root_props: dict[str, str] = {}
    for p in obs.pages:
        for k, v in p.custom_properties.items():
            root_props.setdefault(k, v)
    if len(root_props) > 400:
        root_props = dict(list(root_props.items())[:400])

    tokens = Tokens(
        colors=color_tokens,
        typography=typography,
        spacing=spacing,
        radius=radius,
        shadows=shadows,
        borders=borders,
        motion=motion,
        palette_source_properties=root_props,
    )

    accent = color_tokens.get("accent.primary")
    if accent:
        brand.notes.append(
            f"Accent {accent.value} is the source's brand hue. It is kept as a style token so the profile "
            "stays recognizable; substitute your own hue at similar lightness/chroma if you need brand neutrality."
        )
    brand.excluded += [
        "logos and wordmarks",
        "imagery and illustrations",
        "copy and product names",
        "icon artwork (conventions are described, assets are not copied)",
    ]

    summary = obs.summary()
    profile = AestheticProfile(
        metadata=Metadata(
            name=obs.name,
            source=obs.source,
            captured_at=obs.captured_at,
            extracted_at=datetime.now(UTC),
            gtui_version=__version__,
            browser=f"{obs.meta.browser} {obs.meta.browser_version}".strip(),
            license=license,
            attribution=attribution,
        ),
        tokens=tokens,
        coverage=Coverage(
            pages=int(summary["pages"]),
            viewports=list(summary["viewports"]),  # type: ignore[arg-type]
            elements=int(summary["elements"]),
            state_observations=int(summary["state_observations"]),  # type: ignore[arg-type]
            states=list(summary["states"]),  # type: ignore[arg-type]
        ),
        brand=brand,
    )

    # Components, then character/composition/principles (which read components) --------------
    recipes, sampled = infer_components(obs, profile)
    profile.components = recipes
    profile.coverage.components_sampled = sampled
    for kind in ("button", "input", "card"):
        if not sampled.get(kind):
            unknowns.append(f"component {kind}: none observed")
    profile.character = infer_character(obs, profile, dominant_radius)
    profile.composition = infer_composition(obs, profile)
    profile.principles = infer_principles(obs, profile)

    # Section confidences -----------------------------------------------------------------------
    def avg(vals: list[float]) -> float:
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    profile.confidence = {
        "colors": avg([t.confidence for t in color_tokens.values()]),
        "typography": typography.confidence,
        "spacing": spacing.confidence,
        "radius": avg([t.confidence for t in radius.values()]),
        "shadows": avg([t.confidence for t in shadows.values()]),
        "motion": motion.confidence,
        "components": avg([c.confidence for c in recipes]),
        "principles": avg([p.confidence for p in profile.principles]),
    }
    profile.unknowns = unknowns
    desc = profile.character.summary
    profile.metadata.description = (
        f"Design language of {obs.source} — {desc}" if desc else f"Design language of {obs.source}"
    )
    return profile
