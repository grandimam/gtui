"""Derive character, composition and evidence-backed design principles from tokens, recipes and
raw observations. Every principle carries the metric it was derived from."""

from __future__ import annotations

from collections import Counter

from gtui.core.color import contrast_ratio, distance, is_neutral, lightness, parse_color
from gtui.inference.common import confidence, evidence_sample, mode
from gtui.ir.schema import (
    AestheticProfile,
    Character,
    Composition,
    Principle,
    is_unknown,
    unknown,
)
from gtui.observations.models import ObservationSet


def infer_character(obs: ObservationSet, profile: AestheticProfile, dominant_radius: float | None) -> Character:
    t = profile.tokens
    ch = Character()
    base = profile.color("surface.base")
    if base:
        ch.color_scheme = "dark" if lightness(parse_color(base.value)) < 0.5 else "light"  # type: ignore[arg-type]

    # Density: body size, control heights, spacing base.
    body = t.typography.scale.get("base")
    buttons = [c for c in profile.components if c.kind == "button" and c.variant != "icon"]
    btn_h = mode([c.properties.get("height") for c in buttons]) if buttons else None
    spacing_base = t.spacing.base if not is_unknown(t.spacing.base) else None
    if body or btn_h:
        score = 0
        if body:
            score += -1 if body.size <= 14 else (1 if body.size >= 16.5 else 0)
        if btn_h:
            score += -1 if btn_h <= 34 else (1 if btn_h >= 44 else 0)
        if spacing_base == 8:
            score += 1
        ch.density = "compact" if score <= -1 else ("spacious" if score >= 2 else "comfortable")

    # Contrast between surfaces (restrained = subtle tonal steps).
    raised = profile.color("surface.raised")
    if base and raised:
        dl = abs(lightness(parse_color(raised.value)) - lightness(parse_color(base.value)))  # type: ignore[arg-type]
        ch.contrast = "restrained" if dl < 0.06 else ("moderate" if dl < 0.15 else "bold")
    elif base:
        ch.contrast = "restrained"

    # Depth from how cards are elevated.
    cards = profile.recipes("card")
    if cards:
        mix = cards[0].properties.get("elevation_mix", {})
        total = sum(mix.values()) or 1
        shadow_share = (mix.get("shadow", 0) + mix.get("border+shadow", 0)) / total
        big_shadows = any(s.blur >= 16 for s in t.shadows.values())
        if shadow_share >= 0.5 and big_shadows:
            ch.depth = "layered"
        elif shadow_share > 0.15 or t.shadows:
            ch.depth = "subtle"
        else:
            ch.depth = "flat"
    elif t.shadows:
        ch.depth = "subtle"
    elif profile.coverage.elements:
        ch.depth = "flat"

    # Ornamentation: gradients, shadows, background images, saturated surfaces.
    defaults = obs.defaults()
    if defaults:
        n = len(defaults)
        grads = sum(1 for e in defaults if e.style.has_gradient)
        shadows = sum(1 for e in defaults if e.style.has_shadow)
        sat_bg = sum(
            1
            for e in defaults
            if e.style.background_color
            and len(e.style.background_color) == 7
            and not is_neutral(parse_color(e.style.background_color))
        )  # type: ignore[arg-type]
        score = grads / n * 40 + shadows / n * 10 + sat_bg / n * 10
        ch.ornamentation = "minimal" if score < 0.6 else ("moderate" if score < 1.8 else "rich")

    if dominant_radius is not None:
        r = dominant_radius
        ch.geometry = "sharp" if r <= 2 else ("precise" if r <= 8 else ("soft" if r <= 16 else "round"))
    elif t.radius and set(t.radius) <= {"none", "full"}:
        ch.geometry = "sharp"

    parts = []
    for k in ("color_scheme", "density", "contrast", "depth", "ornamentation", "geometry"):
        v = getattr(ch, k)
        if not is_unknown(v):
            parts.append(f"{k.replace('_', ' ')}: {v}")
    ch.summary = "; ".join(parts)
    return ch


def infer_composition(obs: ObservationSet, profile: AestheticProfile) -> Composition:
    comp = Composition()
    defaults = obs.defaults()
    widths = Counter()
    ev = []
    for e in defaults:
        mw = e.style.max_width
        if mw and 560 <= mw <= 1920 and e.bounds.width >= 400 and e.depth <= 8:
            widths[int(round(mw))] += 1
            if len(ev) < 10:
                ev.append(e)
    if widths:
        comp.max_content_width = widths.most_common(1)[0][0]
        comp.evidence = evidence_sample(ev)
    containers = [e for e in defaults if e.child_count >= 2]
    if containers:
        c = Counter()
        for e in containers:
            d = e.style.display
            key = "flex" if "flex" in d else ("grid" if "grid" in d else "block")
            c[key] += 1
        n = len(containers)
        comp.layout_primitives = {k: round(v / n, 3) for k, v in c.most_common()}

    # Hierarchy: how are headings distinguished from body?
    t = profile.tokens.typography
    body = t.scale.get("base")
    h1 = next((c for c in profile.components if c.kind == "heading" and c.variant == "h1"), None)
    primary_text = profile.color("text.primary")
    if body and h1:
        ratio = (h1.properties.get("size_px") or body.size) / body.size
        heading_colored = primary_text is not None and h1.properties.get("text") not in (None, "text.primary")
        if heading_colored:
            comp.hierarchy = "color_first"
        elif ratio >= 3.0:
            comp.hierarchy = "size_first"
        elif (h1.properties.get("weight") or 400) >= 600 or ratio <= 2.2:
            comp.hierarchy = "typography_first"
        else:
            comp.hierarchy = "mixed"
        comp.confidence = confidence(h1.sample_count + body.usage_count, 0.6)
    else:
        comp.hierarchy = unknown("no h1 or body text observed")
    return comp


