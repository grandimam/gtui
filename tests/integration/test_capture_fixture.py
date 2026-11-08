"""End-to-end: serve the fixture site, capture it with a real browser, extract, evaluate.

Requires `playwright install chromium`; skipped otherwise.
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from gtui.adapters.web.capture import CaptureOptions, capture_site
from gtui.evaluation.deterministic import evaluate
from gtui.inference.synthesizer import synthesize
from gtui.observations.models import Viewport

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "site"


def _browser_available() -> bool:
    try:
        from playwright._impl._driver import compute_driver_executable  # noqa: F401
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def site_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURE))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{port}/index.html"
        httpd.shutdown()


@pytest.mark.skipif(not _browser_available(), reason="Playwright chromium not installed")
async def test_capture_extract_evaluate(site_url, tmp_path: Path):
    opts = CaptureOptions(
        name="fixture", out_dir=tmp_path / "cap", max_pages=4, viewports=[Viewport(width=1280, height=800)]
    )
    obs = await capture_site(site_url, opts)
    s = obs.summary()
    assert s["pages"] >= 2, obs.skipped
    assert s["elements"] > 100
    assert s["state_observations"] > 0
    assert any(p.custom_properties.get("--color-accent") for p in obs.pages)
    # provenance + screenshots
    for p in obs.pages:
        if not p.skipped_reason:
            assert p.screenshot and (tmp_path / "cap" / p.screenshot).exists()
    # token names were recovered from matched rules
    assert any(e.css_vars.get("background-color") == "--color-accent" for e in obs.elements)

    profile = synthesize(obs)
    c = profile.tokens.colors
    assert c["surface.base"].value == "#111115"
    assert c["accent.primary"].value == "#5e6ad2"
    assert c["text.primary"].value == "#f7f7f8"
    assert c["border.focus"].value == "#5e6ad2"
    assert profile.tokens.typography.scale["base"].size == 14
    assert profile.tokens.spacing.base == 4
    assert profile.tokens.motion.durations == {"base": 120}
    kinds = {(r.kind, r.variant) for r in profile.components}
    assert ("button", "primary") in kinds and ("card", "default") in kinds and ("input", "default") in kinds
    primary = next(r for r in profile.components if r.kind == "button" and r.variant == "primary")
    assert primary.states["hover"].changes["background-color"] == "accent.hover"
    assert primary.states["focus-visible"].changes["outline-color"] == "border.focus"

    # a site evaluated against its own profile should score very high
    report = evaluate(profile, obs)
    assert report.overall >= 0.9

    # stable ids across runs
    obs2 = await capture_site(
        site_url,
        CaptureOptions(
            name="fixture", out_dir=tmp_path / "cap2", max_pages=1, viewports=[Viewport(width=1280, height=800)]
        ),
    )
    ids1 = {e.id for e in obs.elements if e.page_id == obs.pages[0].id}
    ids2 = {e.id for e in obs2.elements}
    assert ids2 <= ids1
