"""Infer font families, the type scale and heading conventions."""

from __future__ import annotations

from collections import Counter, defaultdict

from gtui.adapters.web.styles import font_stack, primary_font
from gtui.inference.common import confidence, evidence_sample, mode
from gtui.ir.mapping import TYPE_SCALE_KEYS
from gtui.ir.schema import FontFamily, TypeStep, Typography, unknown
from gtui.observations.models import ElementObservation, ObservationSet

OPEN_FONTS = {
    "inter",
    "roboto",
    "geist",
    "geist sans",
    "geist mono",
    "ibm plex sans",
    "ibm plex mono",
    "source sans pro",
    "source sans 3",
    "source code pro",
    "open sans",
    "lato",
    "manrope",
    "dm sans",
    "dm mono",
    "space grotesk",
    "space mono",
    "jetbrains mono",
    "fira code",
    "fira sans",
    "poppins",
    "nunito",
    "nunito sans",
    "work sans",
    "public sans",
    "system-ui",
    "-apple-system",
    "blinkmacsystemfont",
    "segoe ui",
    "helvetica",
    "helvetica neue",
    "arial",
    "sans-serif",
    "serif",
    "monospace",
    "ui-sans-serif",
    "ui-monospace",
    "ui-serif",
    "menlo",
    "monaco",
    "consolas",
    "courier new",
    "georgia",
    "times new roman",
    "sf mono",
    "sfmono-regular",
    "noto sans",
    "plus jakarta sans",
    "outfit",
    "figtree",
    "onest",
    "instrument sans",
    "instrument serif",
    "bricolage grotesque",
    "lora",
    "merriweather",
    "playfair display",
    "ubuntu",
    "rubik",
    "karla",
    "mulish",
    "raleway",
    "montserrat",
    "oswald",
    "pt sans",
    "pt serif",
    "cabin",
    "quicksand",
    "red hat display",
    "red hat text",
    "libre franklin",
    "libre baskerville",
    "crimson pro",
    "ibm plex serif",
    "overpass",
    "archivo",
    "sora",
    "urbanist",
    "lexend",
    "be vietnam pro",
}
MONO_HINTS = ("mono", "code", "courier", "consolas", "menlo", "monaco")

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def _text_elements(obs: ObservationSet) -> list[ElementObservation]:
    return [
        e
        for e in obs.defaults()
        if e.text
        and e.text_length > 0
        and e.style.font_size > 0
        and e.role != "img"
        and e.tag not in ("svg", "img", "video", "canvas")
    ]


