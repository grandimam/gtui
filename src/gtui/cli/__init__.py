"""gtui command-line interface."""

from __future__ import annotations

import asyncio
import json
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from gtui import __version__
from gtui.cli.render import print_inspect, print_report
from gtui.core.config import slugify
from gtui.storage.profiles import ProfileStore

app = typer.Typer(
    name="gtui",
    help="Design intelligence engine — capture a site's design language, make it portable, let agents apply it.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()
err = Console(stderr=True)


def _version(value: bool) -> None:
    if value:
        console.print(f"gtui {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True, help="Show version")] = False,
) -> None:
    pass


# --- capture ---------------------------------------------------------------------------------------


@app.command()
def capture(
    url: Annotated[str, typer.Argument(help="Site to capture (https://… or localhost:3000)")],
    name: Annotated[str | None, typer.Option("--name", "-n", help="Profile name (default: derived from host)")] = None,
    pages: Annotated[int, typer.Option("--pages", "-p", help="Max pages to visit")] = 6,
    viewport: Annotated[
        list[str], typer.Option("--viewport", "-v", help="WxH; repeat for several (first is primary)")
    ] = ["1440x900"],  # noqa: B006
    responsive: Annotated[bool, typer.Option("--responsive", help="Also capture 390x844 for the entry page")] = False,
    state: Annotated[
        list[str], typer.Option("--state", help="Pseudo states to force (hover, focus-visible, active)")
    ] = ["hover", "focus-visible"],  # noqa: B006
    connect: Annotated[
        str | None,
        typer.Option(
            "--connect",
            help="Attach to your own Chrome, e.g. localhost:9222 (start it with --remote-debugging-port=9222)",
        ),
    ] = None,
    headed: Annotated[bool, typer.Option("--headed", help="Show the browser")] = False,
    scheme: Annotated[str | None, typer.Option("--scheme", help="Force prefers-color-scheme: light|dark")] = None,
    allow: Annotated[list[str], typer.Option("--allow", help="Regex; only follow matching URLs")] = [],  # noqa: B006
    deny: Annotated[list[str], typer.Option("--deny", help="Regex; never follow matching URLs")] = [],  # noqa: B006
    storage_state: Annotated[
        str | None,
        typer.Option("--storage-state", help="Playwright storage state JSON (cookies) for authenticated captures"),
    ] = None,
    extract_after: Annotated[
        bool, typer.Option("--extract/--no-extract", help="Run extract right after capture")
    ] = True,
) -> None:
    """Explore a site and record screenshots, DOM, computed styles and interaction states."""
    from gtui.api import capture as _capture

    store = ProfileStore.default()
    name = name or slugify(url)
    vps = list(viewport)
    if responsive and "390x844" not in vps:
        vps.append("390x844")
    console.print(f"[bold]gtui capture[/] {url} → profile [cyan]{name}[/]  (pages≤{pages}, viewports {', '.join(vps)})")
    if connect:
        console.print(f"[dim]attaching to your browser at {connect} — your session, your cookies; gtui only reads.[/]")

    def progress(msg: str) -> None:
        console.print(f"  [dim]{msg}[/]")

    try:
        obs = asyncio.run(
            _capture(
                url,
                name=name,
                max_pages=pages,
                viewports=vps,
                states=list(state),
                connect=connect,
                headless=not headed,
                color_scheme=scheme,
                allow=list(allow),
                deny=list(deny),
                storage_state=storage_state,
                store=store,
                progress=progress,
            )
        )
    except Exception as exc:  # pragma: no cover - surfaced to user
        msg = str(exc)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            err.print(
                "[red]Chromium is not installed for Playwright.[/] Run: [bold]uv run playwright install chromium[/]"
            )
            raise typer.Exit(2) from exc
        err.print(f"[red]capture failed:[/] {msg}")
        raise typer.Exit(1) from exc
    s = obs.summary()
    console.print(
        f"[green]✓[/] captured {s['pages']} pages, {s['elements']} elements, {s['state_observations']} state observations"
        f" → {store.capture_dir(name)}"
    )
    if obs.skipped:
        console.print(
            f"  [dim]skipped {len(obs.skipped)}: "
            + "; ".join(f"{x['url']} ({x['reason']})" for x in obs.skipped[:4])
            + "[/]"
        )
    if s["pages"] == 0:
        err.print("[red]nothing captured[/]")
        raise typer.Exit(1)
    if extract_after:
        _do_extract(name, store, with_evidence=False, quiet=False)


# --- extract ---------------------------------------------------------------------------------------


def _do_extract(
    name: str,
    store: ProfileStore,
    *,
    with_evidence: bool,
    quiet: bool,
    license: str | None = None,
    attribution: str | None = None,
) -> None:
    from gtui.api import extract as _extract
    from gtui.export import write_profile_bundle

    obs = store.load_capture(name)
    profile = _extract(obs, license=license, attribution=attribution)
    written = write_profile_bundle(profile, store.profile_dir(name))
    if with_evidence:
        store.copy_evidence(name)
    if not quiet:
        console.print(f"[green]✓[/] profile [cyan]{name}[/] → {store.profile_dir(name)}")
        console.print("  " + ", ".join(sorted(written)))
        conf = ", ".join(f"{k} {v:.2f}" for k, v in profile.confidence.items())
        console.print(f"  [dim]confidence: {conf}[/]")
        if profile.unknowns:
            console.print(f"  [dim]unknowns: {len(profile.unknowns)} (see design.md)[/]")
        console.print(
            f"  next: [bold]gtui inspect {name}[/] · [bold]gtui preview {name}[/] · [bold]gtui apply {name} --target ./my-app[/]"
        )


@app.command()
def extract(
    name: Annotated[str, typer.Argument(help="Capture/profile name")],
    with_evidence: Annotated[bool, typer.Option("--with-evidence", help="Copy screenshots into the profile")] = False,
    license: Annotated[str | None, typer.Option("--license", help="License to record on the profile")] = None,
    attribution: Annotated[str | None, typer.Option("--attribution", help="Attribution to record")] = None,
) -> None:
    """Infer tokens, component recipes and principles from a capture; write the profile bundle."""
    store = ProfileStore.default()
    try:
        _do_extract(name, store, with_evidence=with_evidence, quiet=False, license=license, attribution=attribution)
    except FileNotFoundError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc


# --- inspect / list / preview / export -------------------------------------------------------------


@app.command()
def inspect(
    name: Annotated[str, typer.Argument(help="Profile name or path to aesthetic.json")],
    as_json: Annotated[bool, typer.Option("--json", help="Print the raw profile JSON")] = False,
) -> None:
    """Show a profile: palette, type scale, spacing, components, principles, confidence."""
    from gtui.api import load_profile

    try:
        profile = load_profile(name)
    except FileNotFoundError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if as_json:
        console.print_json(profile.model_dump_json())
        return
    print_inspect(console, profile)


@app.command("list")
def list_profiles() -> None:
    """List local profiles and captures."""
    store = ProfileStore.default()
    profiles = store.list_profiles()
    captures = store.list_captures()
    if not profiles and not captures:
        console.print(f"no profiles yet in {store.paths.home}. Start with: [bold]gtui capture https://example.com[/]")
        return
    table = Table(title=f"profiles · {store.paths.profiles}")
    table.add_column("name", style="cyan")
    table.add_column("source")
    table.add_column("captured")
    table.add_column("pages", justify="right")
    table.add_column("elements", justify="right")
    table.add_column("confidence")
    for m in profiles:
        cov = m.get("coverage", {})
        conf = m.get("confidence", {})
        table.add_row(
            m.get("name", "?"),
            m.get("source", ""),
            (m.get("captured_at") or "")[:10],
            str(cov.get("pages", "")),
            str(cov.get("elements", "")),
            " ".join(f"{k[:4]} {v:.1f}" for k, v in list(conf.items())[:4]),
        )
    console.print(table)
    unextracted = [c for c in captures if not store.has_profile(c)]
    if unextracted:
        console.print(f"[dim]captures without a profile: {', '.join(unextracted)} → gtui extract <name>[/]")


@app.command()
def export(
    name: Annotated[str, typer.Argument(help="Profile name")],
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="css | tailwind | shadcn | dtcg | preview | design-md")
    ] = "tailwind",
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write to file instead of stdout")] = None,
) -> None:
    """Export a profile to a target vocabulary."""
    from gtui.api import load_profile
    from gtui.export import render

    try:
        text = render(load_profile(name), fmt)
    except (FileNotFoundError, ValueError) as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console.print(f"[green]✓[/] wrote {out}")
    else:
        print(text)


