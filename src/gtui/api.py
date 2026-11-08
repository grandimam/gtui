"""Python SDK surface.

from gtui.api import capture, extract

obs = await capture("https://example.com", name="example", max_pages=5)
profile = extract(obs)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from gtui.adapters.web.capture import CaptureOptions, capture_site
from gtui.core.config import slugify
from gtui.evaluation.deterministic import EvaluationReport
from gtui.evaluation.deterministic import evaluate as _evaluate
from gtui.inference.synthesizer import synthesize
from gtui.ir.schema import AestheticProfile
from gtui.observations.models import ObservationSet, Viewport
from gtui.storage.profiles import ProfileStore


def parse_viewport(spec: str) -> Viewport:
    w, h = spec.lower().split("x")
    return Viewport(width=int(w), height=int(h))


async def capture(
    url: str,
    *,
    name: str | None = None,
    max_pages: int = 6,
    viewports: list[str] | None = None,
    states: list[str] | None = None,
    connect: str | None = None,
    headless: bool = True,
    color_scheme: str | None = None,
    allow: list[str] | None = None,
    deny: list[str] | None = None,
    responsive_all_pages: bool = False,
    storage_state: str | None = None,
    store: ProfileStore | None = None,
    progress: Callable[[str], None] | None = None,
    save: bool = True,
) -> ObservationSet:
    store = store or ProfileStore.default()
    name = name or slugify(url)
    opts = CaptureOptions(
        name=name,
        out_dir=store.capture_dir(name),
        max_pages=max_pages,
        viewports=[parse_viewport(v) for v in (viewports or ["1440x900"])],
        states=states if states is not None else ["hover", "focus-visible"],
        connect=connect,
        headless=headless,
        color_scheme=color_scheme,
        allow=allow or [],
        deny=deny or [],
        responsive_all_pages=responsive_all_pages,
        storage_state=storage_state,
    )
    obs = await capture_site(url, opts, progress)
    if save:
        store.save_capture(obs)
    return obs


def extract(obs: ObservationSet, *, license: str | None = None, attribution: str | None = None) -> AestheticProfile:
    return synthesize(obs, license=license, attribution=attribution)


def evaluate(profile: AestheticProfile, target: ObservationSet) -> EvaluationReport:
    return _evaluate(profile, target)


def load_profile(name_or_path: str, store: ProfileStore | None = None) -> AestheticProfile:
    p = Path(name_or_path)
    if p.suffix == ".json" and p.exists():
        from gtui.ir import load_profile as _load

        return _load(p)
    return (store or ProfileStore.default()).load_profile(name_or_path)
