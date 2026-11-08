"""Spacing grid, corner radii, shadows, borders and motion."""

from __future__ import annotations

from collections import Counter, defaultdict

from gtui.adapters.web.styles import shadow_blur
from gtui.inference.common import Palette, confidence, evidence_sample, mode
from gtui.ir.schema import Borders, DimensionToken, Motion, ShadowToken, SpacingScale, unknown
from gtui.observations.models import ElementObservation, ObservationSet


def infer_spacing(obs: ObservationSet) -> SpacingScale:
    values: Counter = Counter()
    elems: dict[int, list[ElementObservation]] = defaultdict(list)
    for e in obs.defaults():
        st = e.style
        cands = [v for v in st.padding if v > 0] + ([st.gap] if st.gap and st.gap > 0 else [])
        cands += [v for v in st.margin if 0 < v < 200]
        for v in cands:
            iv = int(round(v))
            if 0 < iv <= 160:
                values[iv] += 1
                if len(elems[iv]) < 20:
                    elems[iv].append(e)
    total = sum(values.values())
    if total < 10:
        return SpacingScale(base=unknown("too few spacing values observed"), usage_count=total)

    def adherence(base: int) -> float:
        return sum(n for v, n in values.items() if v % base == 0) / total

    base: int
    if adherence(8) >= 0.85:
        base = 8
    elif adherence(4) >= 0.6:
        base = 4
    else:
        base = max((2, 3, 5, 6), key=adherence)
    adh = adherence(base)
    scale = sorted(v for v, n in values.items() if v % base == 0 and n >= max(2, 0.015 * total))
    if len(scale) > 12:
        top = {v for v, _ in sorted(((v, values[v]) for v in scale), key=lambda t: -t[1])[:12]}
        scale = sorted(top)
    ev: list[ElementObservation] = []
    for v in scale[:6]:
        ev += elems[v][:2]
    return SpacingScale(
        base=base,
        scale=scale,
        grid_adherence=round(adh, 3),
        usage_count=total,
        confidence=confidence(total, adh, n0=60),
        evidence=evidence_sample(ev, 10),
    )


def _radius_name(v: float) -> str:
    if v <= 0:
        return "none"
    if v <= 2:
        return "xs"
    if v <= 4:
        return "sm"
    if v <= 7:
        return "md"
    if v <= 11:
        return "lg"
    if v <= 18:
        return "xl"
    return "2xl"


def infer_radius(obs: ObservationSet) -> tuple[dict[str, DimensionToken], float | None]:
    """Returns (radius tokens, dominant non-zero radius or None)."""
    counts: Counter = Counter()
    elems: dict[float, list[ElementObservation]] = defaultdict(list)
    full_elems: list[ElementObservation] = []
    for e in obs.defaults():
        st = e.style
        if e.role == "img" or e.tag in ("svg", "img"):
            continue
        surfaced = st.has_border or st.has_shadow or (st.background_color and len(st.background_color) == 7)
        if not surfaced:
            continue
        r = round(st.radius_max)
        if r <= 0:
            counts[0] += 1
            if len(elems[0]) < 20:
                elems[0].append(e)
            continue
        min_side = min(e.bounds.width, e.bounds.height)
        if min_side > 0 and st.radius_max >= min_side / 2 - 0.5:
            full_elems.append(e)
            continue
        counts[r] += 1
        if len(elems[r]) < 20:
            elems[r].append(e)
    tokens: dict[str, DimensionToken] = {}
    total = sum(counts.values()) + len(full_elems)
    if total == 0:
        return tokens, None
    nonzero = {v: n for v, n in counts.items() if v > 0}
    dominant = max(nonzero, key=nonzero.get) if nonzero else None
    tokens["none"] = DimensionToken(
        value=0,
        usage_count=counts.get(0, 0),
        confidence=confidence(counts.get(0, 0), 1.0),
        evidence=evidence_sample(elems[0], 4),
    )
    nz_total = sum(nonzero.values()) or 1
    for v, n in sorted(nonzero.items(), key=lambda t: -t[1]):
        if n < max(2, 0.04 * nz_total) and v != dominant:
            continue
        name = _radius_name(v)
        if name in tokens:
            continue  # the more-used value already owns this bucket
        tokens[name] = DimensionToken(
            value=float(v),
            usage_count=n,
            confidence=confidence(n, n / nz_total + 0.4, n0=15),
            evidence=evidence_sample(elems[v], 6),
        )
    tokens = dict(sorted(tokens.items(), key=lambda kv: kv[1].value))
    if full_elems:
        tokens["full"] = DimensionToken(
            value=9999,
            usage_count=len(full_elems),
            confidence=confidence(len(full_elems), 1.0, n0=8),
            evidence=evidence_sample(full_elems, 6),
        )
    return tokens, float(dominant) if dominant is not None else None