@app.command()
def preview(
    name: Annotated[str, typer.Argument(help="Profile name")],
    open_browser: Annotated[bool, typer.Option("--open/--no-open", help="Open in the default browser")] = True,
) -> None:
    """Render the profile's tokens and recipes as a standalone kitchen-sink page."""
    from gtui.api import load_profile
    from gtui.export import render

    store = ProfileStore.default()
    try:
        profile = load_profile(name)
    except FileNotFoundError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    path = store.profile_dir(name) / "exports" / "preview.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(profile, "preview"), encoding="utf-8")
    console.print(f"[green]✓[/] {path}")
    if open_browser:
        webbrowser.open(path.as_uri())


# --- apply / evaluate ------------------------------------------------------------------------------


@app.command()
def apply(
    name: Annotated[str, typer.Argument(help="Profile name")],
    target: Annotated[Path, typer.Option("--target", "-t", help="Target application directory")] = Path("."),
    print_prompt: Annotated[bool, typer.Option("--prompt/--no-prompt", help="Print the agent prompt")] = True,
) -> None:
    """Analyze a target app and write a hand-off bundle (plan + theme in its dialect) for your coding agent.

    gtui does not edit application code; your agent does, following .gtui/<profile>/transfer-plan.json.
    """
    from gtui.api import load_profile
    from gtui.transfer.analyzer import analyze_target
    from gtui.transfer.planner import agent_prompt, write_handoff

    try:
        profile = load_profile(name)
    except FileNotFoundError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if not target.is_dir():
        err.print(f"[red]target {target} is not a directory[/]")
        raise typer.Exit(1)
    analysis = analyze_target(target)
    bundle = write_handoff(profile, analysis)
    console.print(f"[bold]target[/] {analysis.root}")
    console.print(
        f"  framework [cyan]{analysis.framework}[/] · styling [cyan]{analysis.styling}[/]"
        + (f" · tailwind {analysis.tailwind_version}" if analysis.tailwind_version else "")
        + (f" · theme files {', '.join(analysis.theme_files[:3])}" if analysis.theme_files else "")
    )
    for n in analysis.notes:
        console.print(f"  [yellow]note[/] {n}")
    plan = json.loads((bundle / "transfer-plan.json").read_text())
    table = Table(title="transfer plan", show_lines=False)
    table.add_column("#", justify="right")
    table.add_column("type")
    table.add_column("scope")
    table.add_column("risk")
    table.add_column("action")
    for c in plan["changes"]:
        risk_style = {"low": "green", "medium": "yellow", "high": "red"}[c["risk"]]
        table.add_row(
            str(c["step"]),
            c["type"],
            c["scope"],
            f"[{risk_style}]{c['risk']}[/]",
            c["action"][:110] + ("…" if len(c["action"]) > 110 else ""),
        )
    console.print(table)
    console.print(f"[green]✓[/] hand-off bundle → {bundle}")
    if print_prompt:
        console.rule("[dim]prompt for your coding agent[/]")
        print(agent_prompt(profile, analysis, Path(".gtui") / name))


