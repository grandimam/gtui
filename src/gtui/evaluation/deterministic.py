"""Deterministic evaluation: does a rendered target comply with a profile's tokens?

Takes an ObservationSet of the *target* (captured with the same pipeline) and a profile, and
measures how much of what the target renders falls on the profile's palette, type scale, spacing
grid and radius scale. Reproducible, no model calls. Perceptual critique layers on later.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from gtui.adapters.web.styles import primary_font
from gtui.core.color import distance, parse_color
from gtui.inference.common import Palette
from gtui.ir.schema import AestheticProfile, is_unknown
from gtui.observations.models import ObservationSet


class Dimension(BaseModel):
    name: str
    score: float = Field(ge=0, le=1)
    checked: int = 0
    detail: str = ""
    offenders: list[dict] = Field(default_factory=list)


class EvaluationReport(BaseModel):
    profile: str
    target: str
    evaluated_at: datetime
    overall: float
    dimensions: list[Dimension]
    recommendations: list[str] = Field(default_factory=list)


@dataclass
class _Acc:
    ok: float = 0.0
    total: float = 0.0
    offenders: Counter = field(default_factory=Counter)

    def add(self, good: bool, weight: float, key: str | None = None) -> None:
        self.total += weight
        if good:
            self.ok += weight
        elif key is not None:
            self.offenders[key] += weight

    @property
    def score(self) -> float:
        return round(self.ok / self.total, 3) if self.total else 1.0


def _family_root(name: str) -> str:
    """'Inter Variable' / 'InterVariable' / 'Inter VF' -> 'inter'."""
    n = name.lower().replace("variable", " ").replace(" vf", " ").replace("-", " ")
    return n.split()[0] if n.split() else n


def evaluate(profile: AestheticProfile, target: ObservationSet) -> EvaluationReport:
    t = profile.tokens
    defaults = target.defaults()
    dims: list[Dimension] = []
    recs: list[str] = []

    # Colors ---------------------------------------------------------------------------------
    palette = Palette({r: c.value for r, c in t.colors.items()})
    acc = _Acc()
    for e in defaults:
        bg = e.style.background_color
        if bg and len(bg) == 7 and e.role != "img":
            acc.add(palette.role_of(bg, 0.045) is not None, 1.0, bg)
        if e.text and e.style.color:
            acc.add(palette.role_of(e.style.color, 0.045) is not None, 0.5, e.style.color)
    dims.append(
        Dimension(
            name="color_palette",
            score=acc.score,
            checked=int(acc.total),
            detail="share of opaque backgrounds and text colors that match a profile color role",
            offenders=[{"value": k, "weight": round(v, 1)} for k, v in acc.offenders.most_common(6)],
        )
    )
    if acc.score < 0.85 and acc.offenders:
        recs.append(
            "Replace off-palette colors ("
            + ", ".join(k for k, _ in acc.offenders.most_common(3))
            + ") with the nearest profile role."
        )

    # Scheme / base surface ----------------------------------------------------------------------
    base = profile.color("surface.base")
    tb = Counter(p.root_background for p in target.pages if p.root_background)
    if base and tb:
        d = distance(parse_color(base.value), parse_color(tb.most_common(1)[0][0]))  # type: ignore[arg-type]
        score = 1.0 if d <= 0.03 else (0.5 if d <= 0.1 else 0.0)
        dims.append(
            Dimension(
                name="base_surface",
                score=score,
                checked=1,
                detail=f"target page background {tb.most_common(1)[0][0]} vs profile surface.base {base.value} (ΔE {d:.3f})",
            )
        )
        if score < 1:
            recs.append(f"Set the page background to surface.base ({base.value}).")

    # Typography ----------------------------------------------------------------------------------
    sizes = {k: s.size for k, s in t.typography.scale.items()}
    acc = _Acc()
    fam_acc = _Acc()
    sans = t.typography.families.get("sans")
    sans_name = sans.primary.lower() if sans and not is_unknown(sans) else None  # type: ignore[union-attr]
    sans_roots = {_family_root(f) for f in sans.stack} if sans_name else set()  # type: ignore[union-attr]
    for e in defaults:
        if not (e.text and e.style.font_size > 0):
            continue
        on_scale = any(abs(e.style.font_size - v) <= 0.6 for v in sizes.values()) if sizes else True
        acc.add(on_scale, 1.0, f"{e.style.font_size:g}px")
        if sans_name:
            fam = primary_font(e.style.font_family).lower()
            fam_acc.add(_family_root(fam) in sans_roots, 1.0, fam)
    dims.append(
        Dimension(
            name="type_scale",
            score=acc.score,
            checked=int(acc.total),
            detail="share of text elements whose font-size is on the profile scale",
            offenders=[{"value": k, "weight": round(v)} for k, v in acc.offenders.most_common(6)],
        )
    )
    if acc.score < 0.85 and acc.offenders:
        recs.append(
            "Snap font sizes ("
            + ", ".join(k for k, _ in acc.offenders.most_common(3))
            + ") to the type scale: "
            + ", ".join(f"{k}={v:g}px" for k, v in sizes.items())
            + "."
        )
    if sans_name:
        dims.append(
            Dimension(
                name="font_family",
                score=fam_acc.score,
                checked=int(fam_acc.total),
                detail=f"share of text set in the profile's sans family ({sans_name})",
                offenders=[{"value": k, "weight": round(v)} for k, v in fam_acc.offenders.most_common(4)],
            )
        )
        if fam_acc.score < 0.8:
            recs.append(f"Use '{sans.primary}' (or a metric-compatible fallback) as the base font family.")  # type: ignore[union-attr]

    # Spacing -------------------------------------------------------------------------------------
    if not is_unknown(t.spacing.base):
        base_u = int(t.spacing.base)  # type: ignore[arg-type]
        acc = _Acc()
        for e in defaults:
            for v in [x for x in e.style.padding if x > 0] + ([e.style.gap] if e.style.gap else []):
                iv = int(round(v))
                if 0 < iv <= 160:
                    acc.add(iv % base_u == 0, 1.0, f"{iv}px")
        dims.append(
            Dimension(
                name="spacing_grid",
                score=acc.score,
                checked=int(acc.total),
                detail=f"share of paddings/gaps on the {base_u}px grid",
                offenders=[{"value": k, "weight": round(v)} for k, v in acc.offenders.most_common(6)],
            )
        )
        if acc.score < 0.8:
            recs.append(f"Move spacing onto the {base_u}px grid (scale: {', '.join(map(str, t.spacing.scale))}).")

    # Radius --------------------------------------------------------------------------------------
    radii = {k: v.value for k, v in t.radius.items() if k != "full"}
    if radii:
        acc = _Acc()
        for e in defaults:
            st = e.style
            if not (st.has_border or st.has_shadow or (st.background_color and len(st.background_color) == 7)):
                continue
            r = st.radius_max
            min_side = min(e.bounds.width, e.bounds.height)
            if r > 0 and min_side and r >= min_side / 2 - 0.5:
                acc.add("full" in t.radius, 1.0, "pill")
                continue
            acc.add(any(abs(r - v) <= 1.0 for v in radii.values()), 1.0, f"{r:g}px")
        dims.append(
            Dimension(
                name="radius_scale",
                score=acc.score,
                checked=int(acc.total),
                detail="share of surfaced elements whose corner radius is on the profile scale",
                offenders=[{"value": k, "weight": round(v)} for k, v in acc.offenders.most_common(6)],
            )
        )
        if acc.score < 0.8:
            recs.append("Use only radii from the profile: " + ", ".join(f"{k}={v:g}px" for k, v in radii.items()) + ".")

    # Elevation strategy --------------------------------------------------------------------------
    cards = profile.recipes("card")
    if cards:
        expected = cards[0].properties.get("elevation")
        shadow_n = sum(1 for e in defaults if e.style.has_shadow)
        border_n = sum(1 for e in defaults if e.style.has_border)
        if expected == "border" and shadow_n > border_n:
            dims.append(
                Dimension(
                    name="elevation",
                    score=0.3,
                    checked=shadow_n + border_n,
                    detail=f"profile elevates with borders; target uses {shadow_n} shadows vs {border_n} borders",
                )
            )
            recs.append("Replace drop shadows on containers with 1px borders (border.subtle).")
        elif expected == "shadow" and border_n > 3 * max(1, shadow_n):
            dims.append(
                Dimension(
                    name="elevation",
                    score=0.5,
                    checked=shadow_n + border_n,
                    detail=f"profile elevates with shadows; target uses {border_n} borders vs {shadow_n} shadows",
                )
            )
        else:
            dims.append(
                Dimension(
                    name="elevation",
                    score=1.0,
                    checked=shadow_n + border_n,
                    detail=f"elevation strategy consistent ({expected}); shadows {shadow_n}, borders {border_n}",
                )
            )

    overall = round(sum(d.score for d in dims) / len(dims), 3) if dims else 0.0
    return EvaluationReport(
        profile=profile.metadata.name,
        target=target.source,
        evaluated_at=datetime.now(UTC),
        overall=overall,
        dimensions=dims,
        recommendations=recs,
    )
