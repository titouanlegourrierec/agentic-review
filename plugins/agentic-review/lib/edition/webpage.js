(() => {
  const DATA = JSON.parse(document.getElementById('data').textContent);
  // Prefix of every browser-storage key (review.json edition.storage_key), so two reviews never share marks.
  const KEY = DATA.store || 'review';
  const WEB = DATA.mode === 'web';
  const LABEL = { yellow: 'Method', blue: 'Data and protocol', green: 'Result cited',
                  red: 'Limitation or red flag', purple: 'Correction or disagreement with the paper' };
  const esc = s => String(s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  // Only web and Zotero links, and the PDFs of a shared package (papers/...), are ever written into the preview.
  const safe = u => (/^(https?:|zotero:|papers\/|viewer\.html\?)/i.test(String(u || '').trim()) ? String(u).trim() : '');
  const SHARE = DATA.mode === 'share';
  const LOCAL = 'a[href^="zotero:"], a[href^="papers/"], a[href^="viewer.html"]';
  const isPdf = h => h.startsWith('papers/') || h.startsWith('viewer.html');
  // A shared package served by its launcher (http://localhost) opens PDFs in viewer.html, which draws the
  // highlights; opened as a file, links keep the PDF itself (the viewer cannot load files from disk).
  if (SHARE && /^https?:$/.test(location.protocol)) {
    document.querySelectorAll('a[href^="papers/"]').forEach(a => {
      const [file, frag] = a.getAttribute('href').split('#');
      const page = /^page=(\d+)$/.test(frag || '') ? frag.slice(5) : '';
      const c = a.dataset.c ? DATA.cites[a.dataset.c] : null;
      const ann = c && c.a ? c.a : '';
      a.setAttribute('href', `viewer.html?file=${encodeURIComponent(file)}` + (page ? `&page=${page}` : '') +
        (ann ? `&ann=${encodeURIComponent(ann)}` : ''));
    });
  }
  // Browser storage can be unavailable (private windows, blocked site data): every read and write is guarded.
  const store = {
    get(k, fallback) { try { const v = localStorage.getItem(k); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* not persisted */ } },
    del(k) { try { localStorage.removeItem(k); } catch (e) { /* nothing stored */ } },
  };

  const toastEl = document.querySelector('.toast');
  let toastTimer = null;
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, 1600);
  }

  // Passages already opened in Zotero get a ✓ (kept per browser and per address of the page).
  const OPENED = `${KEY}-opened`;
  const opened = new Set(store.get(OPENED, []));
  const markOpened = () => document.querySelectorAll(LOCAL).forEach(a => {
    a.classList.toggle('opened', opened.has(a.getAttribute('href')));
  });
  markOpened();
  document.addEventListener('click', e => {
    const a = e.target.closest(LOCAL);
    if (!a) return;
    opened.add(a.getAttribute('href'));
    store.set(OPENED, [...opened]);
    markOpened();
    if (current && !pop.hidden) pop.innerHTML = render(current);   // show "✓ opened" right away
  });
  const clear = document.querySelector('.clear-opened');
  if (clear) clear.addEventListener('click', () => { opened.clear(); store.del(OPENED); markOpened(); toast('✓ marks cleared'); });

  // Passage previews: each citation carries data-c, which points to the paper and the highlight it opens.
  const pop = document.querySelector('.pop');
  let hideTimer = null;
  let current = null;

  function renderWeb(p, href) {
    const host = /arxiv\.org/i.test(href) ? 'arXiv page' : /doi\.org/i.test(href) ? 'DOI page' : 'source page';
    let h = `<div class="pk"><i class="sw dotted"></i>Opens the paper's ${host}</div>`;
    if (p.c) h += `<blockquote class="claim">${esc(p.c)}</blockquote>`;
    if (p.cc && p.cc.length) {
      h += '<ul class="cc">' + p.cc.map(x => `<li><span class="verdict ${esc(x.v)}">${esc(x.l)}</span> ${esc(x.q)}` +
        `${x.e ? `<q>${esc(x.e)}</q>` : ''}</li>`).join('');
      if (p.n > p.cc.length) h += `<li class="more">and ${p.n - p.cc.length} more checked claims</li>`;
      h += '</ul>';
    }
    const where = [p.v, p.y].filter(Boolean).join(', ');
    h += `<p class="pp"><b>${esc(p.l)}</b> — ${esc(p.t)}${where ? ` · ${esc(where)}` : ''}</p>`;
    const go = safe(href);
    return h + (go ? `<div class="pa"><a href="${esc(go)}" target="_blank" rel="noopener">Open ↗</a></div>` : '');
  }

  function render(a) {
    const c = DATA.cites[a.dataset.c];
    if (!c) return null;
    const p = DATA.papers[c.k] || {};
    const n = c.a ? DATA.anns[c.a] : null;
    const href = a.getAttribute('href');
    if (WEB) return renderWeb(p, href);
    let kind;
    if (n) kind = `<i class="sw ${esc(n.c)}"></i>${LABEL[n.c] || 'Highlight'}${n.p ? ` · page ${esc(n.p)}` : ''}`;
    else if (href.startsWith('zotero://open-pdf')) kind = '<i class="sw grey"></i>Opens the paper\'s first page in Zotero';
    else if (href.startsWith('zotero://select')) kind = '<i class="sw grey"></i>No PDF in Zotero: opens its record';
    else if (isPdf(href)) kind = '<i class="sw grey"></i>Opens the paper\'s PDF at its first page';
    else if (SHARE) kind = '<i class="sw dotted"></i>No PDF in this package: opens the publisher\'s page';
    else kind = '<i class="sw dotted"></i>Not in your Zotero library: opens the publisher\'s page';
    if (opened.has(href)) kind += '<span class="done">✓ opened</span>';
    let h = `<div class="pk">${kind}</div>`;
    if (n && n.x) h += `<blockquote class="${esc(n.c)}">${esc(n.x)}</blockquote>`;
    else if (n && n.i) h += `<blockquote class="${esc(n.c)} area">Highlighted area (figure or table)</blockquote>`;
    if (n && n.m) h += `<p class="pm">${esc(n.m)}</p>`;
    h += `<p class="pp"><b>${esc(p.l)}</b> — ${esc(p.t)}</p>`;
    const pdf = isPdf(href);
    const web = !href.startsWith('zotero:') && !pdf;
    const open = pdf ? 'Open the PDF ↗' : web ? 'Open ↗' : 'Open in Zotero';
    const actions = [`<a href="${esc(href)}"${web || pdf ? ' target="_blank" rel="noopener"' : ''}>${open}</a>`];
    if (safe(p.u) && !web) actions.push(`<a href="${esc(safe(p.u))}" target="_blank" rel="noopener">Publisher ↗</a>`);
    return h + `<div class="pa">${actions.join('')}</div>`;
  }

  function place(a) {
    const r = a.getBoundingClientRect();
    const w = pop.offsetWidth;
    const h = pop.offsetHeight;
    const left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, document.documentElement.clientWidth - w - 8));
    let top = r.bottom + 8;
    if (top + h > window.innerHeight - 8 && r.top - h - 8 > 0) top = r.top - h - 8;
    pop.style.left = `${left + window.scrollX}px`;
    pop.style.top = `${top + window.scrollY}px`;
  }

  function show(a) {
    clearTimeout(hideTimer);
    if (current === a && !pop.hidden) return;
    const h = render(a);
    if (!h) return;
    current = a;
    pop.innerHTML = h;
    pop.hidden = false;
    place(a);
  }

  function hide(delay) {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { pop.hidden = true; current = null; }, delay);
  }

  document.addEventListener('mouseover', e => {
    const a = e.target.closest('a[data-c]');
    if (a) show(a);
    else if (current && !e.target.closest('.pop')) hide(250);
  });
  document.addEventListener('focusin', e => {
    const a = e.target.closest('a[data-c]');
    if (a) show(a);
  });
  document.addEventListener('focusout', e => { if (e.target.closest('a[data-c]')) hide(250); });
  pop.addEventListener('mouseenter', () => clearTimeout(hideTimer));
  pop.addEventListener('mouseleave', () => hide(200));
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    hide(0);
    if (nav.classList.contains('open')) { sheet(false); tocbtn.focus(); }
    hideTip();
  });

  // Heading anchors: § copies a link to the section.
  document.querySelectorAll('main h2[id], main h3[id]').forEach(h => {
    const a = document.createElement('a');
    a.className = 'anchor';
    a.href = `#${h.id}`;
    a.textContent = '§';
    a.setAttribute('aria-label', 'Copy a link to this section');
    a.addEventListener('click', e => {
      e.preventDefault();
      history.replaceState(null, '', `#${h.id}`);
      const done = () => toast('Link to this section copied');
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(location.href).then(done, () => toast('Link in the address bar'));
      else toast('Link in the address bar');
    });
    h.appendChild(a);
  });

  // Contents: highlight the section being read and unfold only its subsections. On narrow screens the list opens as
  // a sheet from the bar at the top, which also names the section being read.
  const tocLinks = new Map([...document.querySelectorAll('nav.toc a')].map(a => [a.getAttribute('href').slice(1), a]));
  const heads = [...document.querySelectorAll('main h2[id], main h3[id]')].filter(h => tocLinks.has(h.id));
  const nav = document.querySelector('nav.toc');
  const bar = document.querySelector('.progress');
  const totop = document.querySelector('.totop');
  const cursec = document.querySelector('.cursec');
  const tocbtn = document.querySelector('.tocbtn');
  const scrim = document.querySelector('.scrim');
  const narrow = window.matchMedia('(max-width: 960px)');
  function sheet(open) {
    nav.classList.toggle('open', open);
    scrim.hidden = !open;
    tocbtn.setAttribute('aria-expanded', String(open));
    if (open) (nav.querySelector('a.on') || nav.querySelector('a')).focus({ preventScroll: true });
  }
  tocbtn.addEventListener('click', () => sheet(!nav.classList.contains('open')));
  cursec.addEventListener('click', () => sheet(true));
  scrim.addEventListener('click', () => sheet(false));
  nav.addEventListener('click', e => { if (e.target.closest('a') && narrow.matches) sheet(false); });
  narrow.addEventListener('change', () => sheet(false));
  let ticking = false;
  function onScroll() {
    ticking = false;
    const doc = document.documentElement;
    const max = doc.scrollHeight - window.innerHeight;
    bar.style.transform = `scaleX(${max > 0 ? Math.min(1, window.scrollY / max) : 0})`;
    totop.classList.toggle('show', window.scrollY > 900);
    if (current && !pop.hidden) place(current);
    let cur = heads[0];
    for (const h of heads) {
      if (h.getBoundingClientRect().top < 140) cur = h;
      else break;
    }
    tocLinks.forEach(a => a.classList.remove('on'));
    nav.querySelectorAll('li.open').forEach(li => li.classList.remove('open'));
    if (!cur) return;
    const link = tocLinks.get(cur.id);
    link.classList.add('on');
    const top = link.closest('nav.toc > ol > li');
    if (top) top.classList.add('open');
    cursec.textContent = link.textContent.replace(/^(\S+)(?=[A-Z])/, '$1 ');
    if (narrow.matches) return;             // the sheet is hidden: keep the page still
    const r = link.getBoundingClientRect();
    const nr = nav.getBoundingClientRect();
    if (r.top < nr.top || r.bottom > nr.bottom) nav.scrollTop += r.top < nr.top ? r.top - nr.top - 8 : r.bottom - nr.bottom + 8;
  }
  window.addEventListener('scroll', () => { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, { passive: true });
  onScroll();
  totop.addEventListener('click', e => { e.preventDefault(); window.scrollTo({ top: 0, behavior: 'smooth' }); });

  // Light or dark: follows the system until the button is used, then remembers the choice.
  const themeBtn = document.querySelector('button.theme');
  const isDark = () => document.documentElement.dataset.theme === 'dark' ||
    (!document.documentElement.dataset.theme && window.matchMedia('(prefers-color-scheme: dark)').matches);
  const label = () => { themeBtn.querySelector('span').textContent = isDark() ? 'Light' : 'Dark'; };
  label();
  themeBtn.addEventListener('click', () => {
    const next = isDark() ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(`${KEY}-theme`, next); } catch (e) { /* not persisted */ }   // raw: read before the CSS loads
    label();
  });

  // "How the links work" stays folded once folded.
  const howto = document.querySelector('details.howto');
  if (howto) {
    if (store.get(`${KEY}-howto-open`, false) === true) howto.open = true;
    howto.addEventListener('toggle', () => store.set(`${KEY}-howto-open`, howto.open));
  }

  // Catalogue filter.
  const filter = document.querySelector('.filter');
  if (filter) {
    filter.addEventListener('input', () => {
      const q = filter.value.trim().toLowerCase();
      document.querySelectorAll('.catalogue-box tbody tr').forEach(tr => {
        tr.hidden = Boolean(q) && !tr.textContent.toLowerCase().includes(q);
      });
    });
  }
  // Glossary: the first use of a term in each paragraph, list item, table cell or caption explains itself on hover,
  // keyboard focus or tap.
  const GLOSS = DATA.gloss || [];
  const gtip = document.querySelector('.gtip');
  let tipFor = null;
  function hideTip() { gtip.hidden = true; tipFor = null; }
  // A pattern the browser cannot compile is skipped, not allowed to break the page.
  const USABLE = [];
  GLOSS.forEach((g, i) => { try { new RegExp(g.p); USABLE.push(i); } catch (e) { /* skipped */ } });
  if (USABLE.length) {
    const rx = new RegExp(USABLE.map(i => `(${GLOSS[i].p})`).join('|'), 'g');
    const BLOCK = 'p, li, td, figcaption';
    const SKIP = 'a, code, h1, h2, h3, h4, th, svg, .gl, .verdict, .chips, .citedin, .rlabel';
    document.querySelectorAll('main p, main li, main td, main figcaption').forEach(block => {
      if (block.closest('.reflist, .catalogue-box, .glance, .tiles, .howto')) return;
      const nodes = [];
      const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT, { acceptNode: n =>
        n.parentElement.closest(BLOCK) === block && !n.parentElement.closest(SKIP)
          ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
      while (walker.nextNode()) nodes.push(walker.currentNode);
      const seen = new Set();
      nodes.forEach(node => {
        const text = node.nodeValue;
        let m, last = 0, frag = null;
        rx.lastIndex = 0;
        while ((m = rx.exec(text))) {
          if (!m[0]) { rx.lastIndex += 1; continue; }
          const i = USABLE[m.slice(1).findIndex(x => x !== undefined)];
          if (seen.has(i)) continue;
          seen.add(i);
          frag = frag || document.createDocumentFragment();
          frag.append(text.slice(last, m.index));
          const span = document.createElement('span');
          span.className = 'gl';
          span.tabIndex = 0;
          span.dataset.g = i;
          span.textContent = m[0];
          frag.append(span);
          last = m.index + m[0].length;
        }
        if (frag) { frag.append(text.slice(last)); node.replaceWith(frag); }
      });
    });
  }
  function showTip(el) {
    const g = GLOSS[el.dataset.g];
    if (!g) return;
    tipFor = el;
    gtip.innerHTML = `<b>${esc(g.t)}</b> ${esc(g.d)}`;
    gtip.hidden = false;
    const r = el.getBoundingClientRect();
    const w = gtip.offsetWidth;
    const h = gtip.offsetHeight;
    const left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, document.documentElement.clientWidth - w - 8));
    let top = r.bottom + 6;
    if (top + h > window.innerHeight - 8 && r.top - h - 6 > 0) top = r.top - h - 6;
    gtip.style.left = `${left + window.scrollX}px`;
    gtip.style.top = `${top + window.scrollY}px`;
  }
  document.addEventListener('mouseover', e => {
    const g = e.target.closest('.gl');
    if (g) showTip(g);
    else if (tipFor && !e.target.closest('.gtip')) hideTip();
  });
  document.addEventListener('focusin', e => { const g = e.target.closest('.gl'); if (g) showTip(g); });
  document.addEventListener('focusout', e => { if (e.target.closest('.gl')) hideTip(); });
  document.addEventListener('click', e => {
    const g = e.target.closest('.gl');
    if (g) { if (tipFor !== g) showTip(g); }
    else if (tipFor && !e.target.closest('.gtip')) hideTip();
  });

  // BibTeX: copy one entry, or download every cited entry as one file.
  let BIB = {};
  try { BIB = JSON.parse(document.getElementById('bib').textContent); } catch (e) { /* no entries */ }
  function copyText(text, done) {
    const fallback = () => {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.append(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      ta.remove();
      toast(ok ? done : 'Copy failed: select the entry in the downloaded file instead');
    };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(() => toast(done), fallback);
    else fallback();
  }
  document.addEventListener('click', e => {
    const b = e.target.closest('button.bib');
    if (b && BIB[b.dataset.bib]) copyText(BIB[b.dataset.bib], 'BibTeX entry copied');
  });
  const dl = document.querySelector('button.bibdl');
  if (dl) dl.addEventListener('click', () => {
    const text = Object.values(BIB).join('\n\n') + '\n';
    const url = URL.createObjectURL(new Blob([text], { type: 'application/x-bibtex' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = DATA.bib || 'references.bib';
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    toast(`${Object.keys(BIB).length} entries saved as ${a.download}`);
  });
})();
