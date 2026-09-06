// Small helpers shared by every page. No framework: fetch, toasts, and a few data- attributes.
//
//   hippo.api('POST', '/api/thing', {a: 1})     -> parsed JSON (throws on error, shows a toast)
//   hippo.toast('Saved', 'ok')                 -> a small message bottom-right
//   <button data-post="/api/x" data-refresh="2000">   -> POSTs, then reloads the page after N ms
//   <button data-delete="/api/x" data-confirm="Sure?" data-then="/">  -> DELETEs after confirming, then navigates

window.hippo = (() => {
  async function api(method, url, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const resp = await fetch(url, opts);
    let data = null;
    try { data = await resp.json(); } catch (_) { data = null; }
    if (!resp.ok) {
      const message = (data && (data.error || data.detail)) || `${resp.status} ${resp.statusText}`;
      toast(typeof message === 'string' ? message : JSON.stringify(message), 'bad');
      throw new Error(message);
    }
    return data;
  }

  function toast(message, kind = '') {
    const box = document.getElementById('toasts');
    if (!box) return;
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.textContent = message;
    box.appendChild(el);
    setTimeout(() => el.remove(), 4500);
  }

  function fmt(value, digits = 3) {
    if (value === null || value === undefined || value === '') return '–';
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(digits) : String(value);
  }

  // htmx swaps nothing on a 4xx/5xx or a network failure, so without this a failed poll or a
  // crashed /ask would leave the page silently unchanged. One toast per failure makes it visible.
  document.body.addEventListener('htmx:responseError', (e) => {
    toast(`${e.detail.xhr.status} ${e.detail.xhr.statusText || 'error'} from ${e.detail.pathInfo.requestPath}`, 'bad');
  });
  document.body.addEventListener('htmx:sendError', (e) => {
    toast(`Cannot reach hippo (${e.detail.pathInfo.requestPath}). Is the server still running?`, 'bad');
  });

  // Polled tables are replaced wholesale. If that happens between mousedown and mouseup on a
  // Delete button, the click lands on the new table and does nothing; a focused button or link
  // inside the target means the user is mid-click, so skip that one swap (the next poll catches up).
  document.body.addEventListener('htmx:beforeSwap', (e) => {
    const active = document.activeElement;
    if (active && active !== document.body && e.detail.target && e.detail.target.contains(active)) {
      e.detail.shouldSwap = false;
    }
  });

  document.addEventListener('click', async (event) => {
    const post = event.target.closest('[data-post]');
    if (post) {
      event.preventDefault();
      post.disabled = true;
      try {
        await api('POST', post.dataset.post, post.dataset.body ? JSON.parse(post.dataset.body) : undefined);
        toast(post.dataset.message || 'Started', 'ok');
        const wait = Number(post.dataset.refresh || 0);
        if (post.dataset.then) setTimeout(() => (window.location = post.dataset.then), wait);
        else if (wait) setTimeout(() => window.location.reload(), wait);
      } finally { post.disabled = false; }
      return;
    }
    const del = event.target.closest('[data-delete]');
    if (del) {
      event.preventDefault();
      if (del.dataset.confirm && !window.confirm(del.dataset.confirm)) return;
      await api('DELETE', del.dataset.delete);
      toast('Deleted', 'ok');
      if (del.dataset.then) window.location = del.dataset.then; else window.location.reload();
    }
  });

  return { api, toast, fmt };
})();
