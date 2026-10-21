// The assistant for GRAPES Search+ (assistant/server.py).
// When the server is online with a passcode, nothing changes until a staff
// member opens the page with ?demo and enters it (kept for the browser tab).
// Loaded after the page's own script, so it uses the page's DATA, rowHTML,
// openDetail and toggleSave to show recommendations as ordinary result cards.

// Two tabs under the header: a full-page chat with the assistant, and the
// page as it was ("All opportunities", with its keyword search and filters).
function startChat(){
  const history = [];
  let busy = false;

  const tabs = document.createElement('nav');
  tabs.className = 'tabs';
  tabs.setAttribute('aria-label', 'Views');
  tabs.innerHTML = `<div class="wrap">
      <button type="button" data-tab="chat">Ask the assistant</button>
      <button type="button" data-tab="all">All opportunities <span class="ct">${DATA.length}</span></button>
    </div>`;
  document.querySelector('header.mast').after(tabs);

  const page = document.createElement('main');
  page.className = 'chatpage wrap';
  page.innerHTML = `
    <div class="chat-intro">
      <h1>Find funding that fits you.</h1>
      <p>Tell the assistant your degree and year, your field, your citizenship, and what the funding is for.
        It suggests awards from GRAPES and says why each one fits. Don't include your name or student ID.</p>
      <div class="chat-try"><span>Try:</span>
        <button type="button">3rd-year sociology PhD, international student, need summer research funding</button>
        <button type="button">Master's student in public health looking for conference travel grants</button>
        <button type="button">Dissertation-year fellowships in the humanities, U.S. citizen</button>
      </div>
    </div>
    <div class="chat-log" aria-live="polite"></div>
    <form class="chat-form">
      <label for="chatQ" class="chat-sr">Your question</label>
      <textarea id="chatQ" rows="2" maxlength="1500" placeholder="Describe what you're looking for…"></textarea>
      <div class="chat-acts">
        <button type="button" class="linkbtn chat-reset" hidden>Start over</button>
        <button type="submit" class="btn solid">Ask</button>
      </div>
    </form>
    <p class="chat-note">Suggestions from an AI assistant. Always confirm deadlines and eligibility on the sponsor's page.</p>`;
  tabs.after(page);

  const views = {all: [document.querySelector('.hero'), document.querySelector('.browse'), document.getElementById('results')],
                 chat: [page]};
  function show(tab){
    for (const [k, els] of Object.entries(views)) els.forEach(el => { el.hidden = k !== tab; });
    tabs.querySelectorAll('button').forEach(b => b.setAttribute('aria-current', b.dataset.tab === tab ? 'page' : 'false'));
    try { sessionStorage.setItem('grapes-tab', tab); } catch (e) {}
  }
  tabs.addEventListener('click', e => { const b = e.target.closest('[data-tab]'); if (b){ show(b.dataset.tab); window.scrollTo(0, 0); } });
  // The header's Saved and logo buttons belong to the full list
  const pageToggleSaved = window.toggleSaved, pageResetAll = window.resetAll;
  window.toggleSaved = () => { show('all'); pageToggleSaved(); };
  window.resetAll = () => { show('all'); pageResetAll(); };
  let first = 'chat';
  try { first = sessionStorage.getItem('grapes-tab') || (location.hash.length > 1 ? 'all' : 'chat'); } catch (e) {}
  show(first);

  const log = page.querySelector('.chat-log');
  const form = page.querySelector('form');
  const input = page.querySelector('textarea');
  const reset = page.querySelector('.chat-reset');
  const intro = page.querySelector('.chat-intro');

  function bubble(cls, text){
    const p = document.createElement('div');
    p.className = 'chat-msg ' + cls;
    p.textContent = text;
    log.append(p);
    return p;
  }
  function cards(matches){
    const wrap = document.createElement('div');
    wrap.className = 'chat-cards';
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
  page.querySelectorAll('.chat-try button').forEach(b => b.addEventListener('click', () => {
    input.value = b.textContent; form.requestSubmit();
  }));
  reset.addEventListener('click', () => {
    history.length = 0; log.innerHTML = '';
    intro.hidden = false; reset.hidden = true;
    input.focus();
  });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q || busy) return;
    busy = true;
    input.value = '';
    intro.hidden = true; reset.hidden = false;
    bubble('me', q);
    history.push({role: 'user', text: q});
    const wait = bubble('bot wait', 'Looking through GRAPES…');
    wait.scrollIntoView({behavior: 'smooth', block: 'end'});
    try {
      const res = await fetch('/api/ask', {method: 'POST', headers: apiHeaders(),
                                           body: JSON.stringify({messages: history})});
      const data = await res.json();
      wait.remove();
      if (!res.ok) throw new Error(data.error || 'Something went wrong.');
      const reply = bubble('bot', data.reply || 'Here is what I found.');
      if (data.matches.length) cards(data.matches);
      history.push({role: 'assistant', text: data.reply, ids: data.matches.map(m => m.id)});
      reply.scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (err) {
      wait.remove();
      bubble('bot err', err.message || 'The assistant is unavailable right now.');
      history.pop();
    }
    busy = false;
    input.focus({preventScroll: true});
  });
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
  startChat();
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
