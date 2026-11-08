"""Aesthetic IR v0.1 — the framework-independent description of a design language.

Design rules baked into this schema:

* **Unknown is explicit.** A field that was not observed holds ``Unknown`` (serialized as
  ``{"unknown": true, "reason": …}``), never a guessed value and never a silent ``None``.
* **Everything carries evidence.** Tokens, recipes and principles reference observation ids and
  carry a confidence in ``[0, 1]`` derived from sample size and consistency.
* **Semantic names, Tailwind-aligned structure.** Token categories map 1:1 onto Tailwind v4
  ``@theme`` namespaces and semantic color roles map onto shadcn variables (see
  ``gtui.ir.mapping``), so export is mechanical; the names themselves describe *role*.
* **Style vs brand.** Anything that is source-specific expression rather than a reusable
  convention is tagged ``scope="brand"`` and stripped on apply/publish by default.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "0.1"

Scope = Literal["style", "brand"]


class Unknown(BaseModel):
    """Explicit marker for a property that was not (sufficiently) observed.

    ``unknown`` is required (no default) and extras are forbidden so that an ordinary dict
    value can never be mistaken for an Unknown inside ``X | Unknown`` unions.
    """

    model_config = ConfigDict(extra="forbid")

    unknown: Literal[True]
    reason: str = "not observed"


def unknown(reason: str = "not observed") -> Unknown:
    return Unknown(unknown=True, reason=reason)


def is_unknown(value: object) -> bool:
    return isinstance(value, Unknown)


class Evidence(BaseModel):
    """Shared evidence/confidence fields."""

    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    usage_count: int = 0
    evidence: list[str] = Field(default_factory=list, description="Observation ids")


# --- Tokens ----------------------------------------------------------------------------------


class ColorToken(Evidence):
    value: str = Field(description="sRGB hex #rrggbb or #rrggbbaa")
    role: str = Field(description="Dotted semantic role, e.g. surface.base, text.primary")
    scope: Scope = "style"
    source_names: list[str] = Field(
        default_factory=list, description="CSS custom property names the source used for it"
    )
    contrast_on_base: float | None = Field(default=None, description="WCAG ratio vs surface.base")
    note: str | None = None


class FontFamily(Evidence):
    stack: list[str] = Field(description="Font family stack as observed, first is primary")
    scope: Scope = "style"
    generic: Literal["sans-serif", "serif", "monospace", "display", "unknown"] = "unknown"
    note: str | None = None

    @property
    def primary(self) -> str:
        return self.stack[0] if self.stack else ""


class TypeStep(Evidence):
    size: float = Field(description="px")
    line_height: float | Unknown = Field(default_factory=unknown, description="unitless ratio")
    weights: list[int] = Field(default_factory=list, description="weights seen at this size")
    letter_spacing: float | Unknown = Field(default_factory=unknown, description="em")
    roles: list[str] = Field(default_factory=list, description="e.g. body, caption, h1")


class Typography(BaseModel):
    families: dict[str, FontFamily | Unknown] = Field(default_factory=dict, description="sans | mono | display")
    scale: dict[str, TypeStep] = Field(default_factory=dict, description="xs, sm, base, lg, xl, 2xl … ordered by size")
    body: str | Unknown = Field(default_factory=unknown, description="scale key used for body")
    weights: list[int] = Field(default_factory=list)
    heading_weight: int | Unknown = Field(default_factory=unknown)
    heading_tracking: float | Unknown = Field(default_factory=unknown, description="em")
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class SpacingScale(BaseModel):
    base: int | Unknown = Field(default_factory=unknown, description="px grid unit")
    scale: list[int] = Field(default_factory=list, description="px values in use")
    grid_adherence: float | None = Field(default=None, description="fraction on the base grid")
    confidence: float = 0.0
    usage_count: int = 0
    evidence: list[str] = Field(default_factory=list)


class DimensionToken(Evidence):
    value: float = Field(description="px")


class ShadowToken(Evidence):
    value: str = Field(description="CSS box-shadow")
    blur: float = 0.0
    scope: Scope = "style"


class Borders(BaseModel):
    width: float | Unknown = Field(default_factory=unknown, description="dominant px")
    color_role: str | Unknown = Field(default_factory=unknown)
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class Motion(BaseModel):
    durations: dict[str, int] | Unknown = Field(default_factory=unknown, description="fast/base/slow in ms")
    easings: list[str] | Unknown = Field(default_factory=unknown)
    properties: list[str] = Field(default_factory=list, description="commonly transitioned")
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class Tokens(BaseModel):
    colors: dict[str, ColorToken] = Field(default_factory=dict, description="keyed by role")
    typography: Typography = Field(default_factory=Typography)
    spacing: SpacingScale = Field(default_factory=SpacingScale)
    radius: dict[str, DimensionToken] = Field(default_factory=dict, description="none/sm/md/lg/xl/full")
    shadows: dict[str, ShadowToken] = Field(default_factory=dict, description="sm/md/lg")
    borders: Borders = Field(default_factory=Borders)
    motion: Motion = Field(default_factory=Motion)
    palette_source_properties: dict[str, str] = Field(
        default_factory=dict,
        description="Raw custom properties defined on :root by the source (evidence, not tokens)",
    )


# --- Components ------------------------------------------------------------------------------

ComponentKind = Literal["button", "input", "card", "link", "nav_item", "heading", "badge", "table_row", "surface"]


class StateDelta(BaseModel):
    """How a component changes in an interaction state, as observed."""

    changes: dict[str, str] = Field(default_factory=dict, description="property -> value")
    description: str = ""
    sample_count: int = 0
    evidence: list[str] = Field(default_factory=list)


class ComponentRecipe(Evidence):
    kind: ComponentKind
    variant: str = "default"
    description: str = ""
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Framework-agnostic recipe. Values reference token roles where possible, e.g. "
            "{'height': 32, 'padding_x': 12, 'font': 'sm', 'weight': 500, 'radius': 'md', "
            "'background': 'accent.primary', 'text': 'text.on_accent', 'border': 'none'}"
        ),
    )
    states: dict[str, StateDelta] = Field(default_factory=dict)
    sample_count: int = 0


# --- Character / composition / principles ----------------------------------------------------


class Character(BaseModel):
    color_scheme: Literal["dark", "light", "mixed"] | Unknown = Field(default_factory=unknown)
    density: Literal["compact", "comfortable", "spacious"] | Unknown = Field(default_factory=unknown)
    contrast: Literal["restrained", "moderate", "bold"] | Unknown = Field(default_factory=unknown)
    depth: Literal["flat", "subtle", "layered"] | Unknown = Field(default_factory=unknown)
    ornamentation: Literal["minimal", "moderate", "rich"] | Unknown = Field(default_factory=unknown)
    geometry: Literal["sharp", "precise", "soft", "round"] | Unknown = Field(default_factory=unknown)
    summary: str = ""


class Composition(BaseModel):
    max_content_width: int | Unknown = Field(default_factory=unknown, description="px")
    layout_primitives: dict[str, float] = Field(
        default_factory=dict, description="share of containers using flex/grid/block"
    )
    hierarchy: Literal["typography_first", "color_first", "size_first", "mixed"] | Unknown = Field(
        default_factory=unknown
    )
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class Principle(Evidence):
    id: str
    kind: Literal["invariant", "variant", "exception"] = "invariant"
    statement: str
    rationale: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


# --- Profile ---------------------------------------------------------------------------------


class Coverage(BaseModel):
    pages: int = 0
    viewports: list[str] = Field(default_factory=list)
    elements: int = 0
    state_observations: int = 0
    states: list[str] = Field(default_factory=list)
    components_sampled: dict[str, int] = Field(default_factory=dict)


class Metadata(BaseModel):
    name: str
    version: str = "0.1.0"
    source: str
    captured_at: datetime
    extracted_at: datetime
    gtui_version: str
    browser: str = ""
    license: str | None = None
    attribution: str | None = None
    description: str = ""


class Brand(BaseModel):
    """What was deliberately *not* generalized."""

    excluded: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AestheticProfile(BaseModel):
    schema_version: str = SCHEMA_VERSION
    metadata: Metadata
    character: Character = Field(default_factory=Character)
    tokens: Tokens = Field(default_factory=Tokens)
    components: list[ComponentRecipe] = Field(default_factory=list)
    composition: Composition = Field(default_factory=Composition)
    principles: list[Principle] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict, description="per section")
    coverage: Coverage = Field(default_factory=Coverage)
    brand: Brand = Field(default_factory=Brand)
    unknowns: list[str] = Field(default_factory=list, description="human-readable list")
    extensions: dict[str, Any] = Field(default_factory=dict)

    # -- helpers -----------------------------------------------------------------------------

    def color(self, role: str) -> ColorToken | None:
        return self.tokens.colors.get(role)

    def style_colors(self) -> dict[str, ColorToken]:
        return {k: v for k, v in self.tokens.colors.items() if v.scope == "style"}

    def recipes(self, kind: ComponentKind) -> list[ComponentRecipe]:
        return [c for c in self.components if c.kind == kind]
