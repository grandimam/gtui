"""Synthetic observation sets — a tiny dark, compact 'tool' UI — for browser-free tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gtui.core.ids import observation_id
from gtui.observations.models import (
    Bounds,
    CaptureMeta,
    ComputedStyle,
    ElementObservation,
    ObservationSet,
    PageCapture,
    Provenance,
    Viewport,
)

VP = Viewport(width=1440, height=900)
NOW = datetime(2026, 11, 8, tzinfo=UTC)


class Builder:
    def __init__(self, name: str = "synthetic", url: str = "https://synthetic.test/") -> None:
        self.obs = ObservationSet(
            name=name, source=url, captured_at=NOW, meta=CaptureMeta(gtui_version="test", browser="chromium")
        )
        self.page_id = "page-synth"
        self.obs.pages.append(
            PageCapture(
                id=self.page_id,
                url=url,
                viewport=VP,
                captured_at=NOW,
                scroll_width=1440,
                scroll_height=2000,
                root_background="#111115",
                root_color="#f7f7f8",
                root_font_family="Inter, sans-serif",
                root_font_size=14,
                custom_properties={"--color-bg-primary": "#111115", "--color-accent": "#5e6ad2"},
            )
        )
        self.prov = Provenance(page_id=self.page_id, url=url, viewport=VP, captured_at=NOW)
        self.n = 0

    def el(
        self,
        tag: str,
        *,
        role: str = "",
        text: str = "",
        w: float = 100,
        h: float = 20,
        parent: str | None = None,
        region: str = "",
        css_vars: dict | None = None,
        state: str = "default",
        state_diff: dict | None = None,
        key: str | None = None,
        **style,
    ) -> ElementObservation:
        key = key or f"e{self.n}"
        if state == "default":
            self.n += 1
        st = ComputedStyle(**{"font_family": "Inter, sans-serif", "font_size": 14, "line_height": 21, **style})
        e = ElementObservation(
            id=observation_id(self.page_id, key, state),
            page_id=self.page_id,
            key=key,
            tag=tag,
            role=role,
            region=region,
            depth=1 if parent is None else 2,
            parent_id=parent,
            child_count=0,
            text=text,
            text_length=len(text),
            bounds=Bounds(x=0, y=0, width=w, height=h),
            state=state,
            state_diff=state_diff or {},
            style=st,
            css_vars=css_vars or {},
            provenance=self.prov,
        )
        self.obs.elements.append(e)
        return e


@pytest.fixture
def synthetic() -> ObservationSet:
    b = Builder()
    body = b.el("body", w=1440, h=2000, background_color="#111115", css_vars={"background-color": "--color-bg-primary"})
    # body text and secondary captions
    for _ in range(12):
        b.el(
            "p",
            role="paragraph",
            text="Body copy " * 8,
            w=600,
            h=21,
            parent=body.id,
            color="#f7f7f8",
            css_vars={"color": "--color-text-primary"},
        )
    for _ in range(8):
        b.el("span", text="caption", w=80, h=18, parent=body.id, color="#a0a0a9", font_size=12, line_height=18)
    for _ in range(3):
        b.el(
            "h1",
            role="heading",
            text="Heading",
            w=400,
            h=29,
            parent=body.id,
            color="#f7f7f8",
            font_size=24,
            font_weight=600,
            line_height=29,
            letter_spacing=-0.48,
        )
    # cards with borders
    for _ in range(6):
        c = b.el(
            "div",
            w=300,
            h=120,
            parent=body.id,
            background_color="#1c1c22",
            border_width=1,
            border_style="solid",
            border_color="#26262c",
            radius=[10, 10, 10, 10],
            padding=[16, 16, 16, 16],
        )
        c.child_count = 2
        b.el("h3", role="heading", text="Card", w=200, h=21, parent=c.id, color="#f7f7f8", font_weight=600)
    # buttons: primary (accent) + ghost, with hover states
    for _ in range(4):
        btn = b.el(
            "button",
            role="button",
            text="Save",
            w=80,
            h=32,
            parent=body.id,
            background_color="#5e6ad2",
            color="#ffffff",
            font_size=13,
            font_weight=500,
            radius=[6, 6, 6, 6],
            padding=[0, 12, 0, 12],
            transition_durations=[120.0],
            transition_properties=["background-color"],
            transition_easings=["ease"],
            css_vars={"background-color": "--color-accent"},
        )
        b.el(
            "button",
            role="button",
            text="Save",
            w=80,
            h=32,
            parent=body.id,
            key=btn.key,
            state="hover",
            state_diff={"background-color": "rgb(111, 122, 224)"},
            background_color="#6f7ae0",
            color="#ffffff",
            font_size=13,
            font_weight=500,
            radius=[6, 6, 6, 6],
            padding=[0, 12, 0, 12],
        )
    for _ in range(5):
        b.el(
            "button",
            role="button",
            text="Cancel",
            w=80,
            h=32,
            parent=body.id,
            color="#a0a0a9",
            font_size=13,
            font_weight=500,
            radius=[6, 6, 6, 6],
            padding=[0, 12, 0, 12],
            transition_durations=[120.0],
        )
    # inputs
    for _ in range(3):
        b.el(
            "input",
            role="textbox",
            text="",
            w=240,
            h=32,
            parent=body.id,
            background_color="#1c1c22",
            border_width=1,
            border_style="solid",
            border_color="#26262c",
            radius=[6, 6, 6, 6],
            padding=[0, 10, 0, 10],
            font_size=13,
        )
    # nav
    nav = b.el("nav", role="navigation", w=600, h=48, parent=body.id, region="nav")
    for _ in range(4):
        b.el(
            "a",
            role="link",
            text="Issues",
            w=60,
            h=28,
            parent=nav.id,
            region="nav",
            color="#a0a0a9",
            font_size=13,
            font_weight=500,
            radius=[4, 4, 4, 4],
            padding=[0, 8, 0, 8],
        )
    # danger + success badges
    for _ in range(3):
        b.el(
            "span",
            text="Error",
            w=48,
            h=20,
            parent=body.id,
            background_color="#e5484d",
            color="#ffffff",
            font_size=11,
            radius=[4, 4, 4, 4],
            padding=[0, 6, 0, 6],
        )
        b.el(
            "span",
            text="Done",
            w=48,
            h=20,
            parent=body.id,
            background_color="#30a46c",
            color="#ffffff",
            font_size=11,
            radius=[4, 4, 4, 4],
            padding=[0, 6, 0, 6],
        )
    # inline links
    for _ in range(3):
        b.el("a", role="link", text="learn more", w=70, h=21, parent=body.id, color="#5e6ad2")
    return b.obs
