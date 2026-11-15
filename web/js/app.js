// Routing and the glue between the record panel, the 3-D viewer and the ask drawer.
//   #/houston                      city list and map
//   #/houston/commercial/233899    one property
//   #/los-angeles/office-to-housing   the office-to-housing map (web/city/city.js)
import { fetchConversion, fetchDetail, fetchScan, fetchTwin } from './api.js';
import { showCity, showOnly } from './browse.js';
import { createFloorModel, CURRENT_YEAR } from './floors.js';
import { escapeHtml, number, rate, CITY_NAMES } from './format.js';
import { renderRecord } from './record.js';
import { setUpAsk } from './ask.js';
import { Viewer } from './twin/viewer.js';
import { handoff } from './handoff.js';
import { showConversionMap } from '/city/city.js';

const DEFAULT_CITY = 'houston';
const el = (id) => document.getElementById(id);
const browseView = el('browse');
const twinView = el('twin');
const cityView = el('city');
const status = el('stage-status');
const controls = el('stage-controls');
const tip = el('floor-tip');

let current = null; // everything belonging to the open property

// ---- property view ------------------------------------------------------------
function closeProperty() {
  if (!current) return;
  current.viewer.dispose();
  clearInterval(current.playTimer);
  current = null;
}

function freshCanvas() {
  // A new canvas per property drops the old WebGL context and its listeners in one go.
  const old = el('canvas');
  const canvas = old.cloneNode();
  old.replaceWith(canvas);
  return canvas;
}

function showStatus(title, body = '') {
  status.hidden = !title;
  status.innerHTML = title ? `<strong>${escapeHtml(title)}</strong>${escapeHtml(body)}` : '';
}

function repaint() {
  const { viewer, floors, year, marked, hovered } = current;
  viewer.paint((floor) => {
    const info = floors.at(floor, year);
    return {
      leasedShare: info.leasedShare,
      available: info.available.length > 0,
      emphasised: floor === hovered || marked.has(floor),
      walk: Boolean(info.walkthrough),
    };
  });
}

function showFloorTip(floor, event) {
  if (!floor || !event) { tip.hidden = true; return; }
  const info = current.floors.at(floor, current.year);
  const lines = info.tenants.slice(0, 4).map((t) => `${escapeHtml(t.tenant)}, ${number(t.sf)} sq ft`);
  info.available.forEach((s) => lines.push(`Suite ${escapeHtml(s.suite || '')} available, ${number(s.sf)} sq ft at ${rate(s.rate)}`));
  if (info.scans.length) lines.push('Has an interior scan');
  if (info.walkthrough) lines.push('<b>Click to walk this floor</b>');
  tip.innerHTML = `<strong>Floor ${floor}</strong>${lines.length ? lines.join('<br>') : 'Nothing on record'}`;
  tip.hidden = false;
  tipStage = tip.parentElement.getBoundingClientRect();   // measured once per floor, not on every pointer move
  moveFloorTip(event);
}

// The tooltip follows the pointer without rebuilding its text or repainting the floors.
let tipStage = null;
function moveFloorTip(event) {
  if (tip.hidden || !event || !tipStage) return;
  tip.style.transform = `translate(${event.clientX - tipStage.left + 14}px, ${event.clientY - tipStage.top + 14}px)`;
}

function setYear(year) {
  current.year = year;
  el('timeline-year').value = year;
  const { tenants, leasedSf } = current.floors.summary(year);
  el('timeline-out').textContent = year;
  el('timeline-out').title = `${tenants} tenants, ${number(leasedSf)} sq ft on record`;
  repaint();
}

function togglePlay() {
  const button = el('timeline-play');
  if (current.playTimer) {
    clearInterval(current.playTimer);
    current.playTimer = null;
    button.textContent = 'Play';
    return;
  }
  let year = current.year >= CURRENT_YEAR ? current.floors.firstYear : current.year;
  button.textContent = 'Pause';
  current.playTimer = setInterval(() => {
    setYear(year);
    if (year++ >= CURRENT_YEAR) togglePlay();
  }, 300);
}

async function openScan(scan) {
  if (!current || !scan) return;
  const session = current;
  showStatus('Loading the interior scan', ' The first load downloads the mesh from Matterport.');
  try {
    const assets = await fetchScan(scan.id);
    if (current !== session) return;
    const cutRange = await session.viewer.showScan(assets, scan.floor);
    session.record.setOpenScan({ id: scan.id, cutRange, photos: assets.photos });
    showStatus('');
  } catch (error) {
    showStatus('The scan could not be loaded', ` ${error.message}`);
  }
}

