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

// "Check the sponsor's page now": a button in each listing's details that runs
// the research agent on that listing and shows what the sponsor's page says today.
(function(){
  const results = {};   // per listing, for this visit
  const MON_FULL = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  function longDate(iso){
    const [y, m, d] = iso.split('-').map(Number);
    return `${MON_FULL[m - 1]} ${d}, ${y}`;
  }
  function quote(f){
    if (!f || !f.quote) return '';
    const src = f.source ? ` <a href="${esc(f.source)}" target="_blank" rel="noopener">Source</a>` : '';
    return `<blockquote>“${esc(f.quote)}”${src}</blockquote>`;
  }
  function render(box, r){
    let head, cls = 'asst-check-res';
    const dl = r.deadline;
    if (r.status === 'confirmed'){
      cls += ' ok';
      head = `Confirmed today: the deadline is <b>${longDate(dl.value)}</b>.`;
      const listed = DATA.find(x => x.id === box._id);
      if (listed && listed.deadlineSort !== dl.value) head += ` This listing says ${esc(r.listing_deadline || 'no date')}.`;
    } else if (r.status === 'not_posted'){
      cls += ' warn';
      head = `The sponsor hasn't posted the next deadline yet. The last one was ${longDate(dl.value)}.`;
    } else if (r.status === 'stopped'){
      cls += ' bad';
      head = 'The sponsor’s page says this program has ended or is paused.';
    } else {
      cls += ' warn';
      head = 'Couldn’t confirm a deadline on the sponsor’s page.';
    }
    let html = `<p class="asst-check-head">${head}</p>${quote(dl)}`;
    if (dl && dl.year_added) html += '<p class="asst-check-small">The page gives this date without a year; the next one is shown.</p>';
    if (r.amount) html += `<p>Amount: <b>${esc(r.amount.value)}</b></p>${quote(r.amount)}`;
    if (r.status !== 'confirmed' && r.notes) html += `<p class="asst-check-small">${esc(r.notes)}</p>`;
    html += `<p class="asst-check-small">Checked by the research agent just now. Cost: $${r.cost.toFixed(3)}.</p>`;
    box.className = cls;
    box.innerHTML = html;
  }
  function addCheck(id){
    const body = document.getElementById('dBody');
    if (!body || body.querySelector('.asst-check')) return;
    const wrap = document.createElement('section');
    wrap.className = 'asst-check';
    wrap.innerHTML = `<button type="button" class="asst-check-btn">Check the sponsor’s page now</button>
      <div class="asst-check-res" aria-live="polite"></div>`;
    body.prepend(wrap);
    const btn = wrap.querySelector('button'), box = wrap.querySelector('.asst-check-res');
    box._id = id;
    if (results[id]){ btn.hidden = true; render(box, results[id]); return; }
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.textContent = 'Reading the sponsor’s page… (about 20–40 seconds)';
      try {
        const res = await fetch('/api/check', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                               body: JSON.stringify({id})});
        if (res.status === 404) throw new Error('Live checks are off. Install requests, beautifulsoup4 and python-dateutil, then restart the assistant.');
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'The check failed.');
        results[id] = data;
        btn.hidden = true;
        render(box, data);
      } catch (err) {
        btn.disabled = false;
        btn.textContent = 'Try again';
        box.className = 'asst-check-res bad';
        box.textContent = err.message || 'The check failed.';
      }
    });
  }
  const open = window.openDetail;
  window.openDetail = function(id){ open(id); addCheck(id); };
})();
