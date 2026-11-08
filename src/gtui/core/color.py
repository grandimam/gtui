"""Color parsing and perceptual math.

Chrome reports computed colors as ``rgb()``/``rgba()``, and as ``oklch()``, ``oklab()`` or
``color(srgb …)`` when authors used modern syntax (Tailwind v4 / shadcn default to oklch).
We normalize everything to sRGB and expose OKLab-based lightness/chroma/distance, which track
perception far better than raw RGB.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?"
_RGB_RE = re.compile(rf"rgba?\(\s*({_NUM})\s*,?\s*({_NUM})\s*,?\s*({_NUM})\s*(?:[,/]\s*({_NUM}%?))?\s*\)")
_OKLCH_RE = re.compile(rf"oklch\(\s*({_NUM}%?)\s+({_NUM}%?)\s+({_NUM})(?:deg)?\s*(?:/\s*({_NUM}%?))?\s*\)")
_OKLAB_RE = re.compile(rf"oklab\(\s*({_NUM}%?)\s+({_NUM}%?)\s+({_NUM}%?)\s*(?:/\s*({_NUM}%?))?\s*\)")
_SRGB_RE = re.compile(rf"color\(srgb\s+({_NUM}%?)\s+({_NUM}%?)\s+({_NUM}%?)\s*(?:/\s*({_NUM}%?))?\s*\)")
_HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")

NAMED = {"transparent": (0, 0, 0, 0.0), "white": (255, 255, 255, 1.0), "black": (0, 0, 0, 1.0)}


@dataclass(frozen=True)
class RGBA:
    r: int
    g: int
    b: int
    a: float = 1.0

    @property
    def hex(self) -> str:
        """``#rrggbb`` for opaque colors, ``#rrggbbaa`` otherwise."""
        base = f"#{self.r:02x}{self.g:02x}{self.b:02x}"
        if self.a >= 0.995:
            return base
        return base + f"{round(self.a * 255):02x}"

    @property
    def opaque(self) -> bool:
        return self.a >= 0.995

    @property
    def transparent(self) -> bool:
        return self.a <= 0.005


def _pct_or_num(token: str, scale: float = 1.0) -> float:
    token = token.strip()
    if token.endswith("%"):
        return float(token[:-1]) / 100.0 * scale
    return float(token)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def parse_color(value: str | None) -> RGBA | None:
    """Parse a computed CSS color. Returns ``None`` for unparseable values."""
    if not value:
        return None
    v = value.strip().lower()
    if v in NAMED:
        r, g, b, a = NAMED[v]
        return RGBA(r, g, b, a)
    m = _RGB_RE.fullmatch(v)
    if m:
        r, g, b = (int(round(float(m.group(i)))) for i in (1, 2, 3))
        a = _pct_or_num(m.group(4)) if m.group(4) else 1.0
        return RGBA(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)), _clamp01(a))
    m = _OKLCH_RE.fullmatch(v)
    if m:
        L = _pct_or_num(m.group(1))
        C = _pct_or_num(m.group(2), 0.4)
        H = float(m.group(3))
        a = _pct_or_num(m.group(4)) if m.group(4) else 1.0
        r, g, b = oklab_to_srgb(L, C * math.cos(math.radians(H)), C * math.sin(math.radians(H)))
        return RGBA(r, g, b, _clamp01(a))
    m = _OKLAB_RE.fullmatch(v)
    if m:
        L = _pct_or_num(m.group(1))
        a_ = _pct_or_num(m.group(2), 0.4)
        b_ = _pct_or_num(m.group(3), 0.4)
        a = _pct_or_num(m.group(4)) if m.group(4) else 1.0
        r, g, b = oklab_to_srgb(L, a_, b_)
        return RGBA(r, g, b, _clamp01(a))
    m = _SRGB_RE.fullmatch(v)
    if m:
        r, g, b = (int(round(_clamp01(_pct_or_num(m.group(i))) * 255)) for i in (1, 2, 3))
        a = _pct_or_num(m.group(4)) if m.group(4) else 1.0
        return RGBA(r, g, b, _clamp01(a))
    m = _HEX_RE.fullmatch(v)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(ch * 2 for ch in h)
        if len(h) == 6:
            return RGBA(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
        if len(h) == 8:
            return RGBA(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16) / 255)
    return None