def infer_typography(obs: ObservationSet) -> tuple[Typography, list[str], list[str]]:
    """Returns (typography, brand_notes, unknown_notes)."""
    texts = _text_elements(obs)
    typo = Typography()
    brand_notes: list[str] = []
    unknowns: list[str] = []
    if not texts:
        unknowns.append("typography: no text elements observed")
        return typo, brand_notes, unknowns

    # Families -----------------------------------------------------------------------------------
    fam_chars: Counter = Counter()
    fam_elems: dict[str, list[ElementObservation]] = defaultdict(list)
    fam_stack: dict[str, list[str]] = {}
    heading_fams: Counter = Counter()
    for e in texts:
        fam = primary_font(e.style.font_family)
        if not fam:
            continue
        fam_chars[fam] += min(e.text_length, 400)
        fam_elems[fam].append(e)
        fam_stack.setdefault(fam, font_stack(e.style.font_family))
        if e.tag in _HEADING_TAGS:
            heading_fams[fam] += 1

    def is_mono(fam: str) -> bool:
        stack = [s.lower() for s in fam_stack.get(fam, [])]
        return any(h in fam.lower() for h in MONO_HINTS) or "monospace" in stack

    total_chars = sum(fam_chars.values()) or 1
    sans_candidates = [f for f, _ in fam_chars.most_common() if not is_mono(f)]
    if sans_candidates:
        f = sans_candidates[0]
        share = fam_chars[f] / total_chars
        typo.families["sans"] = FontFamily(
            stack=fam_stack[f],
            generic="sans-serif",
            usage_count=len(fam_elems[f]),
            confidence=confidence(len(fam_elems[f]), share),
            evidence=evidence_sample(fam_elems[f]),
            note=None if f.lower() in OPEN_FONTS else "Verify font license before reuse.",
        )
        if f.lower() not in OPEN_FONTS:
            brand_notes.append(
                f"Font '{f}' may be proprietary; verify license or substitute a metric-compatible open font."
            )
    mono_candidates = [f for f, _ in fam_chars.most_common() if is_mono(f)]
    if mono_candidates:
        f = mono_candidates[0]
        typo.families["mono"] = FontFamily(
            stack=fam_stack[f],
            generic="monospace",
            usage_count=len(fam_elems[f]),
            confidence=confidence(len(fam_elems[f]), 0.9, n0=10),
            evidence=evidence_sample(fam_elems[f]),
        )
    else:
        typo.families["mono"] = unknown("no monospace text observed")
    if heading_fams:
        hf = heading_fams.most_common(1)[0][0]
        if sans_candidates and hf != sans_candidates[0] and not is_mono(hf):
            typo.families["display"] = FontFamily(
                stack=fam_stack[hf],
                generic="display",
                usage_count=heading_fams[hf],
                confidence=confidence(heading_fams[hf], 0.9, n0=8),
                evidence=evidence_sample([e for e in fam_elems[hf] if e.tag in _HEADING_TAGS]),
                note=None if hf.lower() in OPEN_FONTS else "Verify font license before reuse.",
            )
            if hf.lower() not in OPEN_FONTS:
                brand_notes.append(f"Display font '{hf}' may be proprietary; verify license.")

    # Scale --------------------------------------------------------------------------------------
    size_count: Counter = Counter()
    size_elems: dict[float, list[ElementObservation]] = defaultdict(list)
    for e in texts:
        s = round(e.style.font_size * 2) / 2
        size_count[s] += 1
        size_elems[s].append(e)
    total = sum(size_count.values())
    # body = mode among paragraph-like text, else overall mode
    para = [e for e in texts if e.text_length >= 40 and e.tag not in _HEADING_TAGS]
    body_size = mode([round(e.style.font_size * 2) / 2 for e in para]) if para else None
    if body_size is None:
        body_size = size_count.most_common(1)[0][0]
    kept = [s for s, n in size_count.items() if n >= max(2, 0.015 * total) or s == body_size]
    kept = sorted(set(kept))
    below = [s for s in kept if s < body_size][-3:]
    above = [s for s in kept if s > body_size][:7]
    ordered = below + [body_size] + above
    base_idx = TYPE_SCALE_KEYS.index("base")
    start = base_idx - len(below)
    keys = TYPE_SCALE_KEYS[start : start + len(ordered)]
    on_scale = 0
    for key, size in zip(keys, ordered, strict=True):
        elems = size_elems[size]
        on_scale += len(elems)
        lh_ratios = [
            round((e.style.line_height / e.style.font_size) / 0.05) * 0.05
            for e in elems
            if e.style.line_height and e.style.font_size
        ]
        weights = Counter(e.style.font_weight for e in elems)
        ws = [w for w, n in weights.most_common() if n >= max(1, 0.1 * len(elems))]
        tracking = [
            round((e.style.letter_spacing / e.style.font_size) / 0.005) * 0.005 for e in elems if e.style.font_size
        ]
        roles = Counter()
        for e in elems:
            if e.tag in _HEADING_TAGS:
                roles[e.tag] += 1
            elif e.role in ("button", "link", "textbox", "listitem", "cell", "paragraph", "label"):
                roles[e.role] += 1
        role_names = [r for r, _ in roles.most_common(3)]
        if key == "base":
            role_names = ["body"] + [r for r in role_names if r != "paragraph"]
        typo.scale[key] = TypeStep(
            size=size,
            line_height=round(mode(lh_ratios), 2) if lh_ratios else unknown("line-height: normal"),
            weights=sorted(ws),
            letter_spacing=round(mode(tracking), 3) if tracking else unknown(),
            roles=role_names,
            usage_count=len(elems),
            confidence=confidence(len(elems), 1.0, n0=12),
            evidence=evidence_sample(elems),
        )
    typo.body = "base"
    all_weights = Counter(e.style.font_weight for e in texts)
    typo.weights = sorted(w for w, n in all_weights.items() if n >= max(2, 0.02 * total))

    headings = [e for e in texts if e.tag in {"h1", "h2", "h3"}]
    if headings:
        typo.heading_weight = mode([e.style.font_weight for e in headings])
        # tracking is a display-heading trait; h3s are often body-sized and untracked
        display = [e for e in headings if e.tag in {"h1", "h2"}] or headings
        tr = [round((e.style.letter_spacing / e.style.font_size) / 0.005) * 0.005 for e in display if e.style.font_size]
        typo.heading_tracking = round(mode(tr), 3) if tr else unknown()
    else:
        unknowns.append("typography: no h1–h3 headings observed")

    typo.confidence = confidence(total, on_scale / total if total else 0)
    typo.evidence = evidence_sample(texts, 10)
    return typo, brand_notes, unknowns
