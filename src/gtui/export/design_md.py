"""Render design.md — the profile in prose, written for a coding agent to read and apply."""

from __future__ import annotations

from gtui.export.theme import shadcn_variables
from gtui.ir.mapping import COLOR_ROLES_ORDER, tailwind_color_var
from gtui.ir.schema import AestheticProfile, ComponentRecipe, is_unknown


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, dict):
        return ", ".join(f"{k} {_fmt(x)}" for k, x in v.items())
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, list):
        return ", ".join(_fmt(x) for x in v)
    return str(v)


def _recipe_block(r: ComponentRecipe) -> str:
    p = dict(r.properties)
    p.pop("elevation_mix", None)
    lines = [f"**{r.kind} / {r.variant}** — {r.description or ''} _(n={r.sample_count}, conf {r.confidence:.2f})_", ""]
    for k, v in p.items():
        if v in (None, "none") and k not in ("background", "border", "shadow"):
            continue
        lines.append(f"- {k}: {_fmt(v)}")
    for state, delta in r.states.items():
        lines.append(f"- **:{state}** → {delta.description or _fmt(delta.changes)} _(n={delta.sample_count})_")
    return "\n".join(lines)


def render_design_md(profile: AestheticProfile) -> str:
    m, t, ch = profile.metadata, profile.tokens, profile.character
    out: list[str] = []
    out.append(f"# {m.name} — design language\n")
    out.append(
        f"Source: {m.source}  \nCaptured: {m.captured_at:%Y-%m-%d} · gtui {m.gtui_version} · schema {profile.schema_version}  "
    )
    cov = profile.coverage
    out.append(
        f"Coverage: {cov.pages} pages · {cov.elements} elements · {cov.state_observations} state observations "
        f"({', '.join(cov.states) or 'none'}) · viewports {', '.join(cov.viewports)}\n"
    )
    out.append(
        "> This document was derived from measured observations. Confidence values are coverage-based "
        "heuristics, not calibrated probabilities. Anything marked *unknown* was not observed — do not invent it.\n"
    )

    # Character --------------------------------------------------------------------------------
    out.append("## Character\n")
    for k in ("color_scheme", "density", "contrast", "depth", "ornamentation", "geometry"):
        v = getattr(ch, k)
        out.append(f"- **{k.replace('_', ' ')}**: {'unknown' if is_unknown(v) else v}")
    if not is_unknown(profile.composition.hierarchy):
        out.append(f"- **hierarchy**: {profile.composition.hierarchy}")
    if not is_unknown(profile.composition.max_content_width):
        out.append(f"- **max content width**: {profile.composition.max_content_width}px")
    if profile.composition.layout_primitives:
        out.append(f"- **layout**: {_fmt({k: f'{v:.0%}' for k, v in profile.composition.layout_primitives.items()})}")
    out.append("")

    # Principles -------------------------------------------------------------------------------
    if profile.principles:
        out.append("## Principles\n")
        for p in profile.principles:
            tag = {"invariant": "always", "variant": "context", "exception": "do not generalize"}[p.kind]
            out.append(f"- **{p.statement}** _({tag}; conf {p.confidence:.2f}; evidence {len(p.evidence)} obs)_")
            if p.rationale:
                out.append(f"  - {p.rationale}")
        out.append("")

    # Colors -----------------------------------------------------------------------------------
    out.append("## Colors\n")
    out.append("| role | value | contrast vs base | usage | conf | source names | tailwind var | shadcn |")
    out.append("|---|---|---|---|---|---|---|---|")
    sh = shadcn_variables(profile)
    inv = {}
    for name, role in sh.items():
        inv.setdefault(role, []).append(name)
    roles = sorted(t.colors, key=lambda r: COLOR_ROLES_ORDER.index(r) if r in COLOR_ROLES_ORDER else 99)
    for role in roles:
        tok = t.colors[role]
        out.append(
            f"| `{role}` | `{tok.value}` | {tok.contrast_on_base or '—'} | {tok.usage_count} | {tok.confidence:.2f} | "
            f"{', '.join(f'`{s}`' for s in tok.source_names) or '—'} | `{tailwind_color_var(role)}` | "
            f"{', '.join(f'`--{n}`' for n in inv.get(role, [])) or '—'} |"
        )
    notes = [f"- {r}: {tok.note}" for r, tok in t.colors.items() if tok.note]
    if notes:
        out.append("")
        out += notes
    out.append("")

    # Typography -------------------------------------------------------------------------------
    out.append("## Typography\n")
    for name, fam in t.typography.families.items():
        if is_unknown(fam):
            out.append(f"- **{name}**: unknown ({fam.reason})")  # type: ignore[union-attr]
        else:
            out.append(f"- **{name}**: {', '.join(fam.stack[:4])}" + (f" — _{fam.note}_" if fam.note else ""))  # type: ignore[union-attr]
    out.append("")
    out.append("| step | px | line-height | weights | tracking | roles | n |")
    out.append("|---|---|---|---|---|---|---|")
    for key, s in t.typography.scale.items():
        lh = "—" if is_unknown(s.line_height) else f"{s.line_height:g}"
        tr = "—" if is_unknown(s.letter_spacing) else f"{s.letter_spacing:+.3f}em"
        out.append(
            f"| {key}{' (body)' if key == 'base' else ''} | {s.size:g} | {lh} | {', '.join(map(str, s.weights))} | {tr} | {', '.join(s.roles)} | {s.usage_count} |"
        )
    if not is_unknown(t.typography.heading_weight):
        tr = t.typography.heading_tracking
        out.append(
            f"\nHeadings: weight {t.typography.heading_weight}" + ("" if is_unknown(tr) else f", tracking {tr:+.3f}em")
        )
    out.append("")

    # Spacing / radius / shadows / borders / motion ---------------------------------------------
    out.append("## Spacing, shape, depth, motion\n")
    sp = t.spacing
    if is_unknown(sp.base):
        out.append(f"- **spacing**: unknown ({sp.base.reason})")  # type: ignore[union-attr]
    else:
        out.append(
            f"- **spacing**: {sp.base}px grid ({sp.grid_adherence:.0%} of {sp.usage_count} values on grid); scale {', '.join(map(str, sp.scale))}"
        )
    if t.radius:
        out.append(
            "- **radius**: "
            + ", ".join(
                f"{k} {('pill' if k == 'full' else f'{v.value:g}px')} (n={v.usage_count})" for k, v in t.radius.items()
            )
        )
    else:
        out.append("- **radius**: unknown (no surfaced elements with radius observed)")
    if t.shadows:
        out.append("- **shadows**:")
        for k, v in t.shadows.items():
            out.append(f"  - {k} (blur {v.blur:g}px, n={v.usage_count}): `{v.value}`")
    else:
        out.append("- **shadows**: none observed")
    b = t.borders
    if not is_unknown(b.width):
        out.append(f"- **borders**: {b.width:g}px, color `{b.color_role}`")
    mo = t.motion
    if is_unknown(mo.durations):
        out.append(f"- **motion**: unknown ({mo.durations.reason})")  # type: ignore[union-attr]
    else:
        out.append(
            f"- **motion**: {_fmt({k: f'{v}ms' for k, v in mo.durations.items()})}; easing {', '.join(mo.easings) if not is_unknown(mo.easings) else '—'}; "  # type: ignore[union-attr]
            f"transitions on {', '.join(mo.properties) or '—'}"
        )
    out.append("")

    # Components -------------------------------------------------------------------------------
    if profile.components:
        out.append("## Component recipes\n")
        out.append(
            "Values reference token roles above (`accent.primary`, `sm`, `md`…). Raw values appear where no token matched.\n"
        )
        for kind in ("button", "input", "card", "nav_item", "link", "badge", "heading"):
            rs = profile.recipes(kind)  # type: ignore[arg-type]
            for r in rs:
                out.append(_recipe_block(r))
                out.append("")

    # How to apply -----------------------------------------------------------------------------
    out.append("## How to apply this profile\n")
    out.append(
        "1. **Tokens first.** Map the color roles onto your theme variables (shadcn column above, or `exports/tailwind.css`). "
        "Do not introduce colors outside the palette; derive hover/active states the way the recipes describe."
    )
    out.append("2. **Type.** Adopt the scale exactly; body = `base`. Keep heading weight/tracking as specified.")
    out.append(
        "3. **Spacing & shape.** Only use values from the spacing scale; use the dominant radius for controls and cards."
    )
    out.append(
        "4. **Components.** Restyle your existing components to match the recipes — do not replace them. Keep your "
        "layout, information architecture, copy, logic and accessibility semantics unchanged."
    )
    out.append(
        "5. **Respect the principles** — especially accent restraint and the elevation strategy; they matter more than any single value."
    )
    out.append("6. **Never copy** " + "; ".join(profile.brand.excluded) + ".")
    out.append("")

    if profile.brand.notes:
        out.append("## Brand / licensing notes\n")
        out += [f"- {n}" for n in profile.brand.notes]
        out.append("")
    if profile.unknowns:
        out.append("## Unknowns (not observed — do not invent)\n")
        out += [f"- {u}" for u in profile.unknowns]
        out.append("")
    out.append("## Confidence by section\n")
    out.append(", ".join(f"{k} {v:.2f}" for k, v in profile.confidence.items()))
    out.append("")
    return "\n".join(out)