# --- sRGB <-> OKLab -------------------------------------------------------------------------


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = _clamp01(c)
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def srgb_to_oklab(r: int, g: int, b: int) -> tuple[float, float, float]:
    rl, gl, bl = (_srgb_to_linear(c / 255) for c in (r, g, b))
    lin_l = 0.4122214708 * rl + 0.5363325363 * gl + 0.0514459929 * bl
    lin_m = 0.2119034982 * rl + 0.6806995451 * gl + 0.1073969566 * bl
    lin_s = 0.0883024619 * rl + 0.2817188376 * gl + 0.6299787005 * bl
    l_, m_, s_ = (math.copysign(abs(x) ** (1 / 3), x) for x in (lin_l, lin_m, lin_s))
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, a, bb


def oklab_to_srgb(L: float, a: float, b: float) -> tuple[int, int, int]:
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    lin_l, lin_m, lin_s = l_**3, m_**3, s_**3
    rl = 4.0767416621 * lin_l - 3.3077115913 * lin_m + 0.2309699292 * lin_s
    gl = -1.2684380046 * lin_l + 2.6097574011 * lin_m - 0.3413193965 * lin_s
    bl = -0.0041960863 * lin_l - 0.7034186147 * lin_m + 1.7076147010 * lin_s
    return tuple(int(round(_linear_to_srgb(c) * 255)) for c in (rl, gl, bl))  # type: ignore[return-value]


def to_oklch(c: RGBA) -> tuple[float, float, float]:
    L, a, b = srgb_to_oklab(c.r, c.g, c.b)
    C = math.hypot(a, b)
    h = math.degrees(math.atan2(b, a)) % 360 if C > 1e-4 else 0.0
    return L, C, h


def oklch_css(c: RGBA, precision: int = 3) -> str:
    L, C, h = to_oklch(c)
    body = f"{L:.{precision}f} {C:.{precision}f} {h:.1f}"
    if c.opaque:
        return f"oklch({body})"
    return f"oklch({body} / {c.a:.2f})"


def lightness(c: RGBA) -> float:
    """Perceptual lightness in [0, 1] (OKLab L)."""
    return srgb_to_oklab(c.r, c.g, c.b)[0]


def chroma(c: RGBA) -> float:
    return to_oklch(c)[1]


def hue(c: RGBA) -> float:
    return to_oklch(c)[2]


def is_neutral(c: RGBA, max_chroma: float = 0.04) -> bool:
    return chroma(c) < max_chroma


def distance(a: RGBA, b: RGBA) -> float:
    """Euclidean distance in OKLab (≈ perceptual ΔE; 0.02 is barely distinguishable)."""
    la, aa, ba = srgb_to_oklab(a.r, a.g, a.b)
    lb, ab, bb = srgb_to_oklab(b.r, b.g, b.b)
    return math.sqrt((la - lb) ** 2 + (aa - ab) ** 2 + (ba - bb) ** 2)


def relative_luminance(c: RGBA) -> float:
    rl, gl, bl = (_srgb_to_linear(x / 255) for x in (c.r, c.g, c.b))
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def contrast_ratio(a: RGBA, b: RGBA) -> float:
    """WCAG 2.x contrast ratio."""
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def composite(fg: RGBA, bg: RGBA) -> RGBA:
    """Alpha-composite ``fg`` over an opaque ``bg``."""
    a = fg.a
    return RGBA(
        int(round(fg.r * a + bg.r * (1 - a))),
        int(round(fg.g * a + bg.g * (1 - a))),
        int(round(fg.b * a + bg.b * (1 - a))),
        1.0,
    )


def hue_family(c: RGBA) -> str:
    """Coarse hue name used for status-color inference."""
    if is_neutral(c):
        return "neutral"
    # OKLCH hue anchors: red≈25°, orange≈60°, yellow≈105°, green≈145°, cyan≈195°,
    # blue≈265°, violet≈295°, magenta≈330°.
    h = hue(c)
    if h < 40 or h >= 350:
        return "red"
    if h < 75:
        return "orange"
    if h < 115:
        return "yellow"
    if h < 175:
        return "green"
    if h < 225:
        return "teal"
    if h < 280:
        return "blue"
    if h < 330:
        return "purple"
    return "pink"
