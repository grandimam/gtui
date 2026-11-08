"""Target analysis: what framework / styling dialect does the target app speak?

gtui never edits the target. It detects the dialect so the hand-off bundle is written in the
target's own vocabulary (shadcn vars, Tailwind v4 @theme, Tailwind v3 config, plain CSS vars).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", ".turbo", "out", "coverage", ".gtui"}


@dataclass
class TargetAnalysis:
    root: Path
    framework: str = "unknown"  # next | vite-react | react | remix | astro | unknown
    styling: str = "css"  # shadcn | tailwind-v4 | tailwind-v3 | css-modules | css
    tailwind_version: str | None = None
    theme_files: list[str] = field(default_factory=list)  # css files declaring tokens
    tailwind_config: str | None = None
    components_dir: str | None = None
    ui_dir: str | None = None
    existing_vars: dict[str, str] = field(default_factory=dict)
    test_command: str | None = None
    dev_command: str | None = None
    package_manager: str = "npm"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["root"] = str(self.root)
        return d


def _iter_files(root: Path, suffixes: tuple[str, ...], limit: int = 4000):
    n = 0
    for p in root.rglob("*"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix in suffixes:
            yield p
            n += 1
            if n >= limit:
                return


def analyze_target(root: Path) -> TargetAnalysis:
    root = root.resolve()
    a = TargetAnalysis(root=root)
    pkg_path = root / "package.json"
    deps: dict[str, str] = {}
    scripts: dict[str, str] = {}
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            scripts = pkg.get("scripts", {}) or {}
        except json.JSONDecodeError:
            a.notes.append("package.json is not valid JSON")
    else:
        a.notes.append("no package.json found — is this a web project?")

    if (root / "pnpm-lock.yaml").exists():
        a.package_manager = "pnpm"
    elif (root / "yarn.lock").exists():
        a.package_manager = "yarn"
    elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        a.package_manager = "bun"
    if "next" in deps:
        a.framework = "next"
    elif "@remix-run/react" in deps:
        a.framework = "remix"
    elif "astro" in deps:
        a.framework = "astro"
    elif "react" in deps and "vite" in deps:
        a.framework = "vite-react"
    elif "react" in deps:
        a.framework = "react"
    run = {"npm": "npm run", "pnpm": "pnpm", "yarn": "yarn", "bun": "bun run"}[a.package_manager]
    if "test" in scripts:
        a.test_command = f"{run} test"
    if "dev" in scripts:
        a.dev_command = f"{run} dev"

    if "tailwindcss" in deps:
        a.tailwind_version = deps["tailwindcss"]
        major = re.search(r"\d+", deps["tailwindcss"])
        a.styling = "tailwind-v4" if major and int(major.group()) >= 4 else "tailwind-v3"
    for name in ("tailwind.config.js", "tailwind.config.ts", "tailwind.config.cjs", "tailwind.config.mjs"):
        if (root / name).exists():
            a.tailwind_config = name
            if a.styling == "css":
                a.styling = "tailwind-v3"
    if (root / "components.json").exists():
        a.styling = "shadcn"
        try:
            cj = json.loads((root / "components.json").read_text())
            css = cj.get("tailwind", {}).get("css")
            if css:
                a.theme_files.append(css)
            aliases = cj.get("aliases", {})
            a.ui_dir = aliases.get("ui") or (
                aliases.get("components", "") + "/ui" if aliases.get("components") else None
            )
        except json.JSONDecodeError:
            pass

    var_re = re.compile(r"^\s*(--[\w-]+)\s*:\s*([^;]+);", re.M)
    for css_file in _iter_files(root, (".css", ".scss")):
        try:
            text = css_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        has_theme = "@theme" in text
        has_root_vars = ":root" in text and "--" in text
        if has_theme or has_root_vars or '@import "tailwindcss"' in text or "@import 'tailwindcss'" in text:
            rel = str(css_file.relative_to(root))
            if rel not in a.theme_files:
                a.theme_files.append(rel)
            if has_theme and a.styling in ("css", "tailwind-v3"):
                a.styling = "tailwind-v4"
            for m in var_re.finditer(text):
                if len(a.existing_vars) < 200:
                    a.existing_vars.setdefault(m.group(1), m.group(2).strip())
        if ".module." in css_file.name and a.styling == "css":
            a.styling = "css-modules"
    if {"--background", "--foreground"} <= set(a.existing_vars) and a.styling != "shadcn":
        a.styling = "shadcn"
        a.notes.append("shadcn-style variables detected without components.json")

    for cand in ("src/components", "components", "app/components", "src/app/components"):
        if (root / cand).is_dir():
            a.components_dir = cand
            if a.ui_dir is None and (root / cand / "ui").is_dir():
                a.ui_dir = f"{cand}/ui"
            break
    return a
