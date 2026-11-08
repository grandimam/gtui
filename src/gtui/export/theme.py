"""CSS-variable exports: plain CSS, Tailwind v4 ``@theme`` and shadcn/ui variables."""

from __future__ import annotations

from gtui.core.color import oklch_css, parse_color
from gtui.ir.mapping import (
    COLOR_ROLES_ORDER,
    SHADCN_COLOR_MAP,
    SHADCN_FALLBACKS,
    TYPE_SCALE_KEYS,
    tailwind_color_var,
)
from gtui.ir.schema import AestheticProfile, is_unknown


def _fmt_color(hex_value: str, oklch: bool) -> str:
    if not oklch:
        return hex_value
    c = parse_color(hex_value)
    return oklch_css(c) if c else hex_value


def _font_stack(stack: list[str]) -> str:
    return ", ".join(f'"{f}"' if " " in f and not f.startswith(("ui-", "-apple")) else f for f in stack)


def theme_declarations(
    profile: AestheticProfile, *, oklch: bool = False, include_brand: bool = True
) -> list[tuple[str, str, str]]:
    """Return (section, name, value) declarations in Tailwind v4 namespace form."""
    t = profile.tokens
    out: list[tuple[str, str, str]] = []
    roles = sorted(t.colors, key=lambda r: COLOR_ROLES_ORDER.index(r) if r in COLOR_ROLES_ORDER else 99)
    for role in roles:
        tok = t.colors[role]
        if tok.scope == "brand" and not include_brand:
            continue
        out.append(("color", tailwind_color_var(role), _fmt_color(tok.value, oklch)))
    for name, fam in t.typography.families.items():
        if is_unknown(fam):
            continue
        out.append(("font", f"--font-{name}", _font_stack(fam.stack)))  # type: ignore[union-attr]
    for key in TYPE_SCALE_KEYS:
        step = t.typography.scale.get(key)
        if not step:
            continue
        out.append(("text", f"--text-{key}", f"{step.size:g}px"))
        if not is_unknown(step.line_height):
            out.append(("text", f"--text-{key}--line-height", f"{step.line_height:g}"))  # type: ignore[arg-type]
        if not is_unknown(step.letter_spacing) and abs(step.letter_spacing) >= 0.005:  # type: ignore[operator]
            out.append(("text", f"--text-{key}--letter-spacing", f"{step.letter_spacing:g}em"))  # type: ignore[arg-type]
    names = {300: "light", 400: "normal", 500: "medium", 600: "semibold", 700: "bold", 800: "extrabold", 900: "black"}
    for w in t.typography.weights:
        if w in names:
            out.append(("font-weight", f"--font-weight-{names[w]}", str(w)))
    if not is_unknown(t.typography.heading_tracking) and abs(t.typography.heading_tracking) >= 0.005:  # type: ignore[operator]
        out.append(("tracking", "--tracking-heading", f"{t.typography.heading_tracking:g}em"))  # type: ignore[arg-type]
    if not is_unknown(t.spacing.base):
        out.append(("spacing", "--spacing", f"{t.spacing.base / 16:g}rem"))  # type: ignore[operator]
    for key, tok in t.radius.items():
        val = "9999px" if key == "full" else f"{tok.value:g}px"
        out.append(("radius", f"--radius-{key}", val))
    for key, tok in t.shadows.items():
        out.append(("shadow", f"--shadow-{key}", tok.value))
    if not is_unknown(t.motion.durations):
        for k, ms in t.motion.durations.items():  # type: ignore[union-attr]
            out.append(("duration", f"--duration-{k}", f"{ms}ms"))
    if not is_unknown(t.motion.easings):
        for i, ez in enumerate(t.motion.easings[:2]):  # type: ignore[index]
            out.append(("ease", f"--ease-{'standard' if i == 0 else 'emphasized'}", ez))
    return out


