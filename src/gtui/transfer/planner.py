"""Transfer planning: produce an ordered, scoped, risk-rated plan and a hand-off bundle that an
external coding agent (Claude Code, Codex, …) executes. gtui does not modify application code.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from gtui.export.design_md import render_design_md
from gtui.export.theme import render_css, render_shadcn, render_tailwind, shadcn_variables
from gtui.ir.schema import AestheticProfile, is_unknown
from gtui.transfer.analyzer import TargetAnalysis

CONSTRAINTS = [
    "Do not change business logic, data fetching, routing or information architecture.",
    "Do not remove or weaken accessibility semantics (roles, labels, focus order, contrast ≥ 4.5:1 for body text).",
    "Do not replace working components; restyle them to match the recipes.",
    "Do not add dependencies for styling that the project does not already use.",
    "Do not copy logos, wordmarks, imagery, icon artwork, copy or product names from the source.",
    "Use only colors from the profile palette; use only spacing values from the spacing scale.",
    "Work on a branch/worktree; keep changes reviewable; run the existing tests before finishing.",
]


def build_plan(profile: AestheticProfile, target: TargetAnalysis) -> dict:
    theme_file = (
        target.theme_files[0]
        if target.theme_files
        else ("app/globals.css" if target.framework == "next" else "src/index.css")
    )
    dialect = {"shadcn": "shadcn.css", "tailwind-v4": "tailwind.css"}.get(target.styling, "theme.css")
    changes: list[dict] = []
    changes.append(
        {
            "step": 1,
            "type": "tokens",
            "scope": "global theme",
            "risk": "low",
            "files": [theme_file],
            "action": f"Replace/merge the theme variables in {theme_file} with the values in .gtui/{profile.metadata.name}/{dialect}. "
            + (
                "Map onto the existing shadcn variables (see 'shadcn' column in design.md)."
                if target.styling == "shadcn"
                else "Keep existing variable names where they already exist; add the gtui roles otherwise."
            ),
            "verify": "App renders; page background equals surface.base; body text uses text.primary and the sans family.",
        }
    )
    if target.tailwind_config and target.styling == "tailwind-v3":
        changes.append(
            {
                "step": 2,
                "type": "tokens",
                "scope": "tailwind config",
                "risk": "low",
                "files": [target.tailwind_config],
                "action": "Extend theme.colors/fontSize/borderRadius/boxShadow in the Tailwind config from tokens.json "
                "(Tailwind v3 has no @theme; use CSS variables as values).",
                "verify": "Utilities like bg-surface-base / text-sm resolve to the new tokens.",
            }
        )
    step = len(changes) + 1
    changes.append(
        {
            "step": step,
            "type": "typography",
            "scope": "global",
            "risk": "low",
            "files": [theme_file],
            "action": "Set the base font-size/line-height from the 'base' step; set heading weight and tracking per the heading recipes; "
            "limit font sizes to the scale.",
            "verify": "No font-size outside the scale (gtui evaluate → type_scale ≥ 0.9).",
        }
    )
    step += 1
    kinds = [c.kind for c in profile.components]
    shared = []
    if "button" in kinds:
        shared.append("button")
    if "input" in kinds:
        shared.append("input")
    if "card" in kinds:
        shared.append("card")
    if "badge" in kinds:
        shared.append("badge")
    if shared:
        changes.append(
            {
                "step": step,
                "type": "component",
                "scope": ", ".join(shared),
                "risk": "medium",
                "files": [target.ui_dir or target.components_dir or "components/"],
                "action": "Restyle the shared primitives to the recipes in components.json (height, padding, radius, surface, border, "
                "hover/focus deltas). Keep props/APIs unchanged.",
                "verify": "Variants map: primary→accent surface, secondary/outline/ghost per recipe; focus ring uses border.focus.",
            }
        )
        step += 1
    if "nav_item" in kinds:
        changes.append(
            {
                "step": step,
                "type": "component",
                "scope": "navigation",
                "risk": "medium",
                "files": [target.components_dir or "components/"],
                "action": "Apply the nav_item recipe (density, weight, selected state) to sidebar/header navigation.",
                "verify": "Selected state matches the 'selected' recipe; hover delta matches.",
            }
        )
        step += 1
    changes.append(
        {
            "step": step,
            "type": "layout",
            "scope": "density & composition",
            "risk": "medium",
            "files": ["pages/screens"],
            "action": "Adjust page-level spacing to the spacing scale"
            + (
                f", max content width {profile.composition.max_content_width}px"
                if not is_unknown(profile.composition.max_content_width)
                else ""
            )
            + f"; density target: {profile.character.density if not is_unknown(profile.character.density) else 'as observed'}. "
            "Apply the elevation strategy from the card recipe to all containers.",
            "verify": "gtui evaluate → spacing_grid ≥ 0.85, elevation = 1.0.",
        }
    )
    step += 1
    changes.append(
        {
            "step": step,
            "type": "validation",
            "scope": "whole app",
            "risk": "low",
            "files": [],
            "action": (f"Run `{target.test_command}`; " if target.test_command else "Run the test suite if present; ")
            + (
                f"start `{target.dev_command}` and run `gtui evaluate {profile.metadata.name} --url http://localhost:<port>`."
                if target.dev_command
                else f"render the app and run `gtui evaluate {profile.metadata.name} --url <dev url>`."
            ),
            "verify": "All tests pass; evaluation overall ≥ 0.85; no accessibility regressions.",
        }
    )
    return {
        "profile": profile.metadata.name,
        "source": profile.metadata.source,
        "target": str(target.root),
        "target_analysis": target.to_dict(),
        "generated_at": datetime.now(UTC).isoformat(),
        "preserve": [
            "functionality",
            "information architecture",
            "routing",
            "data",
            "copy",
            "accessibility semantics",
            "tests",
        ],
        "constraints": CONSTRAINTS,
        "changes": changes,
        "shadcn_mapping": shadcn_variables(profile) if target.styling == "shadcn" else None,
        "unknowns": profile.unknowns,
    }


def agent_prompt(profile: AestheticProfile, target: TargetAnalysis, bundle_dir: Path) -> str:
    rel = bundle_dir
    return f"""Restyle this application to adopt the design language described in {rel}/design.md.

