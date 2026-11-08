"""Browser session management.

Two modes:

* **launch** — a fresh headless Chromium (default).
* **connect** — attach to a Chrome the user already started with ``--remote-debugging-port``.
  This is the legitimate path to authenticated product UIs: the user logs in themselves and
  gtui only observes. Cookies and storage belong to the user's own session.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from gtui.observations.models import Viewport


@dataclass
class BrowserOptions:
    headless: bool = True
    connect: str | None = None  # e.g. http://localhost:9222
    viewport: Viewport = field(default_factory=lambda: Viewport(width=1440, height=900))
    color_scheme: str | None = None  # light | dark | None (site default)
    user_agent: str | None = None
    storage_state: str | None = None  # path to Playwright storage state json
    reduced_motion: bool = True  # observe resting styles, not mid-animation frames


@dataclass
class Session:
    browser: Browser
    context: BrowserContext
    owns_context: bool
    version: str
    name: str = "chromium"

    async def new_page(self, viewport: Viewport) -> Page:
        page = await self.context.new_page()
        await page.set_viewport_size({"width": viewport.width, "height": viewport.height})
        return page


@asynccontextmanager
async def open_session(opts: BrowserOptions):
    async with async_playwright() as pw:
        if opts.connect:
            endpoint = opts.connect
            if not endpoint.startswith(("http://", "https://", "ws://", "wss://")):
                endpoint = "http://" + endpoint
            browser = await pw.chromium.connect_over_cdp(endpoint)
            # Reuse the default context so the user's login session is visible.
            if browser.contexts:
                context = browser.contexts[0]
                owns = False
            else:
                context = await browser.new_context()
                owns = True
        else:
            browser = await pw.chromium.launch(headless=opts.headless)
            kwargs: dict = {
                "viewport": {"width": opts.viewport.width, "height": opts.viewport.height},
                "device_scale_factor": 1,
            }
            if opts.color_scheme:
                kwargs["color_scheme"] = opts.color_scheme
            if opts.reduced_motion:
                kwargs["reduced_motion"] = "reduce"
            if opts.user_agent:
                kwargs["user_agent"] = opts.user_agent
            if opts.storage_state:
                kwargs["storage_state"] = opts.storage_state
            context = await browser.new_context(**kwargs)
            owns = True
        session = Session(browser=browser, context=context, owns_context=owns, version=browser.version)
        try:
            yield session
        finally:
            if owns:
                await context.close()
            if opts.connect:
                # never kill the user's browser; just drop the connection
                try:
                    await browser.close()
                except Exception:
                    pass
            else:
                await browser.close()
