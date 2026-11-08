"""Exploration policy: which pages to visit next, and which to skip as redundant.

Safe by construction — the explorer only follows GET links (``<a href>``) and never clicks,
submits or types. Candidate links are scored for expected *design* information gain, and pages
whose style signature adds nothing new are skipped (PRD FR-1: optimize for design coverage, not
page count).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse

DESTRUCTIVE_RE = re.compile(
    r"(logout|log-out|signout|sign-out|delete|remove|unsubscribe|cancel|destroy|"
    r"archive|revoke|reset|deactivate|billing|checkout|purchase|pay(ment)?)",
    re.I,
)
LOW_VALUE_RE = re.compile(
    r"(privacy|terms|legal|cookie|gdpr|sitemap|\.pdf$|\.zip$|\.png$|\.jpg$|\.svg$|rss|feed|"
    r"/tag/|/tags/|/author/|/page/\d+|/\d{4}/\d{2}/)",
    re.I,
)
HIGH_VALUE_RE = re.compile(
    r"(pricing|features|product|docs|documentation|changelog|blog|customers|about|"
    r"dashboard|settings|integrations|templates|download|login|sign-?in|sign-?up|contact|"
    r"components|design|guide|explore|browse|search|rooms?|listings?|stays|gallery|catalog|"
    r"collections?|items?|products?|places|map)",
    re.I,
)
AUTH_RE = re.compile(r"(login|sign-?in|sign-?up|register|auth)", re.I)


def normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    p = urlparse(url)
    path = re.sub(r"/{2,}", "/", p.path) or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    # drop tracking params
    query = "&".join(kv for kv in p.query.split("&") if kv and not kv.lower().startswith(("utm_", "ref=", "fbclid")))
    return p._replace(path=path, query=query, fragment="").geturl()


def same_site(a: str, b: str) -> bool:
    ha, hb = urlparse(a).netloc.lower(), urlparse(b).netloc.lower()
    strip = lambda h: h[4:] if h.startswith("www.") else h  # noqa: E731
    return strip(ha) == strip(hb)


@dataclass
class Candidate:
    url: str
    text: str
    in_nav: bool
    score: float = 0.0


@dataclass
class ExplorerState:
    origin: str
    visited: set[str] = field(default_factory=set)
    queued: set[str] = field(default_factory=set)
    signatures: set[str] = field(default_factory=set)
    path_patterns: dict[str, int] = field(default_factory=dict)
    allow: list[re.Pattern[str]] = field(default_factory=list)
    deny: list[re.Pattern[str]] = field(default_factory=list)

    def allowed(self, url: str) -> bool:
        if not same_site(url, self.origin):
            return False
        if self.deny and any(p.search(url) for p in self.deny):
            return False
        if self.allow and not any(p.search(url) for p in self.allow):
            return False
        return True

    def path_pattern(self, url: str) -> str:
        """Collapse ids/slugs so /blog/post-a and /blog/post-b share a pattern."""
        parts = [p for p in urlparse(url).path.split("/") if p]
        out = []
        for i, part in enumerate(parts):
            if i >= 1 and (re.search(r"\d", part) or len(part) > 24 or "-" in part):
                out.append("*")
            else:
                out.append(part)
        return "/" + "/".join(out)

    def score(self, cand: Candidate) -> float:
        url = cand.url
        s = 1.0
        if cand.in_nav:
            s += 2.0
        if HIGH_VALUE_RE.search(url):
            s += 1.5
        if AUTH_RE.search(url):
            s += 0.5  # auth screens show form styling
        if LOW_VALUE_RE.search(url):
            s -= 2.0
        if DESTRUCTIVE_RE.search(url):
            s -= 10.0
        depth = len([p for p in urlparse(url).path.split("/") if p])
        s -= 0.3 * max(0, depth - 1)
        if urlparse(url).query:
            s -= 0.5
        # diminishing returns for the same route pattern
        seen = self.path_patterns.get(self.path_pattern(url), 0)
        s -= 1.2 * seen
        return s

    def enqueue(self, raw_links: list[dict], base_url: str) -> list[Candidate]:
        cands: list[Candidate] = []
        for link in raw_links:
            href = link.get("href") or ""
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:")):
                continue
            url = normalize_url(urljoin(base_url, href))
            if not url.startswith(("http://", "https://")):
                continue
            if url in self.visited or url in self.queued or not self.allowed(url):
                continue
            cand = Candidate(url=url, text=link.get("text", ""), in_nav=bool(link.get("inNav")))
            cand.score = self.score(cand)
            if cand.score <= -5:
                continue
            self.queued.add(url)
            cands.append(cand)
        return cands

    def mark_visited(self, url: str) -> None:
        url = normalize_url(url)
        self.visited.add(url)
        self.queued.discard(url)
        pat = self.path_pattern(url)
        self.path_patterns[pat] = self.path_patterns.get(pat, 0) + 1

    def novelty(self, signatures: list[str]) -> float:
        """Fraction of a page's style signatures not seen before."""
        if not signatures:
            return 0.0
        new = sum(1 for s in signatures if s not in self.signatures)
        return new / len(signatures)

    def absorb(self, signatures: list[str]) -> None:
        self.signatures.update(signatures)


def element_signature(el: dict) -> str:
    """Coarse style fingerprint of one element (tag/role + the properties that define its look)."""
    st = el.get("style", {})
    return "|".join(
        [
            el.get("tag", ""),
            el.get("role", ""),
            el.get("region", ""),
            st.get("font-size", ""),
            st.get("font-weight", ""),
            st.get("background-color", ""),
            st.get("color", ""),
            st.get("border-top-left-radius", ""),
            st.get("padding-left", ""),
            "b" if (st.get("border-top-style", "none") not in ("none", "")) else "",
            "s" if st.get("box-shadow", "none") != "none" else "",
        ]
    )


def style_signatures(elements: list[dict]) -> list[str]:
    """Distinct style fingerprints on a page, for dedupe / information-gain estimates."""
    return sorted({element_signature(el) for el in elements})


_ROLE_PRIORITY = {
    "button": 0,
    "textbox": 0,
    "combobox": 0,
    "checkbox": 1,
    "radio": 1,
    "switch": 1,
    "tab": 1,
    "menuitem": 1,
    "link": 2,
    "heading": 2,
    "dialog": 2,
    "row": 3,
    "listitem": 4,
}


def sample_for_inspection(elements: list[dict], limit: int) -> list[dict]:
    """Pick up to ``limit`` elements for (expensive) CDP inspection.

    One representative per style signature, interactive and structural elements first, then
    anything with a visible surface (border / shadow / background).
    """

    def priority(el: dict) -> tuple:
        st = el.get("style", {})
        surface = (
            st.get("box-shadow", "none") != "none"
            or st.get("border-top-style", "none") not in ("none", "")
            or (st.get("background-color", "") not in ("", "rgba(0, 0, 0, 0)", "transparent"))
        )
        role_p = _ROLE_PRIORITY.get(el.get("role", ""), 6)
        return (role_p if role_p < 6 else (5 if surface else 6), -el.get("bounds", {}).get("width", 0))

    seen: set[str] = set()
    picked: list[dict] = []
    for el in sorted(elements, key=priority):
        sig = element_signature(el)
        if sig in seen:
            continue
        seen.add(sig)
        picked.append(el)
        if len(picked) >= limit:
            break
    return picked