def infer_principles(obs: ObservationSet, profile: AestheticProfile) -> list[Principle]:
    out: list[Principle] = []
    t = profile.tokens
    defaults = obs.defaults()
    n = len(defaults) or 1

    def add(pid: str, statement: str, kind: str, metrics: dict, elements, conf: float, rationale: str = ""):
        out.append(
            Principle(
                id=pid,
                kind=kind,
                statement=statement,
                rationale=rationale,
                metrics=metrics,
                confidence=round(conf, 2),
                usage_count=len(elements) if elements else 0,
                evidence=evidence_sample(elements, 8) if elements else [],
            )
        )

    # 1. Accent restraint.
    accent = profile.color("accent.primary")
    if accent:
        ac = parse_color(accent.value)
        total_area = (
            sum(
                min(e.bounds.area, 1440 * 900 * 2)
                for e in defaults
                if e.style.background_color and len(e.style.background_color) == 7
            )
            or 1
        )
        accent_elems = [
            e
            for e in defaults
            if e.style.background_color
            and len(e.style.background_color) == 7
            and distance(parse_color(e.style.background_color), ac) <= 0.08
        ]  # type: ignore[arg-type]
        accent_area = sum(min(e.bounds.area, 1440 * 900 * 2) for e in accent_elems)
        share = accent_area / total_area
        roles = Counter(e.role or e.tag for e in accent_elems)
        if share < 0.03:
            add(
                "accent-restraint",
                "Use the accent color sparingly — reserve it for primary actions and selection, never for decoration.",
                "invariant",
                {
                    "accent_surface_share": round(share, 4),
                    "accent_elements": len(accent_elems),
                    "accent_roles": dict(roles.most_common(4)),
                },
                accent_elems,
                confidence(len(accent_elems) + 5, 0.9),
                f"Accent surfaces cover {share:.1%} of painted area, mostly on {', '.join(r for r, _ in roles.most_common(2)) or 'controls'}.",
            )
        elif share > 0.15:
            add(
                "accent-prominent",
                "The accent color is a structural surface, not just a highlight.",
                "invariant",
                {"accent_surface_share": round(share, 4)},
                accent_elems,
                confidence(len(accent_elems), 0.8),
            )

    # 2. Elevation strategy.
    cards = profile.recipes("card")
    if cards:
        mix = cards[0].properties.get("elevation_mix", {})
        total = sum(mix.values()) or 1
        border_share = (mix.get("border", 0) + mix.get("border+shadow", 0)) / total
        shadow_only = mix.get("shadow", 0) / total
        card_elems = [e for e in defaults if e.id in set(cards[0].evidence)]
        if border_share >= 0.6:
            add(
                "borders-over-shadows",
                "Separate surfaces with 1px borders and small tonal steps rather than drop shadows.",
                "invariant",
                {"border_share": round(border_share, 3), "elevation_mix": mix},
                card_elems,
                confidence(total, border_share, n0=8),
            )
        elif shadow_only >= 0.6:
            add(
                "shadows-for-elevation",
                "Elevation is expressed with shadows; borders are secondary.",
                "invariant",
                {"shadow_share": round(shadow_only, 3), "elevation_mix": mix},
                card_elems,
                confidence(total, shadow_only, n0=8),
            )

    # 3. Spacing grid.
    if not is_unknown(t.spacing.base) and t.spacing.grid_adherence:
        add(
            "spacing-grid",
            f"All spacing sits on a {t.spacing.base}px grid; use only {', '.join(map(str, t.spacing.scale[:8]))}…",
            "invariant",
            {"base": t.spacing.base, "grid_adherence": t.spacing.grid_adherence, "scale": t.spacing.scale},
            [e for e in defaults if e.id in set(t.spacing.evidence)],
            t.spacing.confidence,
        )

    # 4. Radius consistency.
    nonzero = {k: v for k, v in t.radius.items() if k not in ("none", "full")}
    if nonzero:
        total_r = sum(v.usage_count for v in nonzero.values()) or 1
        top_key, top = max(nonzero.items(), key=lambda kv: kv[1].usage_count)
        share = top.usage_count / total_r
        if share >= 0.5:
            add(
                "radius-consistency",
                f"Corners are consistently {top.value:g}px ({top_key}); larger radii are the exception.",
                "invariant",
                {
                    "dominant_radius": top.value,
                    "share": round(share, 3),
                    "scale": {k: v.value for k, v in t.radius.items()},
                },
                [e for e in defaults if e.id in set(top.evidence)],
                confidence(total_r, share, n0=15),
            )

    # 5. Typography scale & hierarchy.
    body = t.typography.scale.get("base")
    if body:
        h1 = next((c for c in profile.components if c.kind == "heading" and c.variant == "h1"), None)
        if h1 and h1.properties.get("size_px"):
            ratio = h1.properties["size_px"] / body.size
            hw = h1.properties.get("weight") or 400
            if ratio <= 2.4 and hw >= 600:
                add(
                    "hierarchy-by-weight",
                    f"Hierarchy comes from weight ({hw}) and spacing, not large size jumps (h1 is only {ratio:.1f}× body).",
                    "invariant",
                    {"h1_to_body_ratio": round(ratio, 2), "h1_weight": hw, "body_px": body.size},
                    [e for e in defaults if e.id in set(h1.evidence)],
                    confidence(h1.sample_count, 0.8, n0=4),
                )
            elif ratio >= 3.2:
                add(
                    "hierarchy-by-scale",
                    f"Headings are dramatically larger than body ({ratio:.1f}×); scale carries the hierarchy.",
                    "invariant",
                    {"h1_to_body_ratio": round(ratio, 2), "body_px": body.size},
                    [e for e in defaults if e.id in set(h1.evidence)],
                    confidence(h1.sample_count, 0.8, n0=4),
                )
        if body.size <= 14:
            add(
                "compact-type",
                f"Body text is small ({body.size:g}px); the UI reads as dense and tool-like.",
                "invariant",
                {"body_px": body.size, "line_height": body.line_height if not is_unknown(body.line_height) else None},
                [e for e in defaults if e.id in set(body.evidence)],
                body.confidence,
            )
        tracking = t.typography.heading_tracking
        if not is_unknown(tracking) and tracking <= -0.01:
            add(
                "tight-heading-tracking",
                f"Headings use tight letter-spacing ({tracking:+.3f}em).",
                "invariant",
                {"heading_tracking_em": tracking},
                [],
                0.7,
            )

    # 6. Text contrast tiers.
    tp, ts = profile.color("text.primary"), profile.color("text.secondary")
    base = profile.color("surface.base")
    if tp and ts and base:
        b = parse_color(base.value)
        cp, cs = contrast_ratio(parse_color(tp.value), b), contrast_ratio(parse_color(ts.value), b)  # type: ignore[arg-type]
        add(
            "two-tier-text",
            f"Text uses distinct contrast tiers: primary {cp:.1f}:1, secondary {cs:.1f}:1 against the base surface.",
            "invariant",
            {"primary_contrast": round(cp, 2), "secondary_contrast": round(cs, 2)},
            [e for e in defaults if e.id in set(tp.evidence[:4] + ts.evidence[:4])],
            min(tp.confidence, ts.confidence),
        )

    # 7. Motion.
    m = t.motion
    if not is_unknown(m.durations):
        durs = m.durations
        mx = max(durs.values())
        if mx <= 220:
            add(
                "restrained-motion",
                f"Transitions are quick (≤{mx}ms) and limited to color/opacity changes.",
                "invariant",
                {"durations_ms": durs, "properties": m.properties},
                [e for e in defaults if e.id in set(m.evidence)],
                m.confidence,
            )
        elif mx >= 400:
            add(
                "expressive-motion",
                f"Motion is expressive; some transitions run {mx}ms.",
                "variant",
                {"durations_ms": durs},
                [e for e in defaults if e.id in set(m.evidence)],
                m.confidence,
            )

    # 8. Exceptions: saturated surfaces seen once (hero gradients etc.).
    singles = [e for e in defaults if e.style.has_gradient]
    if singles and len(singles) / n < 0.01:
        add(
            "gradients-are-exceptions",
            "Gradients appear only in isolated hero/marketing moments — do not generalize them to UI surfaces.",
            "exception",
            {"gradient_elements": len(singles), "share": round(len(singles) / n, 4)},
            singles,
            0.7,
        )

    # 9. Responsive variant.
    vps = obs.viewports()
    if len(vps) >= 2:
        by_vp: dict[str, list] = {}
        for e in defaults:
            by_vp.setdefault(str(e.provenance.viewport), []).append(e)
        sizes = {vp: mode([round(e.style.font_size) for e in els if e.text_length >= 40]) for vp, els in by_vp.items()}
        sizes = {k: v for k, v in sizes.items() if v}
        if len(set(sizes.values())) > 1:
            add(
                "responsive-type",
                f"Body size shifts across viewports: {sizes}.",
                "variant",
                {"body_by_viewport": sizes},
                [],
                0.6,
            )
        else:
            add(
                "stable-type",
                "Body type size is stable across viewports; layout, not type, adapts.",
                "variant",
                {"body_by_viewport": sizes},
                [],
                0.6,
            )
    return out
