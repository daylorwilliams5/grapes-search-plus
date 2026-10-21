// The assistant for GRAPES Search+ (assistant/server.py).
// When the server is online with a passcode, nothing changes until a staff
// member opens the page with ?demo and enters it (kept for the browser tab).
// Loaded after the page's own script, so it uses the page's DATA, state,
// render, passes, rowHTML, openDetail and toggleSave.

// The search box asks the assistant instead of matching keywords. Its picks
// appear as "Best fits" above the full list, which keeps every filter.
function startSearch(){
  const history = [];
  let picks = null, reply = '', busy = false;

  // A fresh copy of the box drops the page's search-as-you-type
  const old = document.getElementById('qi');
  const input = old.cloneNode(true);
  old.replaceWith(input);
  input.value = state.q;
  input.placeholder = 'e.g. 3rd-year sociology PhD, international student, need summer research funding';
  input.maxLength = 1500;
  document.querySelector('label[for=qi]').textContent = 'Describe what you need';
  document.getElementById('qclr').setAttribute('aria-label', 'Clear and start over');
  input.addEventListener('input', () => document.getElementById('qclr').classList.toggle('show', !!input.value));
  state.q = '';
  if (state.sort === 'rel') state.sort = 'deadline';
  document.getElementById('sortSel').value = state.sort;

  const box = document.createElement('div');
  box.className = 'bf';
  box.hidden = true;
  box.setAttribute('aria-live', 'polite');
  document.querySelector('#results > section').prepend(box);

  // What's selected on the page goes with the question
  function filterText(){
    const parts = [];
    GROUPS.forEach(g => {
      if (!state[g.key].size) return;
      const labels = g.opts.filter(([v]) => state[g.key].has(v)).map(([, l]) => l);
      parts.push(`${g.title}: ${labels.join(', ')}`);
    });
    if (state.verified) parts.push('verified listings only');
    return parts.length ? `\n\n(Filters selected on the page: ${parts.join('; ')}.)` : '';
  }

  function paint(){
    if (!busy && !picks){ box.hidden = true; return; }
    box.hidden = false;
    const head = `<div class="bf-hd"><h2>Best fits</h2>
      <span class="asst-tag">AI assistant</span>
      <button type="button" class="linkbtn bf-reset">Start over</button></div>`;
    if (busy){
      box.innerHTML = head + '<p class="bf-wait">Reading through the GRAPES listings…</p>';
      return;
    }
    // Picks that the current filters rule out are left out here, as in the list
    const fit = picks.filter(m => { const r = DATA.find(x => x.id === m.id); return r && passes(r); });
    const hidden = picks.length - fit.length;
    box.innerHTML = head +
      (reply ? `<p class="bf-reply">${esc(reply)}</p>` : '') +
      fit.map(m => `<div class="asst-card">${m.why ? `<p class="asst-why">${esc(m.why)}</p>` : ''}${rowHTML(DATA.find(x => x.id === m.id))}</div>`).join('') +
      (hidden ? `<p class="bf-small">${hidden} more ${hidden === 1 ? 'pick is' : 'picks are'} hidden by your filters.</p>` : '') +
      '<p class="bf-small">Suggestions from an AI assistant: confirm eligibility on the sponsor’s page. Add details or ask a follow-up in the search box. Every listing is below.</p>';
  }

  async function ask(q){
    if (!q || busy) return;
    busy = true;
    history.push({role: 'user', text: q + filterText()});
    paint();
    box.scrollIntoView({behavior: 'smooth', block: 'start'});
    try {
      const res = await fetch('/api/ask', {method: 'POST', headers: apiHeaders(),
                                           body: JSON.stringify({messages: history})});
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Something went wrong.');
      reply = data.reply || '';
      picks = data.matches;
      history.push({role: 'assistant', text: reply, ids: picks.map(m => m.id)});
    } catch (err) {
      history.pop();
      reply = err.message || 'The assistant is unavailable right now.';
      picks = [];
    }
    busy = false;
    paint();
  }
  function startOver(){
    history.length = 0; picks = null; reply = '';
    input.value = '';
    document.getElementById('qclr').classList.remove('show');
    paint();
    input.focus();
  }

  window.runSearch = () => ask(input.value.trim());
  window.quick = s => { input.value = s; document.getElementById('qclr').classList.add('show'); ask(s); };
  window.clearQ = startOver;
  const pageRender = window.render;
  window.render = function(){ pageRender(); paint(); };

  box.addEventListener('click', e => {
    if (e.target.closest('.bf-reset')) return startOver();
    const sv = e.target.closest('[data-save]');
    if (sv){ e.stopPropagation(); toggleSave(+sv.dataset.save); return; }
    const row = e.target.closest('.row');
    if (row) openDetail(+row.dataset.id);
  });
  box.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.classList.contains('row')){
      e.preventDefault(); openDetail(+e.target.dataset.id);
    }
  });
  render();
}

// "Check the sponsor's page now": a button in each listing's details that runs
// the research agent on that listing and shows what the sponsor's page says today.
function startCheck(){
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
        const res = await fetch('/api/check', {method: 'POST', headers: apiHeaders(),
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
}


// ── Passcode for the online demo ──
let demoPasscode = '';
function apiHeaders(){
  const h = {'Content-Type': 'application/json'};
  if (demoPasscode) h['X-Demo-Passcode'] = demoPasscode;
  return h;
}
function remember(code){ try { sessionStorage.setItem('grapes-demo', code); } catch (e) {} }
function recalled(){ try { return sessionStorage.getItem('grapes-demo') || ''; } catch (e) { return ''; } }
async function tryUnlock(code){
  const res = await fetch('/api/unlock', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                          body: JSON.stringify({passcode: code})});
  return res.ok;
}
function start(check){
  startSearch();
  if (check) startCheck();
}
function askForPasscode(check){
  const box = document.createElement('form');
  box.className = 'asst-lock';
  box.innerHTML = `<label for="asstCode">Staff demo passcode</label>
    <input id="asstCode" type="password" autocomplete="off"/>
    <button type="submit">Unlock</button><p class="asst-lock-err" hidden>That passcode didn’t work.</p>`;
  document.body.append(box);
  box.querySelector('input').focus();
  box.addEventListener('submit', async e => {
    e.preventDefault();
    const code = box.querySelector('input').value.trim();
    if (code && await tryUnlock(code)){
      demoPasscode = code; remember(code); box.remove(); start(check);
    } else {
      box.querySelector('.asst-lock-err').hidden = false;
    }
  });
}
(async function boot(){
  let status = {locked: false, check: true};
  try { status = await (await fetch('/api/status')).json(); } catch (e) {}
  if (!status.locked) return start(status.check);
  const saved = recalled();
  if (saved && await tryUnlock(saved)){ demoPasscode = saved; return start(status.check); }
  if (new URLSearchParams(location.search).has('demo')) askForPasscode(status.check);
})();
