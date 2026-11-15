import { API_BASE } from '../../js/config.js';

const API = API_BASE.replace(/\/$/, '');
// The walkthrough sidebar: the four agents (layout, compliance, structure, cost-benefit) working through the floor, the
// files they produce, Submit for review, and the chat at the bottom.
//
// The agent cards replay the saved study (layouts/<scan>.json) step by step, so the demo never waits on a model. The chat is
// live: commands run on the page, and questions go to the Mundus agent through Atlas's server (POST /api/agent) when it is
// running, or are answered from the same saved study when it is not.
const $ = (id) => document.getElementById(id);
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const n0 = (v) => Math.round(v).toLocaleString('en-US');
const usd = (v) => `$${n0(v)}`;
const usdM = (v) => `${v < 0 ? '−' : ''}$${(Math.abs(v) / 1e6).toFixed(2)}M`;
const pct = (v, d = 1) => `${(v * 100).toFixed(d)}%`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

function item(L, name) { return (L.self_score?.items || {})[name]; }
const scoreLine = (L, name) => { const it = item(L, name); return it ? { text: `${name}: ${it.measured}`, ok: it.points >= it.max - 1e-6 } : null; };

// what each agent says, built from the saved study
function scripts(L, S, SH) {
  const units = L.units, n = units.length, rooms = units.flatMap((u) => u.rooms);
  const count = (t) => rooms.filter((r) => r.type === t).length;
  const mix = Object.entries(L.summary.unit_mix || {}).map(([k, v]) => `${v} × ${k}`).join(', ');
  const A = L.areas || {}, M = L.money || {}, E = L.egress || {};
  const [x0, x1, y0, y1] = SH.rect;
  const checks = units.flatMap((u) => Object.values(u.checks || {})), pass = checks.filter((c) => c.ok).length;
  const pts = (names) => names.reduce((a, k) => a + (item(L, k)?.points || 0), 0), max = (names) => names.reduce((a, k) => a + (item(L, k)?.max || 0), 0);
  const COMPLY = ['LA zoning', 'Room size, daylight, escape', 'Exits and stairs', 'Accessibility', 'Fire, sound, ventilation', 'No hard failures'];
  const STRUCT = ['Detected columns', 'Hidden columns', 'Drains to the core', 'Loads and earthquake'];
  const MONEY = ['Buyer yield', 'Owner view vs office', 'Share of floor rented', 'Unit size vs market'];
  const cols = L.columns || [], hard = cols.filter((c) => c.hard).length, inRooms = cols.filter((c) => (c.overlaps || []).length).length;
  return [
    {
      id: 'layout', name: 'Layout agent', av: 'L', file: 'layout.json', anchor: 'summary',
      steps: [
        { text: `Reading the scan: ${n0(S.stats.areaSf)} sq ft scanned, ${S.panos.length} capture points` },
        { text: `Outer wall ${(x1 - x0).toFixed(1)} × ${(y1 - y0).toFixed(1)} m, ${SH.core.length} core blocks, ${SH.columns.length} probable columns` },
        { text: `Daylight band: ${Math.round(S.share * 100)}% of the floor is within 30 ft of the glass` },
        { text: `Placing ${n} homes along the glass, kitchens and baths toward the core`, rise: true },
        { text: `${count('bed')} bedrooms, ${count('bath')} baths, ${count('kitchen')} kitchens, every bedroom on a window`, ok: true },
        { text: `Corridor loop around the core: ${E.corridor_loop ? 'yes' : 'no'}; worst walk to a stair ${E.worst_travel_to_stair_m} m`, ok: !!E.corridor_loop },
        { text: `Homes take ${n0(A.units_sf)} of ${n0(A.gross_sf)} sq ft (${pct(A.efficiency, 0)} efficient)` },
      ],
      head: `${n} homes`,
      rows: [['Homes', n], ['Mix', mix], ['Rentable', `${n0(L.summary.rentable_sf)} sq ft`], ['Average home', `${n0(L.summary.rentable_sf / n)} sq ft`], ['Efficiency', pct(A.efficiency, 0)], ['Layout score', `${L.self_score?.total ?? '–'} / 100`]],
    },
    {
      id: 'compliance', name: 'Compliance agent', av: 'C', file: 'compliance.md', anchor: 'compliance',
      steps: [
        { text: 'LA Adaptive Reuse Ordinance 188,793: built 1969, by-right conversion (15+ years old)', ok: true },
        ...COMPLY.map((k) => scoreLine(L, k)).filter(Boolean),
        { text: `${pass} of ${checks.length} unit checks pass (room sizes, doors, turning circles, drain runs)`, ok: pass === checks.length },
      ],
      head: `${(+pts(COMPLY).toFixed(1))}/${max(COMPLY)} pts`,
      rows: [['Code points', `${(+pts(COMPLY).toFixed(1))} of ${max(COMPLY)}`], ['Unit checks', `${pass} / ${checks.length} pass`], ['Hard failures', String(L.self_score?.hard_breaks?.length ?? 0)], ['Stairs apart', `${E.stair_separation_m} m`], ['Accessible homes', String(units.filter((u) => u.access && u.access !== 'standard').length)]],
    },
    {
      id: 'structure', name: 'Structure agent', av: 'S', file: 'structure.md', anchor: 'structure',
      steps: [
        { text: `${cols.length} columns checked against every wall, bath and hall (${['probable', 'possible', 'hidden'].map((k) => `${cols.filter((c) => c.kind === k).length} ${k}`).join(', ')})` },
        ...STRUCT.map((k) => scoreLine(L, k)).filter(Boolean),
        { text: 'Beams and slab depth are not in the scan: confirm against the structural drawings before design', flag: true },
      ],
      head: hard ? `${hard} conflicts` : 'No conflicts',
      rows: [['Columns checked', String(cols.length)], ['Inside a room', String(inRooms)], ['Hard conflicts', String(hard)], ['Structure points', `${(+pts(STRUCT).toFixed(1))} of ${max(STRUCT)}`], ['Beams', 'not scanned']],
    },
    {
      id: 'cost', name: 'Cost-benefit agent', av: '$', file: 'cost-benefit.md', anchor: 'cost',
      steps: [
        { text: `Rents from nearby CoStar comps: ${usd(M.avg_rent)} a month on average across ${M.n} homes` },
        { text: `Gross rent ${usdM(M.gpr)} a year → net operating income ${usdM(M.noi)}` },
        { text: `Build ${usdM(M.build)} + linkage fee ${usdM(M.linkage)} = ${usdM(M.owner_cost)} for the owner` },
        { text: `Yield on cost: ${pct(M.yoc_owner, 2)} for the owner, ${pct(M.yoc_buyer, 2)} for a buyer paying ${usdM(M.acq)}`, ok: M.yoc_owner >= 0.055, flag: M.yoc_owner < 0.055 },
        { text: `Against staying office: NOI ${M.vs_office >= 0 ? '+' : ''}${usdM(M.vs_office)} a year`, ok: M.vs_office >= 0, flag: M.vs_office < 0 },
        { text: `Break-even build cost: ${usd(M.breakeven_cost_per_rentable_sf)} per rentable sq ft` },
        ...MONEY.map((k) => scoreLine(L, k)).filter(Boolean).map((l) => (l.ok ? l : { text: l.text, flag: true })),
      ],
      head: `${pct(M.yoc_owner, 1)} yield`,
      rows: [['Rent roll', `${usdM(M.gpr)} / yr`], ['NOI', `${usdM(M.noi)} / yr`], ['Owner cost', usdM(M.owner_cost)], ['Owner yield', pct(M.yoc_owner, 2)], ['Buyer yield', pct(M.yoc_buyer, 2)], ['vs office', `${usdM(M.vs_office)} / yr`]],
    },
  ];
}

