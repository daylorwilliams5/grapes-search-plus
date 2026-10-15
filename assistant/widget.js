// Chat panel for the local assistant prototype (assistant/server.py).
// Loaded after the page's own script, so it uses the page's DATA, rowHTML,
// openDetail and toggleSave to show recommendations as ordinary result cards.
(function(){
  const history = [];
  let busy = false;

  const btn = document.createElement('button');
  btn.className = 'asst-open';
  btn.type = 'button';
  btn.textContent = 'Ask the assistant';
  btn.setAttribute('aria-controls', 'asstPanel');
  btn.setAttribute('aria-expanded', 'false');

  const panel = document.createElement('section');
  panel.id = 'asstPanel';
  panel.className = 'asst';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Funding assistant');
  panel.innerHTML = `
    <header class="asst-head">
      <div><h2>Funding assistant</h2><span class="asst-tag">Prototype</span></div>
      <button type="button" class="asst-x" aria-label="Close assistant">×</button>
    </header>
    <p class="asst-note">Describe your degree, field, citizenship, and what the funding is for.
      Suggestions only: confirm eligibility on the sponsor's page. Don't include your name or ID.</p>
    <div class="asst-log" aria-live="polite"></div>
    <form class="asst-form">
      <label for="asstQ" class="asst-sr">Your question</label>
      <textarea id="asstQ" rows="2" maxlength="1500"
        placeholder="e.g. 3rd-year sociology PhD, international student, need summer research funding"></textarea>
      <button type="submit">Ask</button>
    </form>`;
  document.body.append(btn, panel);

  const log = panel.querySelector('.asst-log');
  const form = panel.querySelector('form');
  const input = panel.querySelector('textarea');

  function show(open){
    panel.hidden = !open;
    btn.hidden = open;
    btn.setAttribute('aria-expanded', String(open));
    if (open) input.focus(); else btn.focus();
  }
  btn.addEventListener('click', () => show(true));
  panel.querySelector('.asst-x').addEventListener('click', () => show(false));

  function bubble(cls, text){
    const p = document.createElement('div');
    p.className = 'asst-msg ' + cls;
    p.textContent = text;
    log.append(p);
    log.scrollTop = log.scrollHeight;
    return p;
  }

  function cards(matches){
    const wrap = document.createElement('div');
    wrap.className = 'asst-cards';
    matches.forEach(m => {
      const r = DATA.find(x => x.id === m.id);
      if (!r) return;
      const item = document.createElement('div');
      item.className = 'asst-card';
      item.innerHTML = (m.why ? `<p class="asst-why">${esc(m.why)}</p>` : '') + rowHTML(r);
      wrap.append(item);
    });
    log.append(wrap);
  }

  // The cards are the page's own result rows: open details, or save, as in the list
  log.addEventListener('click', e => {
    const sv = e.target.closest('[data-save]');
    if (sv){ e.stopPropagation(); toggleSave(+sv.dataset.save); sv.classList.toggle('on'); return; }
    const row = e.target.closest('.row');
    if (row) openDetail(+row.dataset.id);
  });
  log.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.classList.contains('row')){
      e.preventDefault(); openDetail(+e.target.dataset.id);
    }
  });
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); form.requestSubmit(); }
  });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q || busy) return;
    busy = true;
    input.value = '';
    bubble('me', q);
    history.push({role: 'user', text: q});
    const wait = bubble('bot wait', 'Looking through GRAPES…');
    try {
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({messages: history}),
      });
      const data = await res.json();
      wait.remove();
      if (!res.ok) throw new Error(data.error || 'Something went wrong.');
      bubble('bot', data.reply || 'Here is what I found.');
      if (data.matches.length) cards(data.matches);
      history.push({role: 'assistant', text: data.reply, ids: data.matches.map(m => m.id)});
    } catch (err) {
      wait.remove();
      bubble('bot err', err.message || 'The assistant is unavailable right now.');
      history.pop();
    }
    busy = false;
    input.focus();
  });
})();
