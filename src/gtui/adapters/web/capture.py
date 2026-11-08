"""Web capture: explore a site and produce an :class:`ObservationSet`.

Per page: navigate → settle → walk the DOM → (skip if nothing new) → screenshot → CDP
inspection of a representative sample (matched rules for token names, forced hover/focus
states) → observation models with full provenance.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from playwright.async_api import Page

from gtui import __version__
from gtui.adapters.web.browser import BrowserOptions, open_session
from gtui.adapters.web.cdp import CDPInspector
from gtui.adapters.web.dom import EXTRACT_JS
from gtui.adapters.web.explorer import (
    Candidate,
    ExplorerState,
    normalize_url,
    same_site,
    sample_for_inspection,
    style_signatures,
)
from gtui.adapters.web.styles import normalize
from gtui.core.ids import observation_id, page_id
from gtui.observations.models import (
    Bounds,
    CaptureMeta,
    ElementObservation,
    ObservationSet,
    PageCapture,
    Provenance,
    Viewport,
)

log = logging.getLogger(__name__)

_SCROLL_JS = """
async () => {
  const h = document.documentElement.scrollHeight;
  const step = Math.max(400, window.innerHeight * 0.8);
  for (let y = 0; y < Math.min(h, 12000); y += step) {
    window.scrollTo(0, y);
    await new Promise(r => setTimeout(r, 50));
  }
  window.scrollTo(0, 0);
  await new Promise(r => setTimeout(r, 100));
}
"""


@dataclass
class CaptureOptions:
    name: str
    out_dir: Path
    max_pages: int = 6
    viewports: list[Viewport] = field(default_factory=lambda: [Viewport(width=1440, height=900)])
    responsive_all_pages: bool = False
    max_elements: int = 4000
    max_inspected: int = 120
    max_state_elements: int = 40
    states: list[str] = field(default_factory=lambda: ["hover", "focus-visible"])
    timeout_ms: int = 30_000
    settle_ms: int = 800
    min_novelty: float = 0.12
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    headless: bool = True
    connect: str | None = None
    color_scheme: str | None = None
    storage_state: str | None = None
    full_page_screenshots: bool = True

    def to_meta(self) -> dict[str, object]:
        return {
            "max_pages": self.max_pages,
            "viewports": [str(v) for v in self.viewports],
            "states": list(self.states),
            "max_inspected": self.max_inspected,
            "min_novelty": self.min_novelty,
            "color_scheme": self.color_scheme,
            "connect": bool(self.connect),
        }


ProgressFn = Callable[[str], None]


async def capture_site(url: str, opts: CaptureOptions, progress: ProgressFn | None = None) -> ObservationSet:
    say = progress or (lambda _msg: None)
    url = normalize_url(url if "://" in url else "https://" + url)
    opts.out_dir.mkdir(parents=True, exist_ok=True)
    (opts.out_dir / "screenshots").mkdir(exist_ok=True)

    primary = opts.viewports[0]
    bopts = BrowserOptions(
        headless=opts.headless,
        connect=opts.connect,
        viewport=primary,
        color_scheme=opts.color_scheme,
        storage_state=opts.storage_state,
    )
    state = ExplorerState(
        origin=url,
        allow=[re.compile(p) for p in opts.allow],
        deny=[re.compile(p) for p in opts.deny],
    )
    queue: list[Candidate] = [Candidate(url=url, text="", in_nav=True, score=100.0)]
    state.queued.add(url)

    async with open_session(bopts) as session:
        obs = ObservationSet(
            name=opts.name,
            source=url,
            meta=CaptureMeta(
                gtui_version=__version__,
                browser=session.name,
                browser_version=session.version,
                config=opts.to_meta(),
            ),
        )
        page = await session.new_page(primary)
        pages_done = 0
        attempts = 0
        while queue and pages_done < opts.max_pages and attempts < opts.max_pages * 4:
            attempts += 1
            queue.sort(key=lambda c: -c.score)
            cand = queue.pop(0)
            state.mark_visited(cand.url)
            viewports = opts.viewports if (pages_done == 0 or opts.responsive_all_pages) else [primary]
            captured_any = False
            for vp in viewports:
                say(f"[{pages_done + 1}/{opts.max_pages}] {cand.url} @ {vp}")
                try:
                    links, recorded = await _capture_page(page, cand.url, vp, opts, state, obs, first=(pages_done == 0))
                except Exception as exc:  # network errors, timeouts
                    log.warning("capture failed for %s: %s", cand.url, exc)
                    obs.skipped.append({"url": cand.url, "reason": f"error: {exc}"[:200]})
                    break
                if links is None:
                    break
                # a low-novelty page still contributes its links, but does not spend the budget
                captured_any = captured_any or recorded
                if vp is primary or vp == viewports[0]:
                    new = state.enqueue(links, cand.url)
                    queue.extend(new)
                    for c in queue:
                        c.score = state.score(c)
                if not recorded:
                    break
            if captured_any:
                pages_done += 1
        await page.close()
    obs.captured_at = datetime.now(UTC)
    return obs


async def _capture_page(
    page: Page,
    url: str,
    viewport: Viewport,
    opts: CaptureOptions,
    state: ExplorerState,
    obs: ObservationSet,
    *,
    first: bool,
) -> tuple[list[dict] | None, bool]:
    """Capture one page at one viewport.

    Returns ``(links, recorded)``: links discovered on the page (None if the page could not be
    loaded) and whether observations were recorded (False for low-novelty skips).
    """
    await page.set_viewport_size({"width": viewport.width, "height": viewport.height})
    response = await page.goto(url, wait_until="load", timeout=opts.timeout_ms)
    if response is not None and response.status >= 400:
        obs.skipped.append({"url": url, "reason": f"http {response.status}"})
        return None, False
    try:
        await page.wait_for_load_state("networkidle", timeout=min(6000, opts.timeout_ms))
    except Exception:
        pass
    await page.wait_for_timeout(opts.settle_ms)
    try:
        await page.evaluate(_SCROLL_JS)
    except Exception:
        pass

    data = await page.evaluate(EXTRACT_JS, {"maxElements": opts.max_elements})
    final_url = normalize_url(data.get("url") or url)
    if final_url != url:
        state.mark_visited(final_url)
        if first and not same_site(final_url, state.origin):
            # geo / locale redirect (airbnb.com -> airbnb.ae): explore the site we actually landed on
            log.info("entry redirected to %s; adopting it as the exploration origin", final_url)
            state.origin = final_url
    pid = page_id(final_url, viewport.as_tuple())
    if any(p.id == pid and not p.skipped_reason for p in obs.pages):
        return data.get("links", []), False

    elements_raw: list[dict] = data.get("elements", [])
    sigs = style_signatures(elements_raw)
    novelty = state.novelty(sigs)
    captured_at = datetime.now(UTC)
    if not first and novelty < opts.min_novelty:
        obs.pages.append(
            PageCapture(
                id=pid,
                url=final_url,
                title=data.get("title", ""),
                viewport=viewport,
                captured_at=captured_at,
                element_count=len(elements_raw),
                signatures=[],
                skipped_reason=f"low novelty ({novelty:.0%} new style signatures)",
            )
        )
        obs.skipped.append({"url": final_url, "reason": f"low novelty {novelty:.0%}"})
        return data.get("links", []), False
    state.absorb(sigs)

    # Screenshot
    shot_rel = f"screenshots/{pid}.png"
    scroll_h = int(data.get("scroll", {}).get("h", 0))
    try:
        await page.screenshot(
            path=str(opts.out_dir / shot_rel),
            full_page=opts.full_page_screenshots and scroll_h <= 8000,
            animations="disabled",
        )
    except Exception as exc:
        log.warning("screenshot failed: %s", exc)
        shot_rel = None  # type: ignore[assignment]

    # Freeze transitions/animations so forced pseudo-states report resting values, not the first
    # frame of a transition. Default styles (incl. transition-duration) were already recorded.
    try:
        await page.add_style_tag(content="*,*::before,*::after{transition:none!important;animation:none!important}")
    except Exception:
        pass

    # CDP inspection of a representative sample
    css_vars: dict[str, dict[str, str]] = {}
    state_diffs: dict[tuple[str, str], dict[str, str]] = {}
    custom_props: dict[str, str] = {}
    inspector = CDPInspector(page)
    try:
        await inspector.start()
        custom_props = await inspector.root_custom_properties()
        sample = sample_for_inspection(elements_raw, opts.max_inspected)
        states_done = 0
        for el in sample:
            nid = await inspector.node_for_key(el["key"])
            if nid is None:
                continue
            matched = await inspector.matched_styles(nid)
            if matched:
                usage = inspector.var_usage(matched)
                if usage:
                    css_vars[el["key"]] = usage
            if _interactive(el) and states_done < opts.max_state_elements and not el.get("disabled"):
                states_done += 1
                for pseudo in opts.states:
                    st = await inspector.state_styles(nid, pseudo)
                    if not st:
                        continue
                    base = el.get("style", {})
                    diff = {p: v for p, v in st.items() if v and v != base.get(p, "")}
                    if diff:
                        state_diffs[(el["key"], pseudo)] = diff
    except Exception as exc:
        log.warning("CDP inspection failed on %s: %s", final_url, exc)
    finally:
        await inspector.stop()

    # Build models
    root = data.get("root", {})
    page_model = PageCapture(
        id=pid,
        url=final_url,
        title=data.get("title", ""),
        viewport=viewport,
        screenshot=shot_rel,
        captured_at=captured_at,
        scroll_width=int(data.get("scroll", {}).get("w", 0)),
        scroll_height=scroll_h,
        element_count=len(elements_raw),
        root_background=_hex(root.get("bodyBackground")) or _hex(root.get("htmlBackground")),
        root_color=_hex(root.get("color")),
        root_font_family=root.get("fontFamily", ""),
        root_font_size=_px(root.get("fontSize")),
        custom_properties=custom_props,
        signatures=sigs,
    )
    obs.pages.append(page_model)

    prov = Provenance(page_id=pid, url=final_url, viewport=viewport, screenshot=shot_rel, captured_at=captured_at)
    key_to_id = {el["key"]: observation_id(pid, el["key"]) for el in elements_raw}
    for el in elements_raw:
        base_style = normalize(el.get("style", {}))
        b = el.get("bounds", {})
        common = dict(
            page_id=pid,
            key=el["key"],
            tag=el.get("tag", ""),
            role=el.get("role", "") or "",
            region=el.get("region", "") or "",
            depth=int(el.get("depth", 0)),
            parent_id=key_to_id.get(el.get("parent")) if el.get("parent") else None,
            child_count=int(el.get("childCount", 0)),
            text=el.get("text", "") or "",
            text_length=int(el.get("textLength", 0)),
            classes=el.get("classes", "") or "",
            href=el.get("href") or None,
            bounds=Bounds(x=b.get("x", 0), y=b.get("y", 0), width=b.get("width", 0), height=b.get("height", 0)),
            in_viewport=bool(el.get("inViewport", True)),
            current=bool(el.get("current", False)),
            disabled=bool(el.get("disabled", False)),
            css_vars=css_vars.get(el["key"], {}),
            provenance=prov,
        )
        obs.elements.append(ElementObservation(id=key_to_id[el["key"]], style=base_style, **common))
        for pseudo in opts.states:
            diff = state_diffs.get((el["key"], pseudo))
            if not diff:
                continue
            merged = {**el.get("style", {}), **diff}
            obs.elements.append(
                ElementObservation(
                    id=observation_id(pid, el["key"], pseudo),
                    state=pseudo,
                    state_diff=diff,
                    style=normalize(merged),
                    **common,
                )
            )
    return data.get("links", []), True


def _interactive(el: dict) -> bool:
    return el.get("role") in {"button", "link", "textbox", "combobox", "checkbox", "radio", "tab", "menuitem", "switch"}


def _hex(value: str | None) -> str | None:
    from gtui.adapters.web.styles import color_hex

    return color_hex(value)


def _px(value: str | None) -> float:
    from gtui.adapters.web.styles import px

    return px(value, 0.0)
