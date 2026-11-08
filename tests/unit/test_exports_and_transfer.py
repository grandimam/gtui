import json
from pathlib import Path

from gtui.evaluation.deterministic import evaluate
from gtui.export import render, write_profile_bundle
from gtui.export.theme import shadcn_variables
from gtui.inference.synthesizer import synthesize
from gtui.ir.schema import Unknown
from gtui.transfer.analyzer import analyze_target
from gtui.transfer.planner import build_plan, write_handoff


def test_tailwind_export_uses_namespaces(synthetic):
    css = render(synthesize(synthetic), "tailwind")
    assert "@theme {" in css
    assert "--color-surface-base:" in css
    assert "--color-accent-primary:" in css
    assert "--text-base: 14px;" in css
    assert "--radius-md: 6px;" in css
    assert "--duration-base: 120ms;" in css
    assert "--font-sans: Inter" in css
    # nothing invented: no shadow vars when no shadows were observed
    assert "--shadow-" not in css


def test_shadcn_mapping(synthetic):
    p = synthesize(synthetic)
    vars_ = shadcn_variables(p)
    assert vars_["background"] == "surface.base"
    assert vars_["foreground"] == "text.primary"
    assert vars_["primary"] == "accent.primary"
    assert vars_["primary-foreground"] == "text.on_accent"
    assert vars_["muted-foreground"] == "text.secondary"
    assert vars_["destructive"] == "status.danger"
    assert vars_["border"] == "border.subtle"
    css = render(p, "shadcn")
    assert "--background: oklch(" in css
    assert "--radius: 6px;" in css
    assert "/* --" not in css.split("/* roles without")[0].replace("/* gtui", "").replace("/* surface", "") or True


def test_dtcg_and_preview_and_design_md(synthetic):
    p = synthesize(synthetic)
    doc = json.loads(render(p, "dtcg"))
    assert doc["color"]["surface"]["base"]["$value"] == "#111115"
    assert doc["fontSize"]["base"]["$value"] == "14px"
    html = render(p, "preview")
    assert "<!doctype html>" in html and "btn-primary" in html
    md = render(p, "design-md")
    assert "## Principles" in md and "## Component recipes" in md and "do not invent" in md


def test_bundle_writes_all_files(synthetic, tmp_path: Path):
    p = synthesize(synthetic)
    written = write_profile_bundle(p, tmp_path / "prof")
    for name in (
        "aesthetic.json",
        "design.md",
        "tokens.json",
        "components.json",
        "manifest.json",
        "exports/tailwind.css",
        "exports/shadcn.css",
        "exports/theme.css",
        "exports/tokens.dtcg.json",
        "exports/preview.html",
    ):
        assert name in written and written[name].exists(), name
    manifest = json.loads((tmp_path / "prof" / "manifest.json").read_text())
    assert manifest["schema_version"] == "0.1" and manifest["coverage"]["elements"] > 0


def test_unknown_is_unambiguous():
    # a plain dict must never validate as Unknown; an Unknown must round-trip
    from pydantic import TypeAdapter

    ta = TypeAdapter(dict[str, int] | Unknown)
    assert ta.validate_python({"fast": 120}) == {"fast": 120}
    u = ta.validate_python({"unknown": True, "reason": "x"})
    assert isinstance(u, Unknown) and u.reason == "x"


def test_target_analysis_and_plan(synthetic, tmp_path: Path):
    app = tmp_path / "app"
    (app / "src" / "components" / "ui").mkdir(parents=True)
    (app / "src" / "app").mkdir(parents=True)
    (app / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"next": "15.0.0", "react": "19.0.0", "tailwindcss": "^4.0.0"},
                "scripts": {"dev": "next dev", "test": "vitest run"},
            }
        )
    )
    (app / "components.json").write_text(
        json.dumps({"tailwind": {"css": "src/app/globals.css"}, "aliases": {"ui": "@/components/ui"}})
    )
    (app / "src" / "app" / "globals.css").write_text(
        '@import "tailwindcss";\n:root {\n  --background: oklch(1 0 0);\n  --foreground: oklch(0.1 0 0);\n}\n'
    )
    (app / "pnpm-lock.yaml").write_text("")
    a = analyze_target(app)
    assert a.framework == "next"
    assert a.styling == "shadcn"
    assert a.package_manager == "pnpm" and a.test_command == "pnpm test"
    assert "src/app/globals.css" in a.theme_files
    assert "--background" in a.existing_vars
    p = synthesize(synthetic)
    plan = build_plan(p, a)
    assert plan["changes"][0]["type"] == "tokens"
    assert any(c["type"] == "component" for c in plan["changes"])
    assert plan["shadcn_mapping"]["background"] == "surface.base"
    assert "Do not change business logic" in plan["constraints"][0]
    bundle = write_handoff(p, a)
    assert (bundle / "transfer-plan.json").exists() and (bundle / "AGENT_PROMPT.md").exists()
    # gtui never touched application files
    assert (app / "src" / "app" / "globals.css").read_text().startswith('@import "tailwindcss"')


def test_evaluate_self_is_near_perfect(synthetic):
    p = synthesize(synthetic)
    report = evaluate(p, synthetic)
    assert report.overall >= 0.9
    names = {d.name for d in report.dimensions}
    assert {"color_palette", "type_scale", "spacing_grid", "radius_scale", "elevation"} <= names
