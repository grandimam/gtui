"""Kitchen-sink HTML preview: renders the profile's tokens and recipes with no target app, so a
profile can be eyeballed (and later screenshot-evaluated) in isolation."""

from __future__ import annotations

import html

from gtui.export.theme import render_css
from gtui.ir.schema import AestheticProfile, ComponentRecipe, is_unknown


def _val(v, kind: str = "color") -> str:
    if v is None:
        return "inherit"
    if isinstance(v, str):
        if v in ("transparent", "none", "inherit"):
            return v
        if v.startswith("#") or v.startswith("rgb") or v.startswith("oklch"):
            return v
        if kind == "color" and "." in v:
            return f"var(--color-{v.replace('.', '-').replace('_', '-')})"
        if kind == "radius":
            return "9999px" if v == "full" else f"var(--radius-{v})"
        if kind == "font":
            return f"var(--text-{v})"
        return v
    if isinstance(v, (int, float)):
        return f"{v:g}px"
    return str(v)


def _recipe_css(r: ComponentRecipe, cls: str) -> str:
    p = r.properties
    rules = []
    if "height" in p:
        rules.append(f"height:{p['height']}px")
    if "padding_x" in p:
        rules.append(f"padding:0 {p['padding_x']}px")
    if "padding" in p and r.kind == "card":
        rules.append(f"padding:{p['padding']}px")
    if "font" in p:
        rules.append(f"font-size:{_val(p['font'], 'font')}")
    if p.get("weight"):
        rules.append(f"font-weight:{p['weight']}")
    if "radius" in p:
        rules.append(f"border-radius:{_val(p['radius'], 'radius')}")
    if "background" in p and p["background"] not in (None, "inherit"):
        rules.append(f"background:{_val(p['background'])}")
    if p.get("text"):
        rules.append(f"color:{_val(p['text'])}")
    b = p.get("border")
    if isinstance(b, dict):
        rules.append(f"border:{b.get('width', 1)}px solid {_val(b.get('color'))}")
    else:
        rules.append("border:1px solid transparent" if r.kind in ("button", "input") else "border:none")
    if p.get("shadow") and p["shadow"] != "none":
        rules.append(f"box-shadow:{p['shadow']}")
    if p.get("text_transform"):
        rules.append(f"text-transform:{p['text_transform']}")
    if p.get("letter_spacing_em"):
        rules.append(f"letter-spacing:{p['letter_spacing_em']}em")
    if p.get("decoration"):
        rules.append(f"text-decoration:{p['decoration']}")
    css = f".{cls}{{{';'.join(rules)}}}"
    hover = r.states.get("hover")
    if hover:
        hr = []
        for prop, v in hover.changes.items():
            if prop in ("background-color", "color", "border-top-color"):
                target = {"background-color": "background", "color": "color", "border-top-color": "border-color"}[prop]
                hr.append(f"{target}:{_val(v)}")
            elif prop in ("box-shadow", "opacity", "text-decoration-line", "transform"):
                target = "text-decoration" if prop == "text-decoration-line" else prop
                hr.append(f"{target}:{v}")
        if hr:
            css += f".{cls}:hover{{{';'.join(hr)}}}"
    focus = r.states.get("focus-visible")
    if focus:
        fr = []
        for prop, v in focus.changes.items():
            if prop in ("box-shadow", "outline-color", "outline-width", "outline-style", "border-top-color"):
                target = "border-color" if prop == "border-top-color" else prop
                fr.append(f"{target}:{_val(v) if 'color' in prop else v}")
        if fr:
            css += f".{cls}:focus-visible{{{';'.join(fr)}}}"
    return css


