"""Infer semantic color roles from observed usage.

Roles are assigned from *how* a color is used (large opaque surfaces, body text, interactive
backgrounds, borders, focus rings), never from the color value alone. Source custom-property
names, when present, are recorded on the token as the strongest role hint.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from gtui.core.color import (
    RGBA,
    contrast_ratio,
    distance,
    hue_family,
    is_neutral,
    lightness,
    parse_color,
)
from gtui.inference.common import confidence, evidence_sample
from gtui.ir.schema import ColorToken
from gtui.observations.models import ElementObservation, ObservationSet

_MAX_AREA = 1440 * 900 * 2
_INTERACTIVE = {"button", "link", "tab", "menuitem", "switch", "checkbox", "radio"}


def _hue_delta(a: RGBA, b: RGBA) -> float:
    from gtui.core.color import hue

    d = abs(hue(a) - hue(b)) % 360
    return min(d, 360 - d)


_COLOR_IN_STRING = re.compile(r"(rgba?\([^)]*\)|oklch\([^)]*\)|oklab\([^)]*\)|color\([^)]*\)|#[0-9a-fA-F]{3,8})")


@dataclass
class Usage:
    color: RGBA
    bg_area: float = 0.0
    bg_count: int = 0
    text_count: int = 0
    text_chars: int = 0
    border_count: int = 0
    interactive_bg: int = 0
    link_text: int = 0
    bg_elements: list[ElementObservation] = field(default_factory=list)
    text_elements: list[ElementObservation] = field(default_factory=list)
    border_elements: list[ElementObservation] = field(default_factory=list)
    bg_names: Counter = field(default_factory=Counter)
    text_names: Counter = field(default_factory=Counter)
    border_names: Counter = field(default_factory=Counter)

    @property
    def weight(self) -> float:
        return self.bg_area / 10_000 + self.bg_count + self.text_count + self.border_count

    def names(self, kind: str) -> Counter:
        return {"bg": self.bg_names, "text": self.text_names, "border": self.border_names}[kind]


class ColorInference:
    def __init__(self, obs: ObservationSet) -> None:
        self.obs = obs
        self.defaults = obs.defaults()
        self.usages: dict[str, Usage] = {}
        self.tokens: dict[str, ColorToken] = {}
        self.scheme: str = "unknown"
        self.notes: list[str] = []

    # -- collection ------------------------------------------------------------------------------

    def _use(self, hex_value: str | None) -> Usage | None:
        if not hex_value:
            return None
        c = parse_color(hex_value)
        if c is None or c.transparent:
            return None
        key = c.hex
        if key not in self.usages:
            self.usages[key] = Usage(color=c)
        return self.usages[key]

    def collect(self) -> None:
        from gtui.inference.common import effective_backgrounds

        root_bg = {p.id: p.root_background for p in self.obs.pages}
        eff = effective_backgrounds(self.defaults, root_bg)
        for e in self.defaults:
            st = e.style
            if e.role == "img":
                continue
            bg = st.background_color
            if bg and len(bg) == 7:  # opaque only; translucent overlays are not surfaces
                u = self._use(bg)
                if u:
                    u.bg_area += min(e.bounds.area, _MAX_AREA)
                    u.bg_count += 1
                    u.bg_elements.append(e)
                    if e.role in _INTERACTIVE:
                        u.interactive_bg += 1
                    if "background-color" in e.css_vars:
                        u.bg_names[e.css_vars["background-color"]] += 1
                    elif "background" in e.css_vars:
                        u.bg_names[e.css_vars["background"]] += 1
            if e.text_length > 0 and st.color and e.text:
                # Text sitting on a saturated surface (button labels on the accent) is not body text;
                # it is captured separately as text.on_accent.
                behind = eff.get(e.id)
                behind_c = parse_color(behind) if behind else None
                if behind_c is not None and not is_neutral(behind_c, 0.06):
                    continue
                u = self._use(st.color)
                if u:
                    u.text_count += 1
                    u.text_chars += min(e.text_length, 400)
                    u.text_elements.append(e)
                    if e.role == "link":
                        u.link_text += 1
                    if "color" in e.css_vars:
                        u.text_names[e.css_vars["color"]] += 1
            if st.has_border and st.border_color:
                u = self._use(st.border_color)
                if u:
                    u.border_count += 1
                    u.border_elements.append(e)
                    for prop in ("border-color", "border", "border-top-color"):
                        if prop in e.css_vars:
                            u.border_names[e.css_vars[prop]] += 1
                            break
        self._merge_near_duplicates()

    def _merge_near_duplicates(self, tol: float = 0.012) -> None:
        """Fold colors that are perceptually identical (anti-aliasing, 1-step differences)."""
        ordered = sorted(self.usages.values(), key=lambda u: -u.weight)
        kept: list[Usage] = []
        for u in ordered:
            for k in kept:
                if abs(u.color.a - k.color.a) <= 0.1 and distance(u.color, k.color) <= tol:
                    k.bg_area += u.bg_area
                    k.bg_count += u.bg_count
                    k.text_count += u.text_count
                    k.text_chars += u.text_chars
                    k.border_count += u.border_count
                    k.interactive_bg += u.interactive_bg
                    k.link_text += u.link_text
                    k.bg_elements += u.bg_elements
                    k.text_elements += u.text_elements
                    k.border_elements += u.border_elements
                    k.bg_names.update(u.bg_names)
                    k.text_names.update(u.text_names)
                    k.border_names.update(u.border_names)
                    break
            else:
                kept.append(u)
        self.usages = {k.color.hex: k for k in kept}

    # -- role assignment -------------------------------------------------------------------------

    def _token(
        self,
        role: str,
        u: Usage,
        elements: list[ElementObservation],
        count: int,
        total: int,
        base: RGBA | None,
        note: str | None = None,
        kind: str = "bg",
        n_boost: int = 0,
    ) -> ColorToken:
        share = count / total if total else 0.0
        tok = ColorToken(
            value=u.color.hex,
            role=role,
            usage_count=count,
            confidence=confidence(count + n_boost, min(1.0, 0.5 + share)),
            evidence=evidence_sample(elements),
            source_names=[n for n, _ in u.names(kind).most_common(3)],
            contrast_on_base=round(contrast_ratio(u.color, base), 2) if base else None,
            note=note,
        )
        self.tokens[role] = tok
        return tok

    def infer(self) -> dict[str, ColorToken]:
        if not self.usages:
            self.collect()
        usages = list(self.usages.values())
        total_bg = sum(u.bg_count for u in usages) or 1
        total_text = sum(u.text_count for u in usages) or 1
        total_border = sum(u.border_count for u in usages) or 1

        # Base surface: dominant opaque background by area, preferring the page root background.
        root_bgs = Counter(p.root_background for p in self.obs.pages if p.root_background)
        base_u: Usage | None = None
        if root_bgs:
            root_hex = root_bgs.most_common(1)[0][0]
            base_u = self._nearest_usage(root_hex)
        if base_u is None or base_u.bg_area == 0:
            cands = [u for u in usages if u.bg_area > 0]
            base_u = max(cands, key=lambda u: u.bg_area) if cands else None
        base = base_u.color if base_u else None
        if base_u:
            self.scheme = "dark" if lightness(base) < 0.5 else "light"
            # every captured page is itself an observation of the base surface
            self._token(
                "surface.base",
                base_u,
                base_u.bg_elements,
                base_u.bg_count,
                total_bg,
                base,
                n_boost=8 * len(self.obs.pages),
            )
        else:
            self.notes.append("No opaque background observed; surface roles unknown.")

        # Neutral surfaces relative to base.
        if base is not None:
            neutrals = [
                u
                for u in usages
                if u is not base_u and u.bg_count >= 2 and is_neutral(u.color) and distance(u.color, base) > 0.012
            ]
            lighter = sorted(
                [u for u in neutrals if lightness(u.color) > lightness(base)], key=lambda u: lightness(u.color)
            )
            darker = sorted(
                [u for u in neutrals if lightness(u.color) < lightness(base)], key=lambda u: -lightness(u.color)
            )
            if self.scheme == "dark":
                raised, overlay = lighter[:1], lighter[1:2]
                sunken = darker[:1]
            else:
                # light scheme: raised = lighter (white cards on grey), sunken = darker (muted bands)
                raised, overlay = lighter[:1], lighter[1:2]
                sunken = darker[:1]
            for role, lst in (("surface.raised", raised), ("surface.overlay", overlay), ("surface.sunken", sunken)):
                if lst:
                    u = lst[0]
                    self._token(role, u, u.bg_elements, u.bg_count, total_bg, base)
            inverse = [u for u in neutrals if abs(lightness(u.color) - lightness(base)) > 0.5]
            if inverse:
                u = max(inverse, key=lambda u: u.bg_count)
                self._token("surface.inverse", u, u.bg_elements, u.bg_count, total_bg, base)

        # Text roles. Primary = the highest-contrast neutral text color that is in real use (the
        # headline/body color); secondary/tertiary = progressively lower-contrast tiers. Volume alone
        # is misleading: muted captions can outnumber body text on dense screens.
        neutral_text = [u for u in usages if u.text_count >= 2 and is_neutral(u.color, 0.05)]
        if base is not None:
            neutral_text = [u for u in neutral_text if contrast_ratio(u.color, base) >= 1.8]
        if neutral_text:
            max_chars = max(u.text_chars for u in neutral_text) or 1
            by_contrast = sorted(
                neutral_text, key=lambda u: -(contrast_ratio(u.color, base) if base is not None else u.text_chars)
            )
            in_use = [u for u in by_contrast if u.text_chars >= 0.15 * max_chars or u.text_count >= 5]
            primary = (in_use or by_contrast)[0]
            self._token(
                "text.primary", primary, primary.text_elements, primary.text_count, total_text, base, kind="text"
            )
            if base is not None:
                p_contrast = contrast_ratio(primary.color, base)
                lower = [
                    u
                    for u in by_contrast
                    if u is not primary
                    and distance(u.color, primary.color) > 0.03
                    and contrast_ratio(u.color, base) < p_contrast - 0.3
                ]
                # secondary = the most used lower-contrast tier; tertiary = a clearly dimmer one
                lower_by_use = sorted(lower, key=lambda u: -u.text_chars)
                if lower_by_use:
                    sec = lower_by_use[0]
                    self._token("text.secondary", sec, sec.text_elements, sec.text_count, total_text, base, kind="text")
                    s_contrast = contrast_ratio(sec.color, base)
                    tert = [u for u in lower_by_use[1:] if contrast_ratio(u.color, base) < s_contrast - 0.3]
                    if tert:
                        self._token(
                            "text.tertiary",
                            tert[0],
                            tert[0].text_elements,
                            tert[0].text_count,
                            total_text,
                            base,
                            kind="text",
                        )

        # Accent: saturated color used on interactive backgrounds (or, failing that, on links).
        saturated = [u for u in usages if not is_neutral(u.color)]
        accent_u = None
        bg_sat = sorted(
            [u for u in saturated if u.bg_count >= 1 and (u.interactive_bg >= 1 or u.bg_count >= 3)],
            key=lambda u: -(u.interactive_bg * 3 + u.bg_count),
        )
        if bg_sat:
            accent_u = bg_sat[0]
            self._token(
                "accent.primary",
                accent_u,
                accent_u.bg_elements,
                accent_u.bg_count,
                total_bg,
                base,
                note="Brand-adjacent hue. Keep its lightness/chroma; substitute your own hue if needed.",
            )
        else:
            link_sat = sorted([u for u in saturated if u.link_text >= 2], key=lambda u: -u.link_text)
            if link_sat:
                accent_u = link_sat[0]
                self._token(
                    "accent.primary",
                    accent_u,
                    accent_u.text_elements,
                    accent_u.text_count,
                    total_text,
                    base,
                    note="Accent inferred from link color; no saturated interactive surfaces observed.",
                )
        if accent_u is not None:
            # text on accent surfaces
            on_accent = Counter()
            samples: list[ElementObservation] = []
            for e in accent_u.bg_elements:
                for child in self._descendant_text(e):
                    if child.style.color and len(child.style.color) == 7:  # opaque text only
                        on_accent[child.style.color] += 1
                        samples.append(child)
                if e.text and e.style.color and len(e.style.color) == 7:
                    on_accent[e.style.color] += 1
                    samples.append(e)
            if on_accent:
                hx, n = on_accent.most_common(1)[0]
                u = self._nearest_usage(hx) or Usage(color=parse_color(hx))  # type: ignore[arg-type]
                self._token(
                    "text.on_accent",
                    u,
                    [s for s in samples if s.style.color == hx],
                    n,
                    n,
                    accent_u.color,
                    kind="text",
                    note="Text color used on accent surfaces (buttons, selected rows).",
                )
            # second accent
            others = [
                u
                for u in bg_sat[1:]
                if distance(u.color, accent_u.color) > 0.12
                and hue_family(u.color) not in ("red", "green", "orange", "yellow")
            ]
            if others and others[0].bg_count >= 3:
                self._token("accent.secondary", others[0], others[0].bg_elements, others[0].bg_count, total_bg, base)
            # link color, only when it is not simply the accent
            link_sat = sorted([u for u in saturated if u.link_text >= 2], key=lambda u: -u.link_text)
            if link_sat and distance(link_sat[0].color, accent_u.color) > 0.03:
                lu = link_sat[0]
                self._token("text.link", lu, lu.text_elements, lu.link_text, total_text, base, kind="text")
        # Status colors by hue family (only if actually observed more than once, and not a tint of
        # the accent hue).
        for u in sorted(saturated, key=lambda u: -(u.bg_count + u.text_count + u.border_count)):
            if accent_u is not None and (
                distance(u.color, accent_u.color) <= 0.1 or _hue_delta(u.color, accent_u.color) < 25
            ):
                continue
            n = u.bg_count + u.text_count + u.border_count
            # isolated saturated colors (syntax highlighting, one-off labels) are exceptions, not status
            if n < 3 or not u.color.opaque:
                continue
            fam = hue_family(u.color)
            role = {
                "red": "status.danger",
                "green": "status.success",
                "orange": "status.warning",
                "yellow": "status.warning",
                "blue": "status.info",
                "teal": "status.info",
            }.get(fam)
            if role and role not in self.tokens:
                kind = "bg" if u.bg_count >= u.text_count else "text"
                self._token(
                    role,
                    u,
                    u.bg_elements + u.text_elements + u.border_elements,
                    n,
                    total_bg + total_text,
                    base,
                    kind=kind,
                )

        # Borders.
        border_u = sorted([u for u in usages if u.border_count >= 2], key=lambda u: -u.border_count)
        if border_u:
            b0 = border_u[0]
            self._token("border.subtle", b0, b0.border_elements, b0.border_count, total_border, base, kind="border")
            if base is not None:
                stronger = [
                    u
                    for u in border_u[1:]
                    if is_neutral(u.color, 0.06)
                    and abs(lightness(u.color) - lightness(base)) > abs(lightness(b0.color) - lightness(base)) + 0.08
                ]
                if stronger:
                    s = stronger[0]
                    self._token(
                        "border.strong", s, s.border_elements, s.border_count, total_border, base, kind="border"
                    )
        self._focus_ring(base)
        if base is not None:
            hover = self._accent_hover(accent_u)
            if hover:
                self.tokens["accent.hover"] = hover
        return self.tokens

    # -- helpers ---------------------------------------------------------------------------------

    def _nearest_usage(self, hex_value: str, tol: float = 0.02) -> Usage | None:
        c = parse_color(hex_value)
        if c is None:
            return None
        best, best_d = None, float("inf")
        for u in self.usages.values():
            if abs(u.color.a - c.a) > 0.1:  # a translucent overlay is not the same token as its opaque twin
                continue
            d = distance(u.color, c)
            if d < best_d:
                best, best_d = u, d
        return best if best is not None and best_d <= tol else None

    def _descendant_text(self, e: ElementObservation) -> list[ElementObservation]:
        out = []
        for d in self.defaults:
            if d.parent_id == e.id and d.text:
                out.append(d)
        return out

    def _focus_ring(self, base: RGBA | None) -> None:
        colors: Counter = Counter()
        samples: list[ElementObservation] = []
        for e in self.obs.elements:
            if e.state != "focus-visible":
                continue
            cands = []
            if e.state_diff.get("outline-color") and e.state_diff.get("outline-style", "none") not in ("none", "auto"):
                cands.append(e.state_diff["outline-color"])
            if e.state_diff.get("box-shadow"):
                cands += _COLOR_IN_STRING.findall(e.state_diff["box-shadow"])
            if e.state_diff.get("border-top-color"):
                cands.append(e.state_diff["border-top-color"])
            for raw in cands:
                c = parse_color(raw)
                if c and not c.transparent:
                    colors[c.hex] += 1
                    samples.append(e)
                    break
        if colors:
            hx, n = colors.most_common(1)[0]
            c = parse_color(hx)
            assert c
            u = self._nearest_usage(hx, 0.05) or Usage(color=c)
            self.tokens["border.focus"] = ColorToken(
                value=c.hex,
                role="border.focus",
                usage_count=n,
                confidence=confidence(n, 0.8, n0=10),
                evidence=evidence_sample(samples),
                source_names=[s for s, _ in (u.bg_names + u.border_names + u.text_names).most_common(2)],
                contrast_on_base=round(contrast_ratio(c, base), 2) if base else None,
                note="Focus ring color (outline / box-shadow under :focus-visible).",
            )

    def _accent_hover(self, accent_u: Usage | None) -> ColorToken | None:
        if accent_u is None:
            return None
        accent_keys = {(e.page_id, e.key) for e in accent_u.bg_elements}
        colors: Counter = Counter()
        samples = []
        for e in self.obs.elements:
            # state observations carry their own ids; join on (page, element key)
            if e.state != "hover" or (e.page_id, e.key) not in accent_keys:
                continue
            bg = e.state_diff.get("background-color")
            c = parse_color(bg) if bg else None
            if c and not c.transparent and distance(c, accent_u.color) > 0.01:
                colors[c.hex] += 1
                samples.append(e)
        if not colors:
            return None
        hx, n = colors.most_common(1)[0]
        return ColorToken(
            value=hx,
            role="accent.hover",
            usage_count=n,
            confidence=confidence(n, 0.9, n0=8),
            evidence=evidence_sample(samples),
        )