export function setUpSidebar({ LAY, S, SH, SCAN, FLOOR, building, setApts, runCommand }) {
  const list = $('agents'), submit = $('submit'), runBtn = $('run-agents');
  const reviewUrl = () => `review.html?scan=${encodeURIComponent(SCAN)}${building ? `&building=${encodeURIComponent(building)}` : ''}`;
  let ran = false, running = null;
  const AG = LAY ? scripts(LAY, S, SH) : [];

  if (!LAY) {
    list.innerHTML = '<li class="muted" style="font-size:13px">No saved study for this floor yet, so the agents have nothing to replay. Apartments shows the conversion agent\'s draft if there is one.</li>';
    submit.hidden = true;
  }
  const cards = AG.map((a) => {
    const li = document.createElement('li'); li.className = 'agent'; li.dataset.state = 'idle';
    li.innerHTML = `<button type="button" aria-expanded="false"><span class="av">${esc(a.av)}</span><span><span class="nm">${esc(a.name)}</span><br><span class="st">Waiting</span></span><span class="head-num"></span></button><div class="log"></div>`;
    li.querySelector('button').addEventListener('click', () => { if (li.dataset.state === 'idle') return; const o = !li.classList.contains('open'); li.classList.toggle('open', o); li.querySelector('button').setAttribute('aria-expanded', String(o)); });
    list.append(li); return li;
  });

  const open = (li, o) => { li.classList.toggle('open', o); li.querySelector('button').setAttribute('aria-expanded', String(o)); };
  async function play(a, li) {
    li.dataset.state = 'working'; li.querySelector('.st').textContent = 'Working…'; open(li, true);
    const log = li.querySelector('.log');
    for (const s of a.steps) {
      await sleep(REDUCED ? 60 : 520 + Math.random() * 380);
      const d = document.createElement('div'); d.className = s.flag ? 'flag' : s.ok ? 'ok' : ''; d.textContent = s.text; log.append(d);
      if (s.rise) setApts(true);
    }
    await sleep(REDUCED ? 60 : 400);
    li.dataset.state = 'done'; li.querySelector('.st').textContent = `Done · wrote ${a.file}`; li.querySelector('.head-num').textContent = a.head;
    const f = document.createElement('div'); f.className = 'file';
    f.innerHTML = `<div class="fn"><span>${esc(a.file)}</span><a href="${reviewUrl()}#${a.anchor}">Open in review</a></div>` + a.rows.map(([k, v]) => `<div class="row"><span class="muted">${esc(k)}</span><span>${esc(v)}</span></div>`).join('');
    li.append(f); open(li, false);
  }
  async function runAgents() {
    if (!LAY) return setApts(true);
    if (ran) return setApts(true);
    if (running) return running;
    runBtn.disabled = true; runBtn.textContent = 'Agents working…';
    chatLine('step', 'Layout agent started. Compliance, structure and cost-benefit agents will follow its draft.');
    running = (async () => {
      await play(AG[0], cards[0]);
      await Promise.all(AG.slice(1).map((a, i) => sleep(i * 260).then(() => play(a, cards[i + 1]))));
      ran = true; runBtn.textContent = 'Done'; submit.disabled = false;
      chatLine('a', `The agents are done: ${LAY.units.length} homes, ${AG[1].head} on code, ${AG[2].head.toLowerCase()} on structure, ${AG[3].head}. Click any agent to read its file, or Submit for review.`);
    })();
    return running;
  }
  runBtn.addEventListener('click', runAgents);
  submit.addEventListener('click', () => { location.href = reviewUrl(); });

  // ---------- chat ----------
  const chatLog = $('chat-log'), form = $('cmd'), input = $('cmd-in');
  function chatLine(cls, text) { const d = document.createElement('div'); d.className = cls; d.textContent = text; chatLog.append(d); chatLog.scrollTop = chatLog.scrollHeight; return d; }
  chatLine('a', 'Ask me about this floor, or tell me what to do: “remove the walls”, “design apartments”, “floor plan”, “walk inside”.');
  let threadId = null, busy = false;
  // Asked before every question, not once at page load: one slow or failed check must not turn the chat off for the visit.
  const agentUp = () => fetch(`${API}/api/status`).then((r) => (r.ok ? r.json() : { agent: false })).then((j) => !!j.agent).catch(() => false);

  // without the live agent, answer from the saved study, and say so
  function offline(q, why = 'The live agent is not reachable right now.') {
    const t = q.toLowerCase(); if (!LAY) return `${why} This floor has no saved study to answer from.`;
    const pick = /cost|yield|rent|noi|money|price|budget|profit|worth|return|benefit|fee/.test(t) ? 3 : /code|complian|egress|exit|stair|fire|access|ada|zoning|legal|permit|ordinance/.test(t) ? 1
      : /column|beam|struct|load|earthquake|seismic|slab|drain|plumb|riser/.test(t) ? 2 : 0;
    const a = AG[pick];
    return `${why} From the saved study, the ${a.name.toLowerCase()} says:\n`
      + a.rows.map(([k, v]) => `• ${k}: ${v}`).join('\n');
  }
  // The agent on the server knows places, not this page. The first question of a conversation carries the saved study
  // (what each of the four agents did and found), so it can answer about the floor and the agents themselves.
  function withStudy(q) {
    if (!LAY || threadId) return q;
    const where = FLOOR ? `floor ${FLOOR.floor} of ${FLOOR.building}, ${FLOOR.address}` : `floor scan ${SCAN}`;
    const study = AG.map((a) => `${a.name} (wrote ${a.file})\nWhat it did:\n${a.steps.map((x) => `- ${x.text}`).join('\n')}\nResult:\n${a.rows.map(([k, v]) => `- ${k}: ${v}`).join('\n')}`).join('\n\n');
    return `I am on the walkthrough page of an office-to-apartment conversion study for ${where}. Four agents (layout, compliance, structure, cost-benefit) produced the saved study below. Answer from it where it applies, and say so when it does not cover the question.\n\n${study}\n\nQuestion: ${q}`;
  }
  async function* events(response) {
    const reader = response.body.getReader(), dec = new TextDecoder(); let buf = '';
    for (;;) { const { value, done } = await reader.read(); if (done) return; buf += dec.decode(value, { stream: true }); let e;
      while ((e = buf.indexOf('\n\n')) >= 0) { const line = buf.slice(0, e).replace(/^data: /, ''); buf = buf.slice(e + 2); if (line) yield JSON.parse(line); } }
  }
  async function ask(q) {
    if (!(await agentUp())) { chatLine('a', offline(q)); return; }
    const context = { page: 'walkthrough', scan: SCAN, building: building || FLOOR?.propertyId, floor: FLOOR?.floor, address: FLOOR?.address,
      layout: LAY ? { ...LAY.summary, money: LAY.money, score: LAY.self_score?.total } : null };
    try {
      const res = await fetch(`${API}/api/agent`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: withStudy(q), thread_id: threadId, context }) });
      if (!res.ok) throw new Error(`the server answered ${res.status}`);
      let answered = false;
      for await (const ev of events(res)) {
        if (ev.type === 'thread') threadId = ev.id;
        else if (ev.type === 'step') chatLine('step', ev.text);
        else if (ev.type === 'text') { chatLine('a', ev.text); answered = true; }
        else if (ev.type === 'error') chatLine('step', ev.message);
      }
      if (!answered) chatLine('a', offline(q, 'The agent did not return an answer.'));
    } catch (err) { chatLine('step', `The agent could not be reached (${err.message}).`); chatLine('a', offline(q)); }
  }
  async function send() {
    const q = input.value.trim(); if (!q || busy) return;
    input.value = ''; input.style.height = ''; chatLine('q', q);
    const done = runCommand(q);
    if (done) { chatLine('a', done); return; }
    busy = true; form.querySelector('button').disabled = true;
    try { await ask(q); } finally { busy = false; form.querySelector('button').disabled = false; }
  }
  form.addEventListener('submit', (e) => { e.preventDefault(); send(); });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
  input.addEventListener('input', () => { input.style.height = ''; input.style.height = `${Math.min(input.scrollHeight, 120)}px`; });

  return { runAgents, done: () => ran };
}