def render_preview(profile: AestheticProfile) -> str:
    t = profile.tokens
    theme = render_css(profile)
    recipe_css = []
    buttons = [c for c in profile.components if c.kind == "button"]
    for b in buttons:
        recipe_css.append(_recipe_css(b, f"btn-{b.variant}"))
    inputs = profile.recipes("input")
    if inputs:
        recipe_css.append(_recipe_css(inputs[0], "input"))
    cards = profile.recipes("card")
    if cards:
        recipe_css.append(_recipe_css(cards[0], "card"))
    badges = profile.recipes("badge")
    if badges:
        recipe_css.append(_recipe_css(badges[0], "badge"))
    navs = [c for c in profile.components if c.kind == "nav_item"]
    for n in navs:
        recipe_css.append(_recipe_css(n, f"nav-{n.variant}"))
    links = profile.recipes("link")
    if links:
        recipe_css.append(_recipe_css(links[0], "link"))
    for h in [c for c in profile.components if c.kind == "heading"]:
        p = h.properties
        recipe_css.append(
            f".{h.variant}{{font-size:{p.get('size_px', 16)}px;font-weight:{p.get('weight', 600)};"
            f"line-height:{p.get('line_height') or 1.2};letter-spacing:{p.get('letter_spacing_em', 0)}em;"
            f"color:{_val(p.get('text'))};margin:0}}"
        )

    def swatch(role: str) -> str:
        tok = t.colors[role]
        return (
            f'<div class="sw"><div class="chip" style="background:{tok.value}"></div>'
            f"<div><b>{role}</b><br><code>{tok.value}</code> · conf {tok.confidence:.2f}"
            + (f"<br><small>{html.escape(', '.join(tok.source_names))}</small>" if tok.source_names else "")
            + "</div></div>"
        )

    swatches = "".join(swatch(r) for r in t.colors)
    scale_rows = "".join(
        f'<div class="row"><code style="width:4rem">{k}</code>'
        f'<span style="font-size:{s.size:g}px;line-height:{(s.line_height if not is_unknown(s.line_height) else 1.3)};">'
        f"The quick brown fox — {s.size:g}px</span><small>{', '.join(map(str, s.weights))} · {', '.join(s.roles)}</small></div>"
        for k, s in t.typography.scale.items()
    )
    spacing = "".join(
        f'<div class="bar" style="width:{v}px" title="{v}px"></div><code>{v}</code>' for v in t.spacing.scale
    )
    radii = "".join(
        f'<div class="rad" style="border-radius:{"9999px" if k == "full" else f"{v.value:g}px"}"><code>{k}</code></div>'
        for k, v in t.radius.items()
    )
    shadows = "".join(
        f'<div class="shd" style="box-shadow:{v.value}"><code>{k}</code></div>' for k, v in t.shadows.items()
    )
    btns = "".join(
        f'<button class="btn-{b.variant}">{b.variant.title()}</button>' for b in buttons if b.variant != "icon"
    )
    nav_html = "".join(f'<a class="nav-{n.variant}" href="#">{n.variant}</a>' for n in navs) or ""
    principles = "".join(
        f"<li><b>{html.escape(p.statement)}</b> <small>({p.kind}, conf {p.confidence:.2f})</small>"
        + (f"<br><small>{html.escape(p.rationale)}</small>" if p.rationale else "")
        + "</li>"
        for p in profile.principles
    )
    body_font = (
        "var(--font-sans)"
        if "sans" in t.typography.families and not is_unknown(t.typography.families["sans"])
        else "system-ui"
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>gtui preview — {html.escape(profile.metadata.name)}</title>
<style>
{theme}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--color-surface-base,#fff);color:var(--color-text-primary,#111);font-family:{body_font};font-size:var(--text-base,14px);line-height:var(--text-base--line-height,1.5)}}
main{{max-width:960px;margin:0 auto;padding:40px 24px;display:grid;gap:40px}}
section>h2{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--color-text-secondary,#666);margin:0 0 16px;font-weight:600}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}}
.sw{{display:flex;gap:10px;align-items:center;font-size:12px}}.chip{{width:40px;height:40px;border-radius:var(--radius-md,6px);border:1px solid var(--color-border-subtle,#ddd);flex:none}}
.row{{display:flex;align-items:baseline;gap:16px;padding:6px 0;border-bottom:1px solid var(--color-border-subtle,#eee)}}.row small{{margin-left:auto;color:var(--color-text-secondary,#666)}}
.bars{{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center}}.bar{{height:12px;background:var(--color-accent-primary,#5e6ad2);border-radius:2px}}
.rads,.shds{{display:flex;gap:16px;flex-wrap:wrap}}.rad{{width:72px;height:56px;border:1px solid var(--color-border-strong,var(--color-border-subtle,#999));display:grid;place-items:center;background:var(--color-surface-raised,transparent)}}
.shd{{width:96px;height:64px;border-radius:var(--radius-md,6px);background:var(--color-surface-raised,#fff);display:grid;place-items:center}}
.controls{{display:flex;gap:10px;flex-wrap:wrap;align-items:center}}button{{font:inherit;cursor:pointer}}input{{font:inherit;width:220px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}}
.card p{{margin:6px 0 0;color:var(--color-text-secondary,#666)}}
.badges{{display:flex;gap:8px;flex-wrap:wrap}}.badge{{display:inline-flex;align-items:center}}
nav.preview{{display:flex;gap:4px;align-items:center}}nav.preview a{{display:inline-flex;align-items:center;text-decoration:none}}
ul.principles{{padding-left:18px;display:grid;gap:8px}} code{{font-family:var(--font-mono,ui-monospace,monospace);font-size:.9em}}
{"".join(recipe_css)}
</style></head><body><main>
<header><div style="font-size:12px;color:var(--color-text-secondary)">gtui profile · {html.escape(profile.metadata.source)}</div>
<h1 class="h1" style="margin:4px 0 8px">{html.escape(profile.metadata.name)}</h1>
<div style="color:var(--color-text-secondary)">{html.escape(profile.character.summary or "")}</div></header>
<section><h2>Palette</h2><div class="grid">{swatches}</div></section>
<section><h2>Type scale</h2>{scale_rows}</section>
<section><h2>Spacing ({t.spacing.base if not is_unknown(t.spacing.base) else "?"}px grid)</h2><div class="bars">{spacing}</div></section>
<section><h2>Radius</h2><div class="rads">{radii}</div></section>
{"<section><h2>Shadows</h2><div class='shds'>" + shadows + "</div></section>" if shadows else ""}
<section><h2>Buttons</h2><div class="controls">{btns}</div></section>
{"<section><h2>Navigation</h2><nav class='preview'>" + nav_html + "</nav></section>" if nav_html else ""}
{"<section><h2>Input</h2><div class='controls'><input class='input' placeholder='Search…'><input class='input' value='Focused state via :focus-visible'></div></section>" if inputs else ""}
{"<section><h2>Cards</h2><div class='cards'><div class='card'><b>Card title</b><p>Body copy inside a contained surface.</p></div><div class='card'><b>Second card</b><p>Same recipe; consistent padding and radius.</p><div class='badges' style='margin-top:10px'><span class='badge'>Badge</span><span class='badge'>New</span></div></div></div></section>" if cards else ""}
{"<section><h2>Badges</h2><div class='badges'><span class='badge'>Default</span><span class='badge'>Beta</span><span class='badge'>12</span></div></section>" if badges else ""}
<section><h2>Text</h2><h2 class="h2" style="text-transform:none;letter-spacing:inherit">Heading two</h2><h3 class="h3">Heading three</h3>
<p>Body text with an <a class="link" href="#">inline link</a> and <span style="color:var(--color-text-secondary)">secondary text</span>. <code>code sample</code></p></section>
<section><h2>Principles</h2><ul class="principles">{principles}</ul></section>
</main></body></html>
"""
