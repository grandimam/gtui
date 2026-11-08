"""Fixed mappings from IR semantic names to target vocabularies.

The IR keeps its own role names; these tables make export/transfer mechanical. Each IR color
role maps to a Tailwind v4 ``@theme`` variable (``--color-<role-with-dashes>``) and, where one
exists, to a shadcn/ui variable. Roles without a shadcn equivalent are emitted as extensions.
"""

from __future__ import annotations

COLOR_ROLES_ORDER = [
    "surface.base",
    "surface.raised",
    "surface.overlay",
    "surface.sunken",
    "surface.inverse",
    "text.primary",
    "text.secondary",
    "text.tertiary",
    "text.on_accent",
    "text.link",
    "border.subtle",
    "border.strong",
    "border.focus",
    "accent.primary",
    "accent.hover",
    "accent.secondary",
    "status.success",
    "status.warning",
    "status.danger",
    "status.info",
]

#: IR color role -> shadcn variable(s). First entry is canonical.
SHADCN_COLOR_MAP: dict[str, list[str]] = {
    "surface.base": ["background"],
    "surface.raised": ["card", "popover"],
    "surface.sunken": ["muted", "secondary"],
    "surface.overlay": ["accent"],  # shadcn "accent" = subtle hover surface, not brand accent
    "text.primary": ["foreground", "card-foreground", "popover-foreground"],
    "text.secondary": ["muted-foreground"],
    "text.on_accent": ["primary-foreground"],
    "border.subtle": ["border", "input"],
    "border.focus": ["ring"],
    "accent.primary": ["primary"],
    "status.danger": ["destructive"],
}

#: shadcn variables whose value is derived when the IR has no direct role.
SHADCN_FALLBACKS: dict[str, str] = {
    "secondary-foreground": "text.primary",
    "accent-foreground": "text.primary",
    "muted": "surface.raised",
    "secondary": "surface.raised",
    "accent": "surface.raised",
    "ring": "accent.primary",
    "input": "border.subtle",
    "destructive-foreground": "text.on_accent",
}

#: Tailwind v4 type scale keys, ordered. IR uses the same keys.
TYPE_SCALE_KEYS = ["2xs", "xs", "sm", "base", "lg", "xl", "2xl", "3xl", "4xl", "5xl", "6xl"]

RADIUS_KEYS = ["none", "xs", "sm", "md", "lg", "xl", "2xl", "full"]
SHADOW_KEYS = ["xs", "sm", "md", "lg", "xl"]


def tailwind_color_var(role: str) -> str:
    return "--color-" + role.replace(".", "-").replace("_", "-")


def css_var_for_role(role: str, prefix: str = "") -> str:
    name = role.replace(".", "-").replace("_", "-")
    return f"--{prefix}color-{name}" if prefix else f"--color-{name}"