function closeScan() {
  current.viewer.hideScan();
  current.record.setOpenScan(null);
  current.viewer.setView(current.viewer.view);
}

function setView(view) {
  if (!current) return;
  if (current.viewer.scan) { current.viewer.hideScan(); current.record.setOpenScan(null); }
  controls.querySelectorAll('[data-view]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.view === view)));
  current.viewer.setView(view);
}

// Into the floor walkthrough (web/walkthrough/), which links back to this property.
function openWalkthrough(floor) {
  const walk = current?.floors.walkthrough(floor);
  if (walk) location.href = walk.href;
}

function openTour(scan) {
  el('tour').querySelector('iframe').src = `${scan.tourUrl}&play=1&qs=1&brand=0`;
  el('tour').showModal();
}

// From the office-to-housing map, the map stays on screen while the 3-D view is built and drawn behind it, then the
// map zooms away and the model fades in: the page is never blank in between. Elsewhere the view simply replaces.
function revealOverMap() {
  return new Promise((done) => {
    requestAnimationFrame(() => requestAnimationFrame(() => {           // the model's first frames are on the canvas
      if (handoffZoom) { cityView.style.setProperty('--zoom-x', `${handoffZoom[0]}px`); cityView.style.setProperty('--zoom-y', `${handoffZoom[1]}px`); }
      current?.viewer.restartReveal();                                  // the opening fly-in starts as it comes into view
      cityView.classList.add('is-leaving');
      twinView.classList.add('is-in');
      setTimeout(() => {
        cityView.hidden = true;
        cityView.classList.remove('is-leaving');
        el('c-loading').hidden = true;
        twinView.classList.remove('is-entering', 'is-in');
        done();
      }, 640);
    }));
  });
}
let handoffZoom = null;

async function openProperty(city, kind, id) {
  closeProperty();
  const fromMap = handoff.from === 'map' && !cityView.hidden;
  handoffZoom = fromMap ? [handoff.zoomX, handoff.zoomY] : null;
  handoff.from = null;
  browseView.hidden = true;
  if (fromMap) twinView.classList.add('is-entering');
  else cityView.hidden = true;
  twinView.hidden = false;
  controls.hidden = true;
  tip.hidden = true;
  el('record').innerHTML = '';
  el('topbar-note').textContent = '';
  // Usually the model is already cached or prefetched and opens at once: only say it is loading if it takes a while,
  // so a quick open is not interrupted by a box that flashes up and away.
  const slowNotice = setTimeout(() => {
    if (current?.id !== id || current.ready) return;
    if (fromMap) el('c-loading').hidden = false;                      // the map is what is on screen
    else showStatus('Building the site model', ' Fetching the aerial photo, height model and scans. This takes a few seconds the first time.');
  }, 600);

  const viewer = new Viewer({
    canvas: freshCanvas(),
    labelLayer: el('stage-labels'),
    // called only when the floor under the pointer changes; onFloorMove handles the rest of the movement
    onFloorHover: (floor, event) => { if (current?.floors) { current.hovered = floor; repaint(); showFloorTip(floor, event); } },
    onFloorMove: moveFloorTip,
    onFloorClick: (floor) => {
      if (!current?.floors) return;
      const info = current.floors.at(floor, current.year);
      if (info.walkthrough) return openWalkthrough(floor);      // a scanned, baked floor: go straight inside
      current.record.focusFloor(info);
    },
  });
  const session = (current = { viewer, year: CURRENT_YEAR, marked: new Set(), hovered: 0, playTimer: null, kind, id, city });

  try {
    const [detail, twin, conversion] = await Promise.all([
      fetchDetail(kind, id), fetchTwin(kind, id), kind === 'commercial' ? fetchConversion(id) : null]);
    if (current !== session) return;
    session.detail = detail;
    session.twin = twin;
    session.floors = createFloorModel(detail, twin, conversion);
    session.record = renderRecord(el('record'), {
      detail, twin, floors: session.floors, city, conversion,
      handlers: {
        onOpenScan: openScan,
        onCloseScan: closeScan,
        onCut: (height) => viewer.setScanCut(height),
        onTour: openTour,
        onTenantHover: (floors) => { session.marked = new Set(floors); repaint(); },
        onFloorFocus: (floor) => { session.marked = new Set([floor]); repaint(); session.record.focusFloor(session.floors.at(floor)); },
      },
    });
    await viewer.load(twin);
    if (current !== session) return;

    const heightFt = Math.round(twin.building.top * 3.28084);
    viewer.setPins([
      { label: `${number(heightFt)} ft` },
      ...session.floors.walkthroughFloors.map((floor) => ({ floor, label: `Walk floor ${floor}`, walk: true, onClick: () => openWalkthrough(floor) })),
      // a walkthrough floor's scan is still in the Interiors tab; one pin per floor keeps them apart
      ...twin.scans.filter((s) => s.floor && !session.floors.walkthroughFloors.includes(s.floor))
        .map((s) => ({ floor: s.floor, label: `Scan, floor ${s.floor}`, onClick: () => openScan(s) })),
    ]);
    repaint();

    el('timeline').hidden = !session.floors.hasHistory;
    el('timeline-year').min = session.floors.firstYear;
    setYear(CURRENT_YEAR);
    el('layer-heights').checked = el('layer-footprints').checked = false;
    viewer.setVacancy(el('layer-vacancy').checked);
    setView('model');
    controls.hidden = false;
    clearTimeout(slowNotice);
    showStatus('');
    el('topbar-note').textContent = `${CITY_NAMES[city]}, ${detail.type}`;
    document.title = `${detail.name} | Atlas`;
    session.ready = true;
    if (fromMap) {
      const back = el('record').querySelector('.back');               // return to the map it was opened from
      if (back) { back.href = '#/los-angeles/office-to-housing'; back.textContent = 'Back to the office-to-housing map'; }
      await revealOverMap();
    }
  } catch (error) {
    clearTimeout(slowNotice);
    el('c-loading').hidden = true;
    if (fromMap) { cityView.hidden = true; twinView.classList.remove('is-entering', 'is-in'); }   // show the error
    if (current === session) showStatus('This property could not be loaded', ` ${error.message}`);
  }
}

// ---- routing ------------------------------------------------------------------
function route() {
  const [city = DEFAULT_CITY, kind, id] = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  const knownCity = CITY_NAMES[city] ? city : DEFAULT_CITY;
  document.querySelectorAll('.cities a').forEach((a) => {
    if (a.dataset.city === knownCity) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  if (kind === 'office-to-housing') {
    closeProperty();
    twinView.hidden = browseView.hidden = true;
    twinView.classList.remove('is-entering', 'is-in');
    cityView.hidden = false;
    el('topbar-note').textContent = '';
    document.title = 'LA office to housing | Atlas';
    return showConversionMap();
  }
  if (kind && id) return openProperty(knownCity, kind, id);

  closeProperty();
  twinView.hidden = true;
  cityView.hidden = true;
  browseView.hidden = false;
  el('topbar-note').textContent = '';
  document.title = `${CITY_NAMES[knownCity]} | Atlas`;
  showCity(knownCity);
}

// ---- wiring ------------------------------------------------------------------
controls.addEventListener('click', (event) => {
  const view = event.target.closest('[data-view]');
  if (view) setView(view.dataset.view);
});
el('layer-heights').addEventListener('change', (e) => current?.viewer.setLayer('heights', e.target.checked));
el('layer-vacancy').addEventListener('change', (e) => { current?.viewer.setVacancy(e.target.checked); if (current) repaint(); });
el('layer-footprints').addEventListener('change', (e) => current?.viewer.setLayer('footprints', e.target.checked));
el('timeline-year').addEventListener('input', (e) => setYear(Number(e.target.value)));
el('timeline-play').addEventListener('click', togglePlay);
el('tour-close').addEventListener('click', () => { el('tour').close(); el('tour').querySelector('iframe').src = 'about:blank'; });

document.addEventListener('click', (event) => {
  const image = event.target.closest('.photo-grid img');
  if (!image) return;
  const box = el('lightbox');
  box.querySelector('img').src = image.src;
  box.querySelector('p').textContent = image.alt;
  box.showModal();
});
el('lightbox').addEventListener('click', () => el('lightbox').close());

// The agent drives the same functions a person does.
setUpAsk({
  context: () => ({
    city: current?.city || location.hash.split('/')[1] || DEFAULT_CITY,
    property: current?.detail ? { kind: current.kind, id: current.id, name: current.detail.name } : null,
  }),
  actions: {
    open_property: ({ city, kind, id }) => { location.hash = `#/${city}/${kind}/${id}`; },
    show_list: ({ city, ids }) => {
      if (location.hash !== `#/${city}`) location.hash = `#/${city}`;
      setTimeout(() => showOnly(ids), 400);
    },
    mark_floors: ({ floors }) => { if (current?.floors) { current.marked = new Set(floors); repaint(); current.record.show('floors'); } },
    set_view: ({ view }) => setView(view),
    open_scan: ({ scan_id }) => openScan(current?.twin?.scans.find((s) => s.id === scan_id)),
  },
});

addEventListener('hashchange', route);
route();
