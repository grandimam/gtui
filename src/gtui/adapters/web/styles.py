"""Normalize raw computed-style strings into :class:`ComputedStyle`."""

from __future__ import annotations

import re

from gtui.core.color import parse_color
from gtui.observations.models import ComputedStyle

_PX_RE = re.compile(r"^(-?\d*\.?\d+)px$")
_TIME_RE = re.compile(r"^(-?\d*\.?\d+)(ms|s)$")

_WEIGHT_NAMES = {"normal": 400, "bold": 700, "lighter": 300, "bolder": 700}


def px(value: str | None, default: float = 0.0) -> float:
    if not value:
        return default
    m = _PX_RE.match(value.strip())
    return float(m.group(1)) if m else default


def px_or_none(value: str | None) -> float | None:
    if not value:
        return None
    m = _PX_RE.match(value.strip())
    return float(m.group(1)) if m else None


def color_hex(value: str | None) -> str | None:
    c = parse_color(value)
    if c is None or c.transparent:
        return None
    return c.hex


def weight(value: str | None) -> int:
    if not value:
        return 400
    v = value.strip().lower()
    if v in _WEIGHT_NAMES:
        return _WEIGHT_NAMES[v]
    try:
        return int(round(float(v)))
    except ValueError:
        return 400


def durations_ms(value: str | None) -> list[float]:
    out: list[float] = []
    for part in (value or "").split(","):
        m = _TIME_RE.match(part.strip())
        if not m:
            continue
        n = float(m.group(1))
        out.append(n if m.group(2) == "ms" else n * 1000)
    return out


def split_list(value: str | None) -> list[str]:
    # timing functions may contain commas inside cubic-bezier(...)
    out, depth, cur = [], 0, ""
    for ch in value or "":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def letter_spacing_px(value: str | None) -> float:
    if not value or value.strip() == "normal":
        return 0.0
    return px(value, 0.0)


def line_height_px(value: str | None) -> float | None:
    if not value or value.strip() == "normal":
        return None
    return px_or_none(value)


def normalize(raw: dict[str, str]) -> ComputedStyle:
    g = raw.get
    bg_image = (g("background-image") or "none").strip()
    shadow = (g("box-shadow") or "none").strip()
    backdrop = (g("backdrop-filter") or "none").strip()
    gap_vals = [px_or_none(g("row-gap")), px_or_none(g("column-gap"))]
    gaps = [v for v in gap_vals if v is not None and v > 0]
    border_style = (g("border-top-style") or "none").strip()
    return ComputedStyle(
        display=g("display") or "",
        position=g("position") or "",
        color=color_hex(g("color")),
        background_color=color_hex(g("background-color")),
        has_gradient="gradient(" in bg_image,
        has_background_image=bg_image != "none",
        font_family=(g("font-family") or "").strip(),
        font_size=px(g("font-size"), 0.0),
        font_weight=weight(g("font-weight")),
        line_height=line_height_px(g("line-height")),
        letter_spacing=letter_spacing_px(g("letter-spacing")),
        text_transform=(g("text-transform") or "none").strip(),
        text_decoration=(g("text-decoration-line") or "none").strip(),
        border_width=px(g("border-top-width"), 0.0) if border_style not in ("none", "hidden") else 0.0,
        border_style=border_style,
        border_color=color_hex(g("border-top-color")),
        radius=[
            px(g("border-top-left-radius")),
            px(g("border-top-right-radius")),
            px(g("border-bottom-right-radius")),
            px(g("border-bottom-left-radius")),
        ],
        box_shadow=None if shadow == "none" else shadow,
        opacity=float(g("opacity") or 1.0),
        padding=[
            px(g("padding-top")),
            px(g("padding-right")),
            px(g("padding-bottom")),
            px(g("padding-left")),
        ],
        margin=[
            px(g("margin-top")),
            px(g("margin-right")),
            px(g("margin-bottom")),
            px(g("margin-left")),
        ],
        gap=max(gaps) if gaps else None,
        cursor=(g("cursor") or "auto").strip(),
        outline_width=px(g("outline-width"), 0.0),
        outline_style=(g("outline-style") or "none").strip(),
        outline_color=color_hex(g("outline-color")),
        transition_durations=durations_ms(g("transition-duration")),
        transition_properties=[p for p in split_list(g("transition-property")) if p],
        transition_easings=split_list(g("transition-timing-function")),
        backdrop_filter=None if backdrop == "none" else backdrop,
        max_width=px_or_none(g("max-width")),
        flex_direction=g("flex-direction") or "",
        align_items=g("align-items") or "",
        justify_content=g("justify-content") or "",
    )


def primary_font(family: str) -> str:
    """First family in a stack, unquoted."""
    first = split_list(family)[0] if family else ""
    return first.strip().strip("'\"")


def font_stack(family: str) -> list[str]:
    return [f.strip().strip("'\"") for f in split_list(family) if f.strip()]


def shadow_blur(shadow: str) -> float:
    """Largest blur radius in a box-shadow list (px)."""
    best = 0.0
    for part in split_list(shadow):
        nums = [float(m) for m in re.findall(r"(-?\d*\.?\d+)px", part)]
        if len(nums) >= 3:
            best = max(best, abs(nums[2]))
    return best