@app.command()
def evaluate(
    name: Annotated[str, typer.Argument(help="Profile name")],
    url: Annotated[str, typer.Option("--url", "-u", help="Running target app, e.g. http://localhost:3000")],
    pages: Annotated[int, typer.Option("--pages", "-p")] = 3,
    connect: Annotated[str | None, typer.Option("--connect", help="Attach to your own Chrome")] = None,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write JSON report")] = None,
) -> None:
    """Capture the target app and score its compliance with the profile (deterministic checks)."""
    from gtui.api import capture as _capture
    from gtui.api import evaluate as _evaluate
    from gtui.api import load_profile

    store = ProfileStore.default()
    try:
        profile = load_profile(name)
    except FileNotFoundError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"[bold]gtui evaluate[/] {url} against [cyan]{name}[/]")
    target_obs = asyncio.run(
        _capture(
            url,
            name=f"_eval_{name}",
            max_pages=pages,
            connect=connect,
            states=[],
            store=store,
            save=False,
            progress=lambda m: console.print(f"  [dim]{m}[/]"),
        )
    )
    if not target_obs.defaults():
        err.print("[red]nothing rendered at the target url[/]")
        raise typer.Exit(1)
    report = _evaluate(profile, target_obs)
    print_report(console, report)
    out = out or store.profile_dir(name) / "evaluations" / f"{report.evaluated_at:%Y%m%dT%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"[dim]report → {out}[/]")


if __name__ == "__main__":  # pragma: no cover
    app()