Read, in order: {rel}/design.md (the rules), {rel}/transfer-plan.json (ordered steps, constraints), {rel}/components.json (recipes).
The target speaks `{target.styling}` ({target.framework}); the theme in the target's dialect is at {rel}/{"shadcn.css" if target.styling == "shadcn" else "tailwind.css" if target.styling == "tailwind-v4" else "theme.css"}.

Follow the plan step by step. Apply tokens first, then shared components, then layout density. Preserve functionality,
information architecture, copy and accessibility. Do not copy branding or assets from the source. When done, run the tests and
`gtui evaluate {profile.metadata.name} --url <dev server url>` and fix the highest-impact mismatch it reports.
"""


def write_handoff(profile: AestheticProfile, target: TargetAnalysis) -> Path:
    bundle = target.root / ".gtui" / profile.metadata.name
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "design.md").write_text(render_design_md(profile), encoding="utf-8")
    (bundle / "aesthetic.json").write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    (bundle / "components.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in profile.components], indent=2), encoding="utf-8"
    )
    (bundle / "tokens.json").write_text(json.dumps(profile.tokens.model_dump(mode="json"), indent=2), encoding="utf-8")
    (bundle / "theme.css").write_text(render_css(profile), encoding="utf-8")
    (bundle / "tailwind.css").write_text(render_tailwind(profile), encoding="utf-8")
    (bundle / "shadcn.css").write_text(render_shadcn(profile), encoding="utf-8")
    plan = build_plan(profile, target)
    (bundle / "transfer-plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (bundle / "AGENT_PROMPT.md").write_text(
        agent_prompt(profile, target, Path(".gtui") / profile.metadata.name), encoding="utf-8"
    )
    return bundle
