"""Shared statistics helpers for inference."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence

from gtui.core.color import RGBA, distance, parse_color
from gtui.observations.models import ElementObservation


def confidence(n: int, consistency: float = 1.0, n0: int = 30) -> float:
    """Coverage-based confidence: grows with sample size, scaled by consistency.

    This is a heuristic, not a calibrated probability (PRD open question #2). It is reported as
    such in design.md.
    """
    if n <= 0:
        return 0.0
    return round(min(1.0, math.sqrt(n / n0)) * max(0.0, min(1.0, consistency)), 2)


def evidence_sample(elements: Iterable[ElementObservation], k: int = 8) -> list[str]:
    """Pick up to ``k`` observation ids spread across pages."""
    by_page: dict[str, list[str]] = {}
    for e in elements:
        by_page.setdefault(e.page_id, []).append(e.id)
    out: list[str] = []
    while len(out) < k and any(by_page.values()):
        for ids in by_page.values():
            if ids:
                out.append(ids.pop(0))
                if len(out) >= k:
                    break
    return out


def median(values: Sequence[float], default: float = 0.0) -> float:
    vals = [v for v in values if v is not None]
    return float(statistics.median(vals)) if vals else default


def mode(values: Iterable, default=None):
    c = Counter(v for v in values if v is not None)
    return c.most_common(1)[0][0] if c else default


def round_to(value: float, step: float) -> float:
    return round(value / step) * step


def nearest_key(value: float, scale: dict[str, float], tolerance: float | None = None) -> str | None:
    """Closest key in a numeric scale (e.g. radius or type size), optionally within tolerance."""
    best_key, best_d = None, float("inf")
    for key, v in scale.items():
        d = abs(v - value)
        if d < best_d:
            best_key, best_d = key, d
    if best_key is None:
        return None
    if tolerance is not None and best_d > tolerance:
        return None
    return best_key


class Palette:
    """Role lookup for observed colors."""

    def __init__(self, roles: dict[str, str]) -> None:
        self.roles: dict[str, RGBA] = {}
        for role, hx in roles.items():
            c = parse_color(hx)
            if c is not None:
                self.roles[role] = c

    def role_of(self, hex_value: str | None, tolerance: float = 0.035, prefer: tuple[str, ...] = ()) -> str | None:
        """Nearest role within ``tolerance``. When several roles are (near-)equidistant — the same
        value can legitimately be both ``border.subtle`` and ``surface.overlay`` — ``prefer`` picks
        the role family that fits the property being described."""
        if not hex_value:
            return None
        c = parse_color(hex_value)
        if c is None:
            return None
        # alpha matters: an 8% white overlay is not "text.primary" just because both are white
        scored = sorted(
            ((distance(c, rc), role) for role, rc in self.roles.items() if abs(rc.a - c.a) <= 0.15),
            key=lambda t: t[0],
        )
        if not scored or scored[0][0] > tolerance:
            return None
        best_d = scored[0][0]
        ties = [role for d, role in scored if d <= best_d + 0.004]
        for prefix in prefer:
            for role in ties:
                if role.startswith(prefix):
                    return role
        return ties[0]

    def describe(self, hex_value: str | None, prefer: tuple[str, ...] = ()) -> str | None:
        """Role name if known, else the raw hex."""
        if not hex_value:
            return None
        return self.role_of(hex_value, prefer=prefer) or hex_value


def effective_backgrounds(defaults: list[ElementObservation], root_bg: dict[str, str | None]) -> dict[str, str | None]:
    """Nearest opaque ancestor background for every element (its own if opaque)."""
    by_id = {e.id: e for e in defaults}
    cache: dict[str, str | None] = {}

    def resolve(e: ElementObservation) -> str | None:
        if e.id in cache:
            return cache[e.id]
        bg = e.style.background_color
        if bg and len(bg) == 7:  # opaque hex
            cache[e.id] = bg
            return bg
        parent = by_id.get(e.parent_id) if e.parent_id else None
        val = resolve(parent) if parent else root_bg.get(e.page_id)
        cache[e.id] = val
        return val

    for e in defaults:
        resolve(e)
    return cache


def parent_background(
    e: ElementObservation,
    defaults_by_id: dict[str, ElementObservation],
    eff: dict[str, str | None],
    root_bg: dict[str, str | None],
) -> str | None:
    parent = defaults_by_id.get(e.parent_id) if e.parent_id else None
    if parent is None:
        return root_bg.get(e.page_id)
    return eff.get(parent.id)
