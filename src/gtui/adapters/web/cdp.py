"""Chrome DevTools Protocol helpers.

Three things only CDP gives us cleanly:

* ``CSS.getMatchedStylesForNode`` — the *authored* declarations that matched, including the
  ``var(--token)`` references that computed styles have already resolved away. These names are
  the strongest signal we have for a token's semantic role.
* Custom property definitions on ``:root``/``html``/``body`` — the source's own token layer.
* ``CSS.forcePseudoState`` — read hover / focus-visible styling without dispatching events.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from playwright.async_api import CDPSession, Page

from gtui.adapters.web.dom import STATE_PROPS

log = logging.getLogger(__name__)

_VAR_RE = re.compile(r"var\(\s*(--[\w-]+)")
#: Shorthands whose var() reference should also be reported under the longhand we observe.
SHORTHANDS = {
    "background": "background-color",
    "border": "border-top-color",
    "border-color": "border-top-color",
    "border-top": "border-top-color",
    "outline": "outline-color",
    "border-radius": "border-top-left-radius",
    "font": "font-family",
}
INHERITED_PROPS = {"color", "font-family", "font-size", "line-height", "letter-spacing", "font-weight"}


class CDPInspector:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.session: CDPSession | None = None
        self.root_node_id: int | None = None

    async def start(self) -> None:
        self.session = await self.page.context.new_cdp_session(self.page)
        await self.session.send("DOM.enable")
        await self.session.send("CSS.enable")
        await self.refresh_document()

    async def refresh_document(self) -> None:
        assert self.session
        doc = await self.session.send("DOM.getDocument", {"depth": 0})
        self.root_node_id = doc["root"]["nodeId"]

    async def stop(self) -> None:
        if self.session:
            try:
                await self.session.detach()
            except Exception:  # pragma: no cover - best effort
                pass
            self.session = None

    async def node_id(self, selector: str) -> int | None:
        assert self.session and self.root_node_id is not None
        try:
            res = await self.session.send("DOM.querySelector", {"nodeId": self.root_node_id, "selector": selector})
        except Exception as exc:  # stale document etc.
            log.debug("querySelector failed for %s: %s", selector, exc)
            try:
                await self.refresh_document()
                res = await self.session.send("DOM.querySelector", {"nodeId": self.root_node_id, "selector": selector})
            except Exception:
                return None
        nid = res.get("nodeId", 0)
        return nid or None

    async def node_for_key(self, key: str) -> int | None:
        return await self.node_id(f'[data-gtui="{key}"]')

    # -- matched styles ------------------------------------------------------------------------

    async def matched_styles(self, node_id: int) -> dict[str, Any] | None:
        assert self.session
        try:
            return await self.session.send("CSS.getMatchedStylesForNode", {"nodeId": node_id})
        except Exception as exc:
            log.debug("getMatchedStylesForNode failed: %s", exc)
            return None

    @staticmethod
    def _iter_rule_props(matched: dict[str, Any], *, include_ua: bool = False):
        for entry in matched.get("matchedCSSRules", []) or []:
            rule = entry.get("rule", {})
            if not include_ua and rule.get("origin") != "regular":
                continue
            for prop in rule.get("style", {}).get("cssProperties", []) or []:
                # Only *authored* declarations carry `text`/`range`; the rest are longhand expansions
                # Chrome synthesizes from shorthands (where var() references are already lost). We
                # expand shorthands ourselves via SHORTHANDS.
                if "text" not in prop and "range" not in prop:
                    continue
                if prop.get("disabled") or prop.get("parsedOk") is False or prop.get("implicit"):
                    continue
                yield prop.get("name", ""), prop.get("value", "")
        inline = matched.get("inlineStyle") or {}
        for prop in inline.get("cssProperties", []) or []:
            yield prop.get("name", ""), prop.get("value", "")

    def var_usage(self, matched: dict[str, Any]) -> dict[str, str]:
        """Map css property -> custom property name, for properties authored as ``var(--x)``.

        Later (more specific) rules win, matching the cascade order CDP returns.
        """
        usage: dict[str, str] = {}
        direct: set[str] = set()  # properties authored on the element itself (var or not)
        # Rules arrive in cascade order (least → most specific); the last declaration wins, so a
        # later literal must *clear* a var() recorded from an earlier, weaker rule.
        for name, value in self._iter_rule_props(matched):
            if not name or name.startswith("--"):
                continue
            direct.add(name)
            m = _VAR_RE.search(value or "")
            if m:
                usage[name] = m.group(1)
            else:
                usage.pop(name, None)
        # inheritable properties may be authored on an ancestor — but only count them when the
        # element does not set the property itself (a direct `color: #fff` beats body's var()).
        for inh in matched.get("inherited", []) or []:
            for entry in inh.get("matchedCSSRules", []) or []:
                rule = entry.get("rule", {})
                if rule.get("origin") != "regular":
                    continue
                for prop in rule.get("style", {}).get("cssProperties", []) or []:
                    name = prop.get("name", "")
                    if name in INHERITED_PROPS and name not in usage and name not in direct:
                        m = _VAR_RE.search(prop.get("value", "") or "")
                        if m:
                            usage[name] = m.group(1)
        # `background: var(--x)` should be discoverable as background-color, etc. Only fill the
        # longhand when it was not authored directly (a direct longhand wins the cascade).
        for short, long in SHORTHANDS.items():
            if short in usage and long not in direct:
                usage.setdefault(long, usage[short])
        return usage

    def custom_properties(self, matched: dict[str, Any]) -> dict[str, str]:
        """Custom property definitions (``--name: value``) among matched rules."""
        defs: dict[str, str] = {}
        for name, value in self._iter_rule_props(matched):
            if name.startswith("--") and value:
                defs[name] = value.strip()
        return defs

    async def root_custom_properties(self) -> dict[str, str]:
        """Token definitions on html/body, resolved to computed values where possible."""
        defs: dict[str, str] = {}
        for sel in ("html", "body"):
            nid = await self.node_id(sel)
            if nid is None:
                continue
            matched = await self.matched_styles(nid)
            if matched:
                defs.update(self.custom_properties(matched))
        if not defs:
            return {}
        # Resolve var() chains and relative syntax through the browser.
        names = list(defs.keys())
        try:
            resolved: dict[str, str] = await self.page.evaluate(
                """(names) => {
                    const cs = getComputedStyle(document.documentElement);
                    const bcs = getComputedStyle(document.body);
                    const out = {};
                    for (const n of names) {
                      const v = (cs.getPropertyValue(n) || bcs.getPropertyValue(n) || '').trim();
                      if (v) out[n] = v;
                    }
                    return out;
                }""",
                names,
            )
        except Exception:
            resolved = {}
        return {n: resolved.get(n, v) for n, v in defs.items()}

    # -- states ----------------------------------------------------------------------------------

    async def computed(self, node_id: int) -> dict[str, str]:
        assert self.session
        res = await self.session.send("CSS.getComputedStyleForNode", {"nodeId": node_id})
        return {p["name"]: p["value"] for p in res.get("computedStyle", [])}

    async def state_styles(self, node_id: int, pseudo: str) -> dict[str, str] | None:
        """Computed values for STATE_PROPS with ``pseudo`` (e.g. ``hover``) forced on."""
        assert self.session
        try:
            await self.session.send("CSS.forcePseudoState", {"nodeId": node_id, "forcedPseudoClasses": [pseudo]})
            comp = await self.computed(node_id)
            return {p: comp.get(p, "") for p in STATE_PROPS}
        except Exception as exc:
            log.debug("forcePseudoState(%s) failed: %s", pseudo, exc)
            return None
        finally:
            try:
                await self.session.send("CSS.forcePseudoState", {"nodeId": node_id, "forcedPseudoClasses": []})
            except Exception:
                pass
