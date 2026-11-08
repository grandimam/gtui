"""Infer component recipes: how buttons, inputs, cards, links, nav items, headings and badges are
built, expressed in token roles, plus their observed interaction states."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from gtui.core.color import distance, lightness, parse_color
from gtui.inference.common import (
    Palette,
    confidence,
    effective_backgrounds,
    evidence_sample,
    median,
    mode,
    nearest_key,
    parent_background,
)
from gtui.ir.schema import AestheticProfile, ComponentRecipe, StateDelta
from gtui.observations.models import ElementObservation, ObservationSet

_HEADINGS = ("h1", "h2", "h3", "h4")
_NAV_REGIONS = {"nav", "header", "aside"}


@dataclass
class Context:
    obs: ObservationSet
    profile: AestheticProfile
    palette: Palette
    defaults: list[ElementObservation]
    by_id: dict[str, ElementObservation]
    eff_bg: dict[str, str | None]
    root_bg: dict[str, str | None]
    type_scale: dict[str, float]
    radius_scale: dict[str, float]
    states: dict[tuple[str, str, str], ElementObservation]  # (page, key, state) -> obs

    def parent_bg(self, e: ElementObservation) -> str | None:
        return parent_background(e, self.by_id, self.eff_bg, self.root_bg)

    def font_key(self, size: float) -> str | float:
        return nearest_key(size, self.type_scale, tolerance=0.75) or round(size, 1)

    def radius_key(self, e: ElementObservation) -> str | float:
        r = e.style.radius_max
        if r <= 0:
            return "none"
        min_side = min(e.bounds.width, e.bounds.height)
        if min_side > 0 and r >= min_side / 2 - 0.5:
            return "full"
        return nearest_key(r, {k: v for k, v in self.radius_scale.items() if k != "full"}, tolerance=1.5) or round(r, 1)

    def color_role(self, hex_value: str | None, kind: str = "bg") -> str | None:
        """Describe a color as a role, biased toward the family that fits how it is used."""
        prefer = {
            "bg": ("surface.", "accent.", "status."),
            "text": ("text.", "accent.", "status."),
            "border": ("border.", "surface."),
            "ring": ("border.focus", "accent.", "border."),
        }[kind]
        return self.palette.describe(hex_value, prefer=prefer)


def build_context(obs: ObservationSet, profile: AestheticProfile) -> Context:
    defaults = obs.defaults()
    by_id = {e.id: e for e in defaults}
    root_bg = {p.id: p.root_background for p in obs.pages}
    palette = Palette({role: t.value for role, t in profile.tokens.colors.items()})
    type_scale = {k: v.size for k, v in profile.tokens.typography.scale.items()}
    radius_scale = {k: v.value for k, v in profile.tokens.radius.items()}
    states = {(e.page_id, e.key, e.state): e for e in obs.elements if e.state != "default"}
    return Context(
        obs,
        profile,
        palette,
        defaults,
        by_id,
        effective_backgrounds(defaults, root_bg),
        root_bg,
        type_scale,
        radius_scale,
        states,
    )


# --- state deltas ---------------------------------------------------------------------------------


def _describe_bg_change(before: str | None, after: str | None, ctx: Context) -> str:
    b, a = parse_color(before) if before else None, parse_color(after) if after else None
    if a is None or a.transparent:
        return "background removed"
    if b is None or b.transparent:
        return f"background appears ({ctx.color_role(a.hex)})"
    dl = lightness(a) - lightness(b)
    direction = "lightens" if dl > 0 else "darkens"
    return f"background {direction} by {abs(dl):.2f} L ({ctx.color_role(a.hex)})"


def _state_deltas(ctx: Context, members: list[ElementObservation]) -> dict[str, StateDelta]:
    out: dict[str, StateDelta] = {}
    for state in ("hover", "focus-visible"):
        changes_count: Counter = Counter()
        values: dict[str, Counter] = defaultdict(Counter)
        samples: list[ElementObservation] = []
        descr: Counter = Counter()
        for m in members:
            s = ctx.states.get((m.page_id, m.key, state))
            if not s:
                continue
            samples.append(s)
            # `outline-style: auto` is the browser's default focus ring, not an authored style.
            ua_ring = s.state_diff.get("outline-style") == "auto"
            for prop, val in s.state_diff.items():
                if ua_ring and prop.startswith("outline"):
                    continue
                # border-color tracks currentColor on borderless elements; only meaningful with a border
                if prop == "border-top-color" and not m.style.has_border and not s.style.has_border:
                    continue
                changes_count[prop] += 1
                values[prop][val] += 1
                if prop == "background-color":
                    descr[_describe_bg_change(m.style.background_color, s.style.background_color, ctx)] += 1
                elif prop == "color":
                    descr[f"text becomes {ctx.color_role(s.style.color, 'text')}"] += 1
                elif prop == "border-top-color":
                    descr[f"border becomes {ctx.color_role(s.style.border_color, 'border')}"] += 1
                elif prop == "box-shadow":
                    descr["ring/shadow: " + (val[:60] if val != "none" else "none")] += 1
                elif prop == "outline-color" and s.state_diff.get("outline-style", "none") not in ("none", "auto"):
                    descr[f"outline {ctx.color_role(s.style.outline_color, 'ring')} {s.style.outline_width:g}px"] += 1
                elif prop == "text-decoration-line":
                    descr[f"text-decoration: {val}"] += 1
                elif prop == "opacity":
                    descr[f"opacity {val}"] += 1
                elif prop == "transform":
                    descr[f"transform {val[:40]}"] += 1
        if not samples:
            continue
        n = len(samples)
        changes = {}
        for prop, cnt in changes_count.items():
            if cnt >= max(1, 0.3 * n):
                v = values[prop].most_common(1)[0][0]
                pc = parse_color(v)
                kind = {"color": "text", "border-top-color": "border", "outline-color": "ring"}.get(prop, "bg")
                role = ctx.color_role(pc.hex, kind) if (pc and not pc.transparent) else None
                changes[prop] = role or v[:80]
        if not changes:
            continue
        out[state] = StateDelta(
            changes=changes,
            description="; ".join(d for d, _ in descr.most_common(3)),
            sample_count=n,
            evidence=evidence_sample(samples, 6),
        )
    return out


# --- recipes ----------------------------------------------------------------------------------------


def _recipe(
    ctx: Context,
    kind: str,
    variant: str,
    members: list[ElementObservation],
    props: dict[str, Any],
    description: str = "",
    n0: int = 6,
) -> ComponentRecipe:
    return ComponentRecipe(
        kind=kind,
        variant=variant,
        description=description,
        properties=props,
        states=_state_deltas(ctx, members),
        sample_count=len(members),
        usage_count=len(members),
        confidence=confidence(len(members), 1.0, n0=n0),
        evidence=evidence_sample(members),
    )


def _common_props(ctx: Context, members: list[ElementObservation]) -> dict[str, Any]:
    st = [m.style for m in members]
    props: dict[str, Any] = {
        "height": round(median([m.bounds.height for m in members])),
        "padding_x": round(median([s.padding_x for s in st])),
        "padding_y": round(median([s.padding_y for s in st])),
        "font": ctx.font_key(median([s.font_size for s in st])),
        "weight": mode([s.font_weight for s in st]),
        "radius": mode([ctx.radius_key(m) for m in members]),
    }
    bg = mode([s.background_color for s in st if s.background_color])
    props["background"] = (
        ctx.color_role(bg) if bg and sum(1 for s in st if s.background_color) >= len(st) / 2 else "transparent"
    )
    text = mode([s.color for s in st if s.color])
    props["text"] = ctx.color_role(text, "text") if text else None
    bordered = [s for s in st if s.has_border]
    if len(bordered) >= len(st) / 2:
        props["border"] = {
            "width": round(median([s.border_width for s in bordered]), 1),
            "color": ctx.color_role(mode([s.border_color for s in bordered]), "border"),
        }
    else:
        props["border"] = "none"
    shadows = [s.box_shadow for s in st if s.has_shadow]
    props["shadow"] = mode(shadows) if len(shadows) >= len(st) / 2 else "none"
    tt = mode([s.text_transform for s in st])
    if tt and tt != "none":
        props["text_transform"] = tt
    ls = median([s.letter_spacing / s.font_size for s in st if s.font_size])
    if abs(ls) >= 0.005:
        props["letter_spacing_em"] = round(ls, 3)
    return props


def _button_variant(ctx: Context, e: ElementObservation) -> str:
    st = e.style
    if e.text_length == 0 and abs(e.bounds.width - e.bounds.height) <= 6:
        return "icon"
    bg = parse_color(st.background_color) if st.background_color else None
    parent = parse_color(ctx.parent_bg(e) or "") if ctx.parent_bg(e) else None
    accent = ctx.profile.color("accent.primary")
    danger = ctx.profile.color("status.danger")
    if bg and bg.opaque:
        if accent and distance(bg, parse_color(accent.value)) <= 0.08:  # type: ignore[arg-type]
            return "primary"
        if danger and distance(bg, parse_color(danger.value)) <= 0.08:  # type: ignore[arg-type]
            return "destructive"
        if parent is None or distance(bg, parent) > 0.015:
            return "secondary"
    if st.has_border:
        return "outline"
    if bg and not bg.opaque and not bg.transparent:
        return "soft"
    return "ghost"


def _is_buttonish_link(e: ElementObservation) -> bool:
    st = e.style
    return (
        e.tag == "a"
        and e.text_length > 0
        and e.text_length <= 40
        and 22 <= e.bounds.height <= 64
        and st.padding_x >= 8
        and ((st.background_color and len(st.background_color) == 7) or st.has_border)
        and e.region not in _NAV_REGIONS
    )


def infer_components(obs: ObservationSet, profile: AestheticProfile) -> tuple[list[ComponentRecipe], dict[str, int]]:
    ctx = build_context(obs, profile)
    recipes: list[ComponentRecipe] = []
    sampled: dict[str, int] = {}

    # Buttons ------------------------------------------------------------------------------------
    buttons = [
        e
        for e in ctx.defaults
        if (e.role == "button" or _is_buttonish_link(e))
        and e.bounds.height >= 16
        and e.bounds.width >= 16
        and not e.disabled
    ]
    groups: dict[str, list[ElementObservation]] = defaultdict(list)
    for b in buttons:
        groups[_button_variant(ctx, b)].append(b)
    sampled["button"] = len(buttons)
    for variant, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(members) < 1:
            continue
        props = _common_props(ctx, members)
        desc = {
            "primary": "High-emphasis action on the accent surface.",
            "secondary": "Medium emphasis on a tonal neutral surface.",
            "outline": "Medium emphasis; border only, transparent surface.",
            "ghost": "Low emphasis; no surface or border at rest.",
            "soft": "Low emphasis; translucent tint surface.",
            "destructive": "Dangerous action on the danger color.",
            "icon": "Square icon-only control.",
        }.get(variant, "")
        recipes.append(_recipe(ctx, "button", variant, members, props, desc))

    # Inputs -------------------------------------------------------------------------------------
    # single-line fields only; textareas would skew height/padding medians
    inputs = [
        e
        for e in ctx.defaults
        if e.role in ("textbox", "combobox") and e.tag != "textarea" and 20 <= e.bounds.height <= 64
    ]
    sampled["input"] = len(inputs)
    if inputs:
        props = _common_props(ctx, inputs)
        props.pop("padding_y", None)
        recipes.append(_recipe(ctx, "input", "default", inputs, props, "Text fields and selects.", n0=4))

    # Cards --------------------------------------------------------------------------------------
    cards: list[ElementObservation] = []
    for e in ctx.defaults:
        st = e.style
        if e.role in (
            "button",
            "link",
            "textbox",
            "combobox",
            "img",
            "heading",
            "navigation",
            "banner",
            "contentinfo",
            "main",
            "complementary",
            "list",
            "row",
            "cell",
            "table",
        ):
            continue
        if e.tag not in ("div", "section", "article", "li", "a", "aside", "figure"):
            continue
        if not (e.bounds.width >= 160 and e.bounds.height >= 56 and e.child_count >= 1):
            continue
        parent_bg = ctx.parent_bg(e)
        bg = parse_color(st.background_color) if st.background_color and len(st.background_color) == 7 else None
        tonal = bool(bg and parent_bg and distance(bg, parse_color(parent_bg)) > 0.015)  # type: ignore[arg-type]
        if not (st.has_border or st.has_shadow or tonal):
            continue
        if st.radius_max < 2 and not st.has_shadow:
            continue
        page = next((p for p in obs.pages if p.id == e.page_id), None)
        if page and page.scroll_width and e.bounds.width >= 0.96 * page.scroll_width:
            continue  # full-bleed section, not a card
        cards.append(e)
    sampled["card"] = len(cards)
    if cards:
        st = [c.style for c in cards]
        elevation = Counter()
        for s in st:
            if s.has_border and s.has_shadow:
                elevation["border+shadow"] += 1
            elif s.has_border:
                elevation["border"] += 1
            elif s.has_shadow:
                elevation["shadow"] += 1
            else:
                elevation["tone"] += 1
        bg = mode([s.background_color for s in st if s.background_color and len(s.background_color) == 7])
        props: dict[str, Any] = {
            "padding": round(median([min(s.padding_x, s.padding_y) for s in st if s.padding_x or s.padding_y])),
            "radius": mode([ctx.radius_key(c) for c in cards]),
            "background": ctx.color_role(bg) if bg else "inherit",
            "elevation": elevation.most_common(1)[0][0],
            "elevation_mix": dict(elevation),
        }
        bordered = [s for s in st if s.has_border]
        if bordered:
            props["border"] = {
                "width": round(median([s.border_width for s in bordered]), 1),
                "color": ctx.color_role(mode([s.border_color for s in bordered]), "border"),
            }
        shadows = [s.box_shadow for s in st if s.has_shadow]
        if shadows:
            props["shadow"] = mode(shadows)
        recipes.append(
            _recipe(
                ctx, "card", "default", cards, props, "Contained content surfaces (cards, panels, list tiles).", n0=5
            )
        )

    # Nav items ----------------------------------------------------------------------------------
    nav = [
        e
        for e in ctx.defaults
        if e.role in ("link", "button", "tab", "menuitem")
        and e.region in _NAV_REGIONS
        and 0 < e.text_length <= 32
        and e.bounds.height >= 16
    ]
    sampled["nav_item"] = len(nav)
    if nav:
        rest = [e for e in nav if not e.current]
        cur = [e for e in nav if e.current]
        if rest:
            props = _common_props(ctx, rest)
            recipes.append(_recipe(ctx, "nav_item", "default", rest, props, "Navigation links/tabs at rest."))
        if cur:
            props = _common_props(ctx, cur)
            recipes.append(_recipe(ctx, "nav_item", "selected", cur, props, "Current/selected navigation item.", n0=3))

    # Inline links -------------------------------------------------------------------------------
    links = [
        e
        for e in ctx.defaults
        if e.role == "link"
        and e.region not in _NAV_REGIONS
        and e.region != "footer"
        and e.text_length > 0
        and not e.style.background_color
        and not e.style.has_border
        and not _is_buttonish_link(e)
    ]
    sampled["link"] = len(links)
    if links:
        st = [m.style for m in links]
        props = {
            "text": ctx.color_role(mode([s.color for s in st if s.color]), "text"),
            "weight": mode([s.font_weight for s in st]),
            "decoration": mode([s.text_decoration for s in st]),
        }
        recipes.append(_recipe(ctx, "link", "inline", links, props, "Links within text."))

    # Headings -----------------------------------------------------------------------------------
    for tag in _HEADINGS:
        hs = [e for e in ctx.defaults if e.tag == tag and e.text]
        if not hs:
            continue
        sampled[tag] = len(hs)
        st = [h.style for h in hs]
        size = median([s.font_size for s in st])
        props = {
            "font": ctx.font_key(size),
            "size_px": round(size, 1),
            "weight": mode([s.font_weight for s in st]),
            "line_height": round(median([s.line_height / s.font_size for s in st if s.line_height]), 2)
            if any(s.line_height for s in st)
            else None,
            "letter_spacing_em": round(median([s.letter_spacing / s.font_size for s in st if s.font_size]), 3),
            "text": ctx.color_role(mode([s.color for s in st if s.color]), "text"),
        }
        recipes.append(_recipe(ctx, "heading", tag, hs, props, n0=3))

    # Badges -------------------------------------------------------------------------------------
    badges = []
    for e in ctx.defaults:
        st = e.style
        if e.role in ("button", "link", "textbox", "combobox", "heading", "img", "listitem", "cell", "row"):
            continue
        if e.tag not in ("span", "div", "small", "mark", "code", "kbd"):
            continue
        if not (
            14 <= e.bounds.height <= 28 and e.bounds.width <= 180 and 1 <= e.text_length <= 24 and e.child_count <= 1
        ):
            continue
        if not (st.background_color or st.has_border):
            continue
        if st.radius_max <= 0 or st.padding_x < 4:
            continue
        badges.append(e)
    sampled["badge"] = len(badges)
    if badges:
        props = _common_props(ctx, badges)
        props.pop("background", None)
        bgs = Counter(ctx.color_role(b.style.background_color) for b in badges if b.style.background_color)
        props["backgrounds"] = [c for c, _ in bgs.most_common(5)]
        recipes.append(_recipe(ctx, "badge", "default", badges, props, "Small labels, tags, counters, kbd.", n0=4))

    return recipes, sampled
