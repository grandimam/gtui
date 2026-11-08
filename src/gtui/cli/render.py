"""Rich rendering for `inspect` and `evaluate`."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gtui.evaluation.deterministic import EvaluationReport
from gtui.ir.mapping import COLOR_ROLES_ORDER
from gtui.ir.schema import AestheticProfile, is_unknown


def _conf(v: float) -> str:
    color = "green" if v >= 0.75 else ("yellow" if v >= 0.45 else "red")
    return f"[{color}]{v:.2f}[/]"


def print_inspect(console: Console, p: AestheticProfile) -> None:
    m, t, ch = p.metadata, p.tokens, p.character
    header = Text.assemble((m.name, "bold cyan"), ("  ", ""), (m.source, "dim"))
    cov = p.coverage
    body = (
        f"{ch.summary or 'character: unknown'}\n"
        f"[dim]captured {m.captured_at:%Y-%m-%d} · {cov.pages} pages · {cov.elements} elements · "
        f"{cov.state_observations} state obs · viewports {', '.join(cov.viewports)}[/]"
    )
    console.print(Panel(body, title=header, title_align="left"))

    # Palette
    table = Table(title="palette", show_edge=False, pad_edge=False)
    table.add_column("")
    table.add_column("role", style="bold")
    table.add_column("value")
    table.add_column("contrast", justify="right")
    table.add_column("n", justify="right")
    table.add_column("conf", justify="right")
    table.add_column("source name", style="dim")
    roles = sorted(t.colors, key=lambda r: COLOR_ROLES_ORDER.index(r) if r in COLOR_ROLES_ORDER else 99)
    for role in roles:
        tok = t.colors[role]
        swatch = Text("      ", style=f"on {tok.value[:7]}")
        table.add_row(
            swatch,
            role,
            tok.value,
            f"{tok.contrast_on_base:.1f}" if tok.contrast_on_base else "—",
            str(tok.usage_count),
            _conf(tok.confidence),
            tok.source_names[0] if tok.source_names else "",
        )
    console.print(table)

    # Typography
    fams = []
    for k, f in t.typography.families.items():
        fams.append(f"{k}: " + ("unknown" if is_unknown(f) else ", ".join(f.stack[:3])))  # type: ignore[union-attr]
    table = Table(title="typography — " + " · ".join(fams), show_edge=False, pad_edge=False)
    for col in ("step", "px", "line-height", "weights", "tracking", "roles", "n"):
        table.add_column(col, justify="right" if col in ("px", "n") else "left")
    for key, s in t.typography.scale.items():
        table.add_row(
            key + (" ●" if key == "base" else ""),
            f"{s.size:g}",
            "—" if is_unknown(s.line_height) else f"{s.line_height:g}",
            ", ".join(map(str, s.weights)),
            "—" if is_unknown(s.letter_spacing) else f"{s.letter_spacing:+.3f}em",
            ", ".join(s.roles),
            str(s.usage_count),
        )
    console.print(table)

    # Spacing / radius / shadows / motion
    sp = t.spacing
    lines = []
    if is_unknown(sp.base):
        lines.append(f"spacing   unknown — {sp.base.reason}")  # type: ignore[union-attr]
    else:
        lines.append(
            f"spacing   {sp.base}px grid ({sp.grid_adherence:.0%} adherence, n={sp.usage_count}) · {', '.join(map(str, sp.scale))}"
        )
    lines.append(
        "radius    "
        + (
            ", ".join(
                f"{k}={'pill' if k == 'full' else f'{v.value:g}px'}({v.usage_count})" for k, v in t.radius.items()
            )
            or "none observed"
        )
    )
    lines.append(
        "shadows   "
        + (", ".join(f"{k} blur {v.blur:g}px ({v.usage_count})" for k, v in t.shadows.items()) or "none observed")
    )
    b = t.borders
    lines.append("borders   " + ("unknown" if is_unknown(b.width) else f"{b.width:g}px {b.color_role}"))
    mo = t.motion
    lines.append(
        "motion    "
        + (
            f"unknown — {mo.durations.reason}"
            if is_unknown(mo.durations)  # type: ignore[union-attr]
            else ", ".join(f"{k} {v}ms" for k, v in mo.durations.items()) + "  " + ", ".join(mo.easings[:2])
        )
    )  # type: ignore[union-attr]
    comp = p.composition
    if not is_unknown(comp.max_content_width) or not is_unknown(comp.hierarchy):
        lines.append(
            "layout    "
            + (f"max width {comp.max_content_width}px · " if not is_unknown(comp.max_content_width) else "")
            + (f"hierarchy {comp.hierarchy}" if not is_unknown(comp.hierarchy) else "")
        )
    console.print(Panel("\n".join(lines), title="geometry & motion", title_align="left"))

    # Components
    if p.components:
        table = Table(title="component recipes", show_edge=False, pad_edge=False)
        for col in ("kind", "variant", "n", "conf", "recipe", "states"):
            table.add_column(col, justify="right" if col in ("n", "conf") else "left")
        for c in p.components:
            props = {k: v for k, v in c.properties.items() if k not in ("elevation_mix",) and v not in (None, "none")}
            recipe = " ".join(f"{k}={_short(v)}" for k, v in list(props.items())[:8])
            states = "; ".join(f":{s} {d.description[:50]}" for s, d in c.states.items())
            table.add_row(c.kind, c.variant, str(c.sample_count), _conf(c.confidence), recipe, states)
        console.print(table)

    # Principles
    if p.principles:
        lines = []
        for pr in p.principles:
            tag = {"invariant": "[green]always[/]", "variant": "[yellow]context[/]", "exception": "[red]exception[/]"}[
                pr.kind
            ]
            lines.append(f"{tag} {pr.statement} [dim]({_conf(pr.confidence)}, {len(pr.evidence)} obs)[/]")
        console.print(Panel("\n".join(lines), title="principles", title_align="left"))

    conf = "  ".join(f"{k} {_conf(v)}" for k, v in p.confidence.items())
    console.print(f"confidence  {conf}")
    if p.unknowns:
        console.print(
            f"[dim]unknowns ({len(p.unknowns)}): "
            + "; ".join(p.unknowns[:5])
            + ("…" if len(p.unknowns) > 5 else "")
            + "[/]"
        )


def _short(v) -> str:
    if isinstance(v, dict):
        return "{" + ",".join(f"{k}:{_short(x)}" for k, x in v.items()) + "}"
    if isinstance(v, float):
        return f"{v:g}"
    s = str(v)
    return s if len(s) <= 28 else s[:26] + "…"


def print_report(console: Console, r: EvaluationReport) -> None:
    table = Table(title=f"evaluation — overall {r.overall:.2f}", show_edge=False, pad_edge=False)
    table.add_column("dimension")
    table.add_column("score", justify="right")
    table.add_column("checked", justify="right")
    table.add_column("detail")
    table.add_column("top offenders", style="dim")
    for d in r.dimensions:
        table.add_row(
            d.name, _conf(d.score), str(d.checked), d.detail, ", ".join(str(o["value"]) for o in d.offenders[:4])
        )
    console.print(table)
    if r.recommendations:
        console.print(
            Panel(
                "\n".join(f"• {x}" for x in r.recommendations),
                title="recommendations (highest impact first)",
                title_align="left",
            )
        )