def render_css(profile: AestheticProfile, *, oklch: bool = False, selector: str = ":root") -> str:
    decls = theme_declarations(profile, oklch=oklch)
    lines = [f"/* gtui profile: {profile.metadata.name} — {profile.metadata.source} */", f"{selector} {{"]
    section = None
    for sec, name, value in decls:
        if sec != section:
            lines.append(f"  /* {sec} */")
            section = sec
        lines.append(f"  {name}: {value};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_tailwind(profile: AestheticProfile, *, oklch: bool = True) -> str:
    decls = theme_declarations(profile, oklch=oklch)
    lines = [
        f"/* gtui profile: {profile.metadata.name} — Tailwind v4 theme */",
        '@import "tailwindcss";',
        "",
        "@theme {",
    ]
    section = None
    for sec, name, value in decls:
        if sec != section:
            lines.append(f"  /* {sec} */")
            section = sec
        lines.append(f"  {name}: {value};")
    lines.append("}")
    lines += [
        "",
        "@layer base {",
        "  body {",
        "    background-color: var(--color-surface-base);",
        "    color: var(--color-text-primary);",
        "    font-family: var(--font-sans);",
    ]
    base = profile.tokens.typography.scale.get("base")
    if base:
        lines.append("    font-size: var(--text-base);")
        if not is_unknown(base.line_height):
            lines.append("    line-height: var(--text-base--line-height);")
    lines += ["  }", "}", ""]
    return "\n".join(lines)


def shadcn_variables(profile: AestheticProfile) -> dict[str, str]:
    """shadcn/ui variable name -> IR role (resolved, with fallbacks)."""
    colors = profile.tokens.colors
    resolved: dict[str, str] = {}
    for role, names in SHADCN_COLOR_MAP.items():
        if role in colors:
            for n in names:
                resolved.setdefault(n, role)
    for name, role in SHADCN_FALLBACKS.items():
        if name not in resolved and role in colors:
            resolved[name] = role
    # shadcn needs a foreground for every surface; derive sensibly.
    if "foreground" in resolved:
        for n in ("card-foreground", "popover-foreground", "secondary-foreground", "accent-foreground"):
            resolved.setdefault(n, resolved["foreground"])
        resolved.setdefault("muted-foreground", resolved.get("muted-foreground", resolved["foreground"]))
    if "primary" in resolved:
        resolved.setdefault("primary-foreground", "text.on_accent" if "text.on_accent" in colors else "surface.base")
        resolved.setdefault("ring", "accent.primary")
    if "destructive" in resolved:
        resolved.setdefault(
            "destructive-foreground", "text.on_accent" if "text.on_accent" in colors else "surface.base"
        )
    if "background" in resolved:
        for n in ("card", "popover", "secondary", "muted", "accent"):
            resolved.setdefault(n, resolved.get("card", "surface.base"))
    if "border" in resolved:
        resolved.setdefault("input", resolved["border"])
    return resolved


def render_shadcn(profile: AestheticProfile, *, oklch: bool = True, selector: str = ":root") -> str:
    colors = profile.tokens.colors
    resolved = shadcn_variables(profile)
    order = [
        "background",
        "foreground",
        "card",
        "card-foreground",
        "popover",
        "popover-foreground",
        "primary",
        "primary-foreground",
        "secondary",
        "secondary-foreground",
        "muted",
        "muted-foreground",
        "accent",
        "accent-foreground",
        "destructive",
        "destructive-foreground",
        "border",
        "input",
        "ring",
    ]
    lines = [f"/* gtui profile: {profile.metadata.name} — shadcn/ui variables */", f"{selector} {{"]
    for name in order:
        role = resolved.get(name)
        if role and role in colors:
            lines.append(f"  --{name}: {_fmt_color(colors[role].value, oklch)}; /* {role} */")
        else:
            lines.append(f"  /* --{name}: not observed in source */")
    radius = profile.tokens.radius
    md = radius.get("md") or radius.get("lg") or radius.get("sm")
    if md:
        lines.append(f"  --radius: {md.value:g}px;")
    extras = [r for r in colors if r not in {v for v in resolved.values()}]
    if extras:
        lines.append("  /* roles without a shadcn equivalent */")
        for r in extras:
            lines.append(f"  {tailwind_color_var(r)}: {_fmt_color(colors[r].value, oklch)};")
    lines.append("}")
    lines += ["", "@theme inline {"]
    for name in order:
        if name in resolved:
            lines.append(f"  --color-{name}: var(--{name});")
    for key in ("sm", "md", "lg", "xl"):
        if md:
            lines.append(
                f"  --radius-{key}: "
                + {
                    "sm": "calc(var(--radius) - 2px)",
                    "md": "var(--radius)",
                    "lg": "calc(var(--radius) + 2px)",
                    "xl": "calc(var(--radius) + 6px)",
                }[key]
                + ";"
            )
    lines.append("}")
    return "\n".join(lines) + "\n"