def _shadow_name(blur: float) -> str:
    if blur <= 3:
        return "xs"
    if blur <= 8:
        return "sm"
    if blur <= 18:
        return "md"
    if blur <= 36:
        return "lg"
    return "xl"


def infer_shadows(obs: ObservationSet) -> dict[str, ShadowToken]:
    counts: Counter = Counter()
    elems: dict[str, list[ElementObservation]] = defaultdict(list)
    for e in obs.defaults():
        if e.style.has_shadow and e.style.box_shadow:
            counts[e.style.box_shadow] += 1
            if len(elems[e.style.box_shadow]) < 20:
                elems[e.style.box_shadow].append(e)
    tokens: dict[str, ShadowToken] = {}
    total = sum(counts.values())
    for value, n in counts.most_common(8):
        if n < 2 and total > 6:
            continue
        blur = shadow_blur(value)
        name = _shadow_name(blur)
        if name in tokens:
            continue
        tokens[name] = ShadowToken(
            value=value,
            blur=blur,
            usage_count=n,
            confidence=confidence(n, 0.9, n0=8),
            evidence=evidence_sample(elems[value], 6),
        )
    return dict(sorted(tokens.items(), key=lambda kv: kv[1].blur))


def infer_borders(obs: ObservationSet, palette: Palette) -> Borders:
    widths: Counter = Counter()
    colors: Counter = Counter()
    ev: list[ElementObservation] = []
    for e in obs.defaults():
        if e.style.has_border:
            widths[round(e.style.border_width, 1)] += 1
            if e.style.border_color:
                colors[e.style.border_color] += 1
            if len(ev) < 40:
                ev.append(e)
    if not widths:
        return Borders(width=unknown("no borders observed"), color_role=unknown("no borders observed"))
    w = widths.most_common(1)[0][0]
    total = sum(widths.values())
    role = palette.describe(colors.most_common(1)[0][0], prefer=("border.",)) if colors else None
    return Borders(
        width=w,
        color_role=role or unknown(),
        confidence=confidence(total, widths[w] / total),
        evidence=evidence_sample(ev),
    )


def infer_motion(obs: ObservationSet) -> Motion:
    durs: Counter = Counter()
    eases: Counter = Counter()
    props: Counter = Counter()
    ev: list[ElementObservation] = []
    for e in obs.defaults():
        st = e.style
        active = [d for d in st.transition_durations if d > 0]
        if not active:
            continue
        for d in active:
            durs[int(round(d))] += 1
        for ez in st.transition_easings:
            eases[ez] += 1
        for p in st.transition_properties:
            if p not in ("all", "none"):
                props[p] += 1
        if len(ev) < 40:
            ev.append(e)
    total = sum(durs.values())
    if total == 0:
        return Motion(
            durations=unknown("no CSS transitions observed on captured elements"),
            easings=unknown("no CSS transitions observed"),
        )
    frequent = sorted(d for d, n in durs.items() if n >= max(1, 0.05 * total))
    m = mode(durs.elements())
    if len(frequent) == 1:
        durations = {"base": frequent[0]}
    elif len(frequent) == 2:
        durations = {"fast": frequent[0], "base": frequent[1]}
    else:
        durations = {"fast": frequent[0], "base": int(m), "slow": frequent[-1]}
    return Motion(
        durations=durations,
        easings=[ez for ez, _ in eases.most_common(3)],
        properties=[p for p, _ in props.most_common(6)],
        confidence=confidence(total, 0.8, n0=25),
        evidence=evidence_sample(ev),
    )
