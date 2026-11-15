// Start loading a property's 3-D model before it is opened: on hover, focus, or a search narrowed to it.
//
// Opening a building needs its CoStar record, its site model (built by the server from Vexcel the first time, then
// cached on disk), the height model and aerial photo the site model points at, and its conversion screen. Fetching
// them early makes the server build and cache the model, and puts the files in the browser cache (server.py sends
// /data/ and /cache/ with max-age), so the click only has to draw.

const started = new Set();
const queue = [];
let active = 0;
const MAX_PARALLEL = 2;   // a model build makes several Vexcel calls: do not start a dozen while the pointer sweeps

const low = { priority: 'low' };
const quietly = (url) => fetch(url, low).then((r) => (r.ok ? r : null)).catch(() => null);

async function warm(kind, id) {
  await Promise.all([
    quietly(`/data/${kind === 'home' ? 'home' : 'property'}/${id}.json`),
    kind === 'commercial' ? quietly(`/data/conversion/property/${id}.json`) : null,
    quietly(`/api/twin?kind=${kind}&id=${id}`).then(async (r) => {
      const twin = r && (await r.json().catch(() => null));
      if (twin?.heights) await Promise.all([quietly(twin.heights), quietly(twin.ortho)]);
    }),
  ]);
}

function pump() {
  while (active < MAX_PARALLEL && queue.length) {
    const [kind, id] = queue.shift();
    active += 1;
    warm(kind, id).finally(() => { active -= 1; pump(); });
  }
}

/** Queue a property for prefetching. Repeat calls for the same property do nothing. */
export function prefetchProperty(kind, id) {
  const key = `${kind}:${id}`;
  if (started.has(key)) return;
  started.add(key);
  queue.unshift([kind, id]);        // the newest intent first: that is where the pointer is now
  if (queue.length > 6) queue.length = 6;
  pump();
}

/** Hover intent: prefetch only when the pointer rests on an item for a moment, not while it sweeps past. */
export function onHoverIntent(element, selector, getTarget, delay = 120) {
  let timer = 0;
  element.addEventListener('pointerover', (event) => {
    const item = event.target.closest(selector);
    clearTimeout(timer);
    if (item) timer = setTimeout(() => { const t = getTarget(item); if (t) prefetchProperty(...t); }, delay);
  });
  element.addEventListener('pointerout', () => clearTimeout(timer));
  element.addEventListener('focusin', (event) => {
    const item = event.target.closest(selector);
    const t = item && getTarget(item);
    if (t) prefetchProperty(...t);
  });
}
