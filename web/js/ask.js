// The "Ask Atlas" drawer: sends the conversation to the agent and plays back its text, steps and actions.
import { fetchStatus } from './api.js';
import { escapeHtml } from './format.js';

const drawer = document.getElementById('ask');
const toggle = document.getElementById('ask-toggle');
const log = document.getElementById('ask-log');
const form = document.getElementById('ask-form');
const input = document.getElementById('ask-input');

const STARTERS = [
  'Find office towers over 40 stories with a full floor available',
  'Which floors here are empty, and what would the largest one cost per year?',
  'Compare the scanned suites in this building by rent and size',
];

const history = []; // [{ role, content }] plain-text turns
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
    ? `Ask about either city or the building on screen. Atlas can search CoStar records, measure from aerial imagery, read interior scans, and move the model for you.${STARTERS.map((s) => `<button type="button">${escapeHtml(s)}</button>`).join('')}`
    : 'Ask Atlas is switched off. Add ANTHROPIC_API_KEY to the .env file in the project folder and restart the server.';
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
  history.push({ role: 'user', content: question });

  let answer = null;
  let answerText = '';
  try {
    const response = await fetch('/api/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: history, context: handlers.context() }),
    });
    for await (const event of readEvents(response)) {
      if (event.type === 'text') {
        answer ||= add('a');
        answerText += event.text;
        answer.textContent = answerText;
        log.scrollTop = log.scrollHeight;
      } else if (event.type === 'step') {
        add('step', event.text);
        answer = null; // text after a step starts a new paragraph block
      } else if (event.type === 'action') {
        handlers.actions[event.name]?.(event.input);
      } else if (event.type === 'error') {
        add('step', event.message);
      }
    }
  } catch (error) {
    add('step', `The request failed: ${error.message}`);
  }
  if (answerText) history.push({ role: 'assistant', content: answerText });
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
