"""Observation models — the raw, measured evidence a capture produces.

Everything downstream (tokens, components, principles) must reference observations by id.
Observations are *facts about what was rendered*; interpretation happens in ``gtui.inference``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

SourceKind = Literal["rendered", "source_code", "accessibility"]
"""Where an observation came from. Inference can weigh evidence kinds differently."""


class Viewport(BaseModel):
    width: int
    height: int

    def as_tuple(self) -> tuple[int, int]:
        return (self.width, self.height)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.width}x{self.height}"


class Bounds(BaseModel):
    x: float
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)


class ComputedStyle(BaseModel):
    """Normalized subset of computed CSS. Colors are sRGB hex (``#rrggbb[aa]``) or ``None``
    when fully transparent / unparseable."""

    display: str = ""
    position: str = ""
    color: str | None = None
    background_color: str | None = None
    has_gradient: bool = False
    gradient_colors: list[str] = Field(default_factory=list)  # sRGB hex stops, when has_gradient
    has_background_image: bool = False
    font_family: str = ""
    font_size: float = 0.0
    font_weight: int = 400
    line_height: float | None = None  # px
    letter_spacing: float = 0.0  # px
    text_transform: str = "none"
    text_decoration: str = "none"
    border_width: float = 0.0
    border_style: str = "none"
    border_color: str | None = None
    radius: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    box_shadow: str | None = None
    opacity: float = 1.0
    padding: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    margin: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    gap: float | None = None
    cursor: str = "auto"
    outline_width: float = 0.0
    outline_style: str = "none"
    outline_color: str | None = None
    transition_durations: list[float] = Field(default_factory=list)  # ms
    transition_properties: list[str] = Field(default_factory=list)
    transition_easings: list[str] = Field(default_factory=list)
    backdrop_filter: str | None = None
    max_width: float | None = None  # px, when specified in px
    flex_direction: str = ""
    align_items: str = ""
    justify_content: str = ""

    @property
    def radius_max(self) -> float:
        return max(self.radius) if self.radius else 0.0

    @property
    def padding_x(self) -> float:
        return (self.padding[1] + self.padding[3]) / 2

    @property
    def padding_y(self) -> float:
        return (self.padding[0] + self.padding[2]) / 2

    @property
    def has_border(self) -> bool:
        return self.border_width > 0 and self.border_style not in ("none", "hidden") and bool(self.border_color)

    @property
    def has_shadow(self) -> bool:
        return bool(self.box_shadow) and self.box_shadow != "none"


class Provenance(BaseModel):
    page_id: str
    url: str
    viewport: Viewport
    screenshot: str | None = None  # relative path inside the capture directory
    captured_at: datetime
    source_kind: SourceKind = "rendered"


class ElementObservation(BaseModel):
    id: str
    page_id: str
    key: str  # per-page element key (e.g. "e42") used to join states
    tag: str
    role: str = ""
    region: str = ""  # nearest landmark: nav/header/footer/aside/main
    depth: int = 0
    parent_id: str | None = None
    child_count: int = 0
    text: str = ""
    text_length: int = 0
    classes: str = ""
    href: str | None = None
    bounds: Bounds
    in_viewport: bool = True
    current: bool = False  # aria-current / aria-selected
    disabled: bool = False
    state: str = "default"  # default | hover | focus-visible | active
    state_diff: dict[str, str] = Field(default_factory=dict)  # property -> value under state
    style: ComputedStyle
    css_vars: dict[str, str] = Field(default_factory=dict)  # css property -> custom property name
    provenance: Provenance

    @property
    def is_interactive(self) -> bool:
        return self.role in {
            "button",
            "link",
            "textbox",
            "combobox",
            "checkbox",
            "radio",
            "tab",
            "menuitem",
            "switch",
            "option",
        }


class PageCapture(BaseModel):
    id: str
    url: str
    title: str = ""
    viewport: Viewport
    screenshot: str | None = None
    captured_at: datetime
    scroll_width: int = 0
    scroll_height: int = 0
    element_count: int = 0
    root_background: str | None = None
    root_color: str | None = None
    root_font_family: str = ""
    root_font_size: float = 0.0
    custom_properties: dict[str, str] = Field(default_factory=dict)  # --name -> value on :root
    signatures: list[str] = Field(default_factory=list)  # style signatures for dedupe
    skipped_reason: str | None = None


class CaptureMeta(BaseModel):
    gtui_version: str
    browser: str = ""
    browser_version: str = ""
    user_agent: str = ""
    config: dict[str, object] = Field(default_factory=dict)


class ObservationSet(BaseModel):
    name: str
    source: str
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    meta: CaptureMeta
    pages: list[PageCapture] = Field(default_factory=list)
    elements: list[ElementObservation] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)  # url + reason

    # -- convenience -------------------------------------------------------------------------

    def by_id(self) -> dict[str, ElementObservation]:
        return {e.id: e for e in self.elements}

    def defaults(self) -> list[ElementObservation]:
        return [e for e in self.elements if e.state == "default"]

    def viewports(self) -> list[Viewport]:
        seen: dict[tuple[int, int], Viewport] = {}
        for p in self.pages:
            seen.setdefault(p.viewport.as_tuple(), p.viewport)
        return list(seen.values())

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=None), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> ObservationSet:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def summary(self) -> dict[str, object]:
        states = sorted({e.state for e in self.elements})
        return {
            "pages": len([p for p in self.pages if not p.skipped_reason]),
            "elements": len(self.defaults()),
            "state_observations": len(self.elements) - len(self.defaults()),
            "states": states,
            "viewports": [str(v) for v in self.viewports()],
        }


def dump_json(obj: BaseModel, path: Path, indent: int | None = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj.model_dump(mode="json"), indent=indent), encoding="utf-8")
    return path
