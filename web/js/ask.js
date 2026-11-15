// The "Ask Atlas" drawer: sends each question to the Mundus deep agent and plays back its steps, actions and cited answer.
import { fetchStatus } from './api.js';
import { escapeHtml } from './format.js';

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

let threadId = null; // the agent server keeps the conversation; this names it
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
    ? `Ask about the Los Angeles places in world memory. A deep agent sends market, interior and aerial specialists, saves what they find, and cites every fact.${STARTERS.map((s) => `<button type="button">${escapeHtml(s)}</button>`).join('')}`
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

async function send(question) {
  if (busy || !question.trim()) return;
  busy = true;
  form.querySelector('button').disabled = true;
  input.value = '';
  add('q', question);

  try {
    const response = await fetch('/api/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, thread_id: threadId, context: handlers.context() }),
    });
    for await (const event of readEvents(response)) {
      if (event.type === 'thread') {
        threadId = event.id;
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
