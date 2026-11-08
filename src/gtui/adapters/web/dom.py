"""In-page DOM walker.

Runs inside the page via ``page.evaluate`` and returns every visible element with a curated set
of computed CSS properties, its bounds, implicit ARIA role and landmark region. Each element is
tagged with a ``data-gtui`` attribute so the CDP layer can address the same node later.

Only read operations are performed, plus the tagging attribute. No clicks, no form input.
"""

EXTRACT_JS = r"""
(opts) => {
  const MAX = (opts && opts.maxElements) || 4000;
  const PROPS = [
    'display','position','color','background-color','background-image',
    'font-family','font-size','font-weight','line-height','letter-spacing','text-transform',
    'text-decoration-line',
    'border-top-width','border-top-style','border-top-color',
    'border-top-left-radius','border-top-right-radius','border-bottom-right-radius','border-bottom-left-radius',
    'box-shadow','opacity',
    'padding-top','padding-right','padding-bottom','padding-left',
    'margin-top','margin-right','margin-bottom','margin-left',
    'row-gap','column-gap','cursor',
    'outline-width','outline-style','outline-color',
    'transition-duration','transition-property','transition-timing-function',
    'backdrop-filter','max-width','flex-direction','align-items','justify-content',
    'transform','filter'
  ];
  const SKIP = new Set(['script','style','noscript','template','link','meta','head','title','br','wbr']);
  const LANDMARKS = new Set(['nav','header','footer','aside','main']);
  const vw = window.innerWidth, vh = window.innerHeight;
  const out = [];
  let counter = 0;

  const implicitRole = (el, tag) => {
    const r = el.getAttribute('role');
    if (r) return r.split(/\s+/)[0];
    if (tag === 'button') return 'button';
    if (tag === 'a') return el.hasAttribute('href') ? 'link' : '';
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      if (t === 'button' || t === 'submit' || t === 'reset') return 'button';
      if (t === 'checkbox') return 'checkbox';
      if (t === 'radio') return 'radio';
      if (t === 'range') return 'slider';
      if (t === 'hidden') return '';
      return 'textbox';
    }
    if (tag === 'textarea') return 'textbox';
    if (tag === 'select') return 'combobox';
    if (/^h[1-6]$/.test(tag)) return 'heading';
    if (tag === 'nav') return 'navigation';
    if (tag === 'main') return 'main';
    if (tag === 'header') return 'banner';
    if (tag === 'footer') return 'contentinfo';
    if (tag === 'aside') return 'complementary';
    if (tag === 'img' || tag === 'svg' || tag === 'picture' || tag === 'video') return 'img';
    if (tag === 'p') return 'paragraph';
    if (tag === 'li') return 'listitem';
    if (tag === 'ul' || tag === 'ol') return 'list';
    if (tag === 'table') return 'table';
    if (tag === 'tr') return 'row';
    if (tag === 'td' || tag === 'th') return 'cell';
    if (tag === 'label') return 'label';
    if (tag === 'hr') return 'separator';
    if (tag === 'dialog') return 'dialog';
    return '';
  };

  const ownText = (el) => {
    let t = '';
    for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent;
    return t.replace(/\s+/g, ' ').trim();
  };

  const walk = (el, depth, parentKey, region) => {
    if (out.length >= MAX) return;
    const tag = el.tagName.toLowerCase();
    if (SKIP.has(tag)) return;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    const key = 'e' + (counter++);
    try { el.setAttribute('data-gtui', key); } catch (e) {}
    const style = {};
    for (const p of PROPS) style[p] = cs.getPropertyValue(p);
    const myRegion = LANDMARKS.has(tag) ? tag : region;
    const text = ownText(el);
    out.push({
      key, tag, role: implicitRole(el, tag), depth, parent: parentKey,
      text: text.slice(0, 120),
      textLength: Math.min(5000, (el.textContent || '').trim().length),
      classes: (typeof el.className === 'string' ? el.className : '').slice(0, 240),
      href: tag === 'a' ? (el.getAttribute('href') || '') : null,
      bounds: { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height },
      inViewport: r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw,
      region: myRegion,
      childCount: el.children.length,
      current: !!(el.getAttribute('aria-current') && el.getAttribute('aria-current') !== 'false')
               || el.getAttribute('aria-selected') === 'true' || el.getAttribute('data-state') === 'active',
      disabled: el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true',
      style,
    });
    if (tag === 'svg' || tag === 'video' || tag === 'canvas' || tag === 'iframe') return;
    for (const child of el.children) walk(child, depth + 1, key, myRegion);
  };

  walk(document.body, 0, null, '');

  const links = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href;
    if (!href || seen.has(href)) continue;
    seen.add(href);
    links.push({ href, text: (a.textContent || '').trim().slice(0, 80), inNav: !!a.closest('nav,header,aside') });
  }
  const bodyCs = getComputedStyle(document.body);
  const htmlCs = getComputedStyle(document.documentElement);
  return {
    title: document.title, url: location.href,
    scroll: { w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight },
    viewport: { w: vw, h: vh },
    elements: out, links,
    root: {
      bodyBackground: bodyCs.backgroundColor, htmlBackground: htmlCs.backgroundColor,
      color: bodyCs.color, fontFamily: bodyCs.fontFamily, fontSize: bodyCs.fontSize,
      colorScheme: htmlCs.colorScheme, htmlClass: document.documentElement.className || '',
    },
  };
}
"""

#: Properties re-read under forced pseudo states (hover / focus-visible).
STATE_PROPS = [
    "background-color",
    "color",
    "border-top-color",
    "border-top-width",
    "box-shadow",
    "opacity",
    "text-decoration-line",
    "outline-color",
    "outline-width",
    "outline-style",
    "transform",
    "filter",
    "background-image",
]
