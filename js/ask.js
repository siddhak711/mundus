// The "Ask Atlas" drawer: sends each question to the Mundus deep agent and plays back its steps, actions and cited answer.
// Layout requests for a scanned space go to the apartment (conversion) agent instead; its layout comes back as a card.
import { api, fetchStatus } from './api.js';
import { escapeHtml, number } from './format.js';

const drawer = document.getElementById('ask');
const toggle = document.getElementById('ask-toggle');
const log = document.getElementById('ask-log');
const form = document.getElementById('ask-form');
const input = document.getElementById('ask-input');

const STARTERS = [
  'How many tenancies are recorded at Westside Towers East, 11835 Olympic Blvd?',
  'Which of Josephine DTLA, Grether & Grether Lofts, Royal Viking Motel and The Preserve have a pool or spa among their scans?',
  "Could the main room of The Preserve's Lobby/cafe space hold a 40-person standing reception?",
];

const threads = {}; // the agent server keeps each conversation; keys are 'mundus' and 'conversion:<scan id>'
const offered = new Set(); // scans already offered to the apartment agent
let busy = false;

function add(className, text = '') {
  const node = document.createElement('div');
  node.className = className;
  node.textContent = text;
  log.append(node);
  log.scrollTop = log.scrollHeight;
  return node;
}

function showStarters(agentReady) {
  const hint = document.createElement('div');
  hint.className = 'hint';
  hint.innerHTML = agentReady
    ? `Ask about the Los Angeles places in world memory. A deep agent sends market, interior and aerial specialists, saves what they find, and cites every fact. Open a scanned space and ask to lay out apartments on it, and an apartment agent drafts, checks and prices a layout.${STARTERS.map((s) => `<button type="button">${escapeHtml(s)}</button>`).join('')}`
    : 'Ask Atlas is switched off: the agent server is not running. Start the World API and the harness (see README), then reload.';
  hint.addEventListener('click', (event) => {
    if (event.target.tagName === 'BUTTON') send(event.target.textContent);
  });
  log.append(hint);
}

async function* readEvents(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let end;
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const line = buffer.slice(0, end).replace(/^data: /, '');
      buffer = buffer.slice(end + 2);
      if (line) yield JSON.parse(line);
    }
  }
}

let handlers;

function layoutCard(event) {
  const s = event.summary || {};
  const mix = Object.entries(s.unit_mix || {}).map(([type, n]) => `${n} ${type}`).join(', ');
  const checks = s.check_counts ? `${s.check_counts.pass || 0} pass, ${s.check_counts.fail || 0} fail, ${s.check_counts.unknown || 0} unknown` : '';
  const rows = [
    ['Units', `${s.units ?? '?'}${mix ? ` (${mix})` : ''}`],
    ['Rentable', s.rentable_sf ? `${number(s.rentable_sf)} sq ft` : ''],
    ['Rent', s.monthly_rent_usd ? `$${number(s.monthly_rent_usd)} a month` : 'unknown'],
    ['Conversion cost', s.conversion_cost_usd ? `$${number(s.conversion_cost_usd)}` : ''],
    ['Simple yield', s.simple_yield != null ? `${(s.simple_yield * 100).toFixed(1)}%` : ''],
    ['Rule checks', checks],
  ].filter(([, v]) => v);
  const walk = handlers.walkthrough?.(event.floor);
  const node = add('layout');
  node.innerHTML = `<strong>Apartment layout${event.floor ? `, floor ${event.floor}` : ''}${event.name ? `: ${escapeHtml(event.name)}` : ''}</strong>
    ${event.image ? `<div class="photo-grid"><img src="${escapeHtml(event.image)}" alt="Apartment layout drawn over the floor plan"></div>` : ''}
    <table>${rows.map(([k, v]) => `<tr><th>${k}</th><td>${escapeHtml(v)}</td></tr>`).join('')}</table>
    ${(s.issues || []).length ? `<p class="sub">Open issues: ${escapeHtml(s.issues.slice(0, 4).join('; '))}</p>` : ''}
    ${walk ? `<a href="${escapeHtml(walk)}">Walk the floor with the apartments drawn in</a>` : ''}
    <p class="sub">A rough draft: columns are guesses and exits are assumed.</p>`;
  log.scrollTop = log.scrollHeight;
}

async function send(question, { agent = null, scan = null } = {}) {
  if (busy || !question.trim()) return;
  busy = true;
  form.querySelector('button').disabled = true;
  input.value = '';
  add('q', question);

  try {
    const response = await fetch(api('/api/agent'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, threads, agent, context: { ...handlers.context(), ...(scan ? { scan } : {}) } }),
    });
    for await (const event of readEvents(response)) {
      if (event.type === 'thread') {
        threads[event.key || 'mundus'] = event.id;
      } else if (event.type === 'layout') {
        layoutCard(event);
      } else if (event.type === 'text') {
        add('a', event.text);
      } else if (event.type === 'sources') {
        const list = add('sources');
        for (const item of event.items) {
          const row = document.createElement('div');
          row.textContent = `[${item.n}] ${item.statement || item.claim_id}`;
          row.title = item.claim_id;
          list.append(row);
        }
      } else if (event.type === 'step') {
        add('step', event.text);
      } else if (event.type === 'action') {
        handlers.actions[event.name]?.(event.input);
      } else if (event.type === 'error') {
        add('step', event.message);
      }
    }
  } catch (error) {
    add('step', `The request failed: ${error.message}`);
  }
  busy = false;
  form.querySelector('button').disabled = false;
}

function openDrawer() {
  drawer.hidden = false;
  toggle.setAttribute('aria-expanded', 'true');
}

// "Design apartments" on a scanned space: opens the drawer and asks the apartment agent to lay out that space.
export function designSpace(scan) {
  if (!scan) return;
  openDrawer();
  send(`Lay out apartments on ${scan.name || 'this space'}${scan.floor ? ` (floor ${scan.floor})` : ''}.`,
    { agent: 'conversion', scan: { id: scan.id, name: scan.name, floor: scan.floor } });
}

// When a space is opened, the drawer offers the apartment agent for it once.
export function offerSpace(scan) {
  if (!scan || offered.has(scan.id)) return;
  offered.add(scan.id);
  const hint = document.createElement('div');
  hint.className = 'hint';
  hint.innerHTML = `Open space: ${escapeHtml(scan.name || scan.id)}. The apartment agent can lay out units on it, check them against Los Angeles rules and price them.
    <button type="button">Design apartments for this space</button>`;
  hint.querySelector('button').addEventListener('click', () => designSpace(scan));
  log.append(hint);
  log.scrollTop = log.scrollHeight;
}

export function setUpAsk(options) {
  handlers = options;
  toggle.addEventListener('click', () => {
    const open = drawer.hidden;
    drawer.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    if (open) input.focus();
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    send(input.value);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      send(input.value);
    }
  });
  fetchStatus().then(({ agent }) => showStarters(agent)).catch(() => showStarters(false));
}
