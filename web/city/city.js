// LA office-to-housing view: every commercial building on a map, coloured by its conversion screen, and a
// floor-by-floor view of one building that links into the walkthrough.
//   /city/            the map and the ranked list
//   /city/#/233899    one building: eligibility, fit and every floor
import * as L from 'leaflet';
import { compact, escapeHtml, number } from '/js/format.js';

const $ = (id) => document.getElementById(id);
const LA = [[34.05, -118.33], 11];
const PAGE = 80;

// Map groups, in legend order. Status values come from pipeline/conversion.py.
const GROUPS = [
  { key: 'strong', label: 'Strong candidate', note: 'eligible by right, good fit', color: '#0e8a5f', radius: 7, on: true },
  { key: 'possible', label: 'Eligible, weaker fit', note: 'eligible by right', color: '#d99a00', radius: 5.5, on: true },
  { key: 'review', label: 'Eligible with review', note: '5 to 15 years old, or a manufacturing zone', color: '#7a4fd0', radius: 5.5, on: true },
  { key: 'other', label: 'Not a candidate', note: 'other offices and buildings', color: '#98a2ad', radius: 2.5, on: true,
    statuses: ['zone_blocked', 'too_new', 'unknown_age', 'outside_city', 'not_office'] },
];
const groupOf = (status) => GROUPS.find((g) => g.key === status || (g.statuses || []).includes(status)) || GROUPS[3];
const CANDIDATE = new Set(['strong', 'possible', 'review']);

const FLOOR_STATUS = {
  convertible: { label: 'Convertible now', note: 'half or more of the floor is available', color: '#0e8a5f' },
  partial: { label: 'Partly vacant', note: 'some space available', color: '#d99a00' },
  leased: { label: 'Leased', note: 'tenants, nothing available', color: '#9aa5b1' },
  no_data: { label: 'No record', note: 'no current tenant or listing', color: '#c9d0d7' },
};

let data = null;
let map, layer;
const markers = new Map();
const shownGroups = new Set(GROUPS.filter((g) => g.on).map((g) => g.key));
let listLimit = PAGE;
let selected = null;   // { id, record, floor }

// ---- data ---------------------------------------------------------------------
async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw Object.assign(new Error(`${url}: ${r.status}`), { status: r.status });
  return r.json();
}

function missingData() {
  $('overview').innerHTML = `<div class="side-head"><h1>No screen yet</h1>
    <p class="lede">This view reads <code>data/conversion/los-angeles.json</code>. Build it from the CoStar kit:</p>
    <pre>python pipeline/build_index.py &lt;kit folder&gt;\npython pipeline/conversion.py</pre></div>`;
}

// ---- map ----------------------------------------------------------------------
function setUpMap() {
  map = L.map('map', { preferCanvas: true, zoomControl: true }).setView(...LA);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors', maxZoom: 19 }).addTo(map);
  layer = L.layerGroup().addTo(map);
}

function drawMarkers() {
  layer.clearLayers();
  markers.clear();
  // grey first, so candidates sit on top
  const order = [...data.buildings].sort((a, b) => GROUPS.indexOf(groupOf(b.status)) - GROUPS.indexOf(groupOf(a.status)));
  for (const b of order) {
    const g = groupOf(b.status);
    if (!shownGroups.has(g.key)) continue;
    const isSel = selected && String(selected.id) === String(b.id);
    const m = L.circleMarker([b.lat, b.lon], {
      radius: isSel ? g.radius + 4 : g.radius, weight: isSel ? 3 : (g.key === 'other' ? 0 : 1),
      color: isSel ? '#17212b' : '#ffffff', fillColor: g.color, fillOpacity: g.key === 'other' ? 0.55 : 0.92,
    });
    m.bindTooltip(`<span class="map-tip">${escapeHtml(b.name)}</span><br>${escapeHtml(data.statusLabels[b.status] || b.status)}`
      + (b.score != null ? ` · fit ${b.score}` : ''), { direction: 'top' });
    if (CANDIDATE.has(b.status)) m.on('click', () => { location.hash = `#/${b.id}`; });
    layer.addLayer(m);
    markers.set(String(b.id), m);
  }
}

// ---- overview -----------------------------------------------------------------
function renderLegend() {
  const counts = {};
  for (const b of data.buildings) counts[groupOf(b.status).key] = (counts[groupOf(b.status).key] || 0) + 1;
  $('legend').innerHTML = GROUPS.map((g) => `<label class="legend-row">
      <input type="checkbox" data-group="${g.key}" ${shownGroups.has(g.key) ? 'checked' : ''}>
      <i style="background:${g.color}"></i><span><b>${g.label}</b> ${number(counts[g.key] || 0)}<small>${g.note}</small></span>
    </label>`).join('');
  $('legend').querySelectorAll('input').forEach((box) => box.addEventListener('change', () => {
    box.checked ? shownGroups.add(box.dataset.group) : shownGroups.delete(box.dataset.group);
    drawMarkers();
    renderList();
  }));
}

function candidates() {
  const text = $('search').value.trim().toLowerCase();
  return data.buildings
    .filter((b) => CANDIDATE.has(b.status) && shownGroups.has(groupOf(b.status).key))
    .filter((b) => !text || `${b.name} ${b.address}`.toLowerCase().includes(text))
    .sort((a, b) => (b.walkthrough - a.walkthrough) || (b.score ?? -1) - (a.score ?? -1) || (b.availableSf - a.availableSf));
}

function renderList() {
  const rows = candidates();
  $('count').textContent = rows.length
    ? `${number(rows.length)} candidates, best fit first${rows.length > listLimit ? `; showing ${listLimit}` : ''}`
    : 'No candidate matches. Clear the search or turn a group back on.';
  $('list').innerHTML = rows.slice(0, listLimit).map((b) => {
    const g = groupOf(b.status);
    const facts = [b.stories && `${b.stories} floors`, b.yearBuilt && `built ${b.yearBuilt}`,
      b.vacancy != null && `${Math.round(b.vacancy * 100)}% available`,
      b.convertibleFloors && `${b.convertibleFloors} convertible ${b.convertibleFloors === 1 ? 'floor' : 'floors'}`].filter(Boolean);
    return `<li><a class="row" href="#/${b.id}">
      <i style="background:${g.color}"></i>
      <span><b>${escapeHtml(b.name)}</b>${b.walkthrough ? ' <em class="tag">Walkthrough</em>' : ''}
        <small>${escapeHtml(b.name !== b.address ? b.address : '')}</small>
        <small>${escapeHtml(facts.join(' · '))}</small></span>
      <span class="score" title="Fit score out of 100">${b.score ?? ''}</span></a></li>`;
  }).join('');
}

function renderMethod() {
  $('method').innerHTML = `
    <p><b>Eligible</b> means an office building inside the City of Los Angeles that is at least 15 years old, which the
      Citywide Adaptive Reuse Ordinance (in effect Feb 1, 2026) allows to become housing by right or with administrative
      review. Buildings 5 to 15 years old need a Zoning Administrator's approval. The site must also be zoned
      multifamily, commercial, parking or public facilities, read from the zoning code in the CoStar record.
      Manufacturing zones qualify only in certain Adaptive Reuse subareas, with review, so they show as eligible with
      review. Codes the screen cannot read (downtown's new zoning code) are flagged for a check on ZIMAS.</p>
    <p><b>Fit</b> (0 to 100) adds vacancy (50 points at 30% available), floor plate size (30 points under 20,000 sq ft,
      where most of a floor is near a window) and building class (20 for class C, 15 for B, 5 for A). A strong candidate
      scores ${'≥'} 60. These are rules of thumb from conversion studies, not code requirements.</p>
    <p><b>Convertible floor</b>: half or more of the floor is listed as available in CoStar.</p>
    <p>"In the City of LA" is judged from the postal place name, so a few buildings near the city line may be misplaced.</p>
    <ul>${(data.sources || []).map((s) => `<li><a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.label)}</a></li>`).join('')}</ul>`;
}

// ---- one building -------------------------------------------------------------
const pct = (x) => (x == null ? '' : `${Math.round(x * 100)}%`);
const CHECK_MARK = { pass: '✓', fail: '✕', review: '!', unknown: '?' };

function floorRowHtml(f, maxSf, rowH) {
  const s = FLOOR_STATUS[f.status];
  const width = f.sf && maxSf ? Math.max(30, (f.sf / maxSf) * 100) : 100;
  const fill = f.vacantShare != null ? f.vacantShare * 100 : 0;
  const isSel = selected.floor === f.floor;
  const showText = rowH >= 16;
  return `<button type="button" class="floor${isSel ? ' is-sel' : ''}" data-floor="${f.floor}" style="height:${rowH}px"
      aria-label="Floor ${f.floor}: ${s.label}${f.vacantSf ? `, ${number(f.vacantSf)} sq ft available` : ''}">
    <span class="fl-num">${showText || f.floor % 5 === 0 || f.floor === 1 ? f.floor : ''}</span>
    <span class="fl-track is-${f.status}" style="width:${width}%"><span class="fl-fill" style="width:${fill}%;background:${s.color}"></span>
      <span class="fl-marks">${f.scans ? '<span title="Matterport scan">◇</span>' : ''}${f.walkthrough ? '<span title="Walkthrough available">◉</span>' : ''}</span></span>
    <span class="fl-val">${showText && f.vacantSf ? compact(f.vacantSf) : ''}</span>
  </button>`;
}

function scansHtml(f) {
  if (!f.scans) return '';
  const items = f.scans.map((sc) => {
    const what = sc.fullFloor
      ? `whole floor: ${pct(sc.within30ft)} within 30 ft of a window, deepest point ${Math.round(sc.deepestFt)} ft`
      : `${number(sc.scannedSf)} sq ft suite (a suite's edges are mostly corridor walls, so daylight is not measured)`;
    return `<li>${escapeHtml(sc.name)}: ${what}</li>`;
  }).join('');
  return `<h4>Scanned</h4><ul>${items}</ul>`;
}

function daylightHtml(r) {
  const d = r.daylightPlate;
  if (!d) return '';
  const [w, h] = d.plateFt || [];
  return `<div class="daylight">
    <h3>Daylight, measured on floor ${d.floor}</h3>
    <div class="dl-bars">${[25, 30, 35].map((ft) => `<div><span>${ft} ft</span><span class="bar"><span style="width:${(d[`within${ft}ft`] || 0) * 100}%"></span></span><b>${pct(d[`within${ft}ft`])}</b></div>`).join('')}</div>
    <p class="sub">Share of the floor plate within that distance of a window. Plate about ${number(d.plateSf)} sq ft${w ? `, ${w} × ${h} ft` : ''};
      the deepest point is ${Math.round(d.deepestFt)} ft from a window and ${number(d.beyond30ftSf)} sq ft (core and interior rooms) lies beyond 30 ft.
      Measured from the Matterport floor plan of ${escapeHtml(d.name)}; distances are to the outer edge of the scanned floor, not to individual windows.</p>
  </div>`;
}

function floorDetailHtml(r, f) {
  if (!f) return '<p class="hint-line">Pick a floor to see its tenants, listed space and walkthrough.</p>';
  const s = FLOOR_STATUS[f.status];
  const size = f.sf ? `${number(f.sf)} sq ft${f.sizeSource !== 'measured' ? ` (${f.sizeSource} floor)` : ''}` : 'size unknown';
  const spaces = f.spaces.length
    ? `<ul>${f.spaces.map((sp) => `<li>Suite ${escapeHtml(sp.suite || '–')}: ${sp.fullFloor ? 'full floor' : `${number(sp.sf)} sq ft`}${sp.rate ? `, $${sp.rate.toFixed(2)}/sq ft` : ''}</li>`).join('')}</ul>`
    : '<p>No space listed.</p>';
  const tenants = f.tenants.length
    ? `<ul>${f.tenants.map((t) => `<li>${escapeHtml(t.name)}${t.sf ? `, ${number(t.sf)} sq ft` : ''}${t.to ? ` (lease to ${t.to})` : ''}</li>`).join('')}</ul>`
    : '<p>No current tenant recorded.</p>';
  const walk = f.walkthrough
    ? `<a class="walk-btn" href="${escapeHtml(f.walkthrough.url)}?building=${r.id}&floor=${f.floor}">Walk floor ${f.floor}${f.walkthrough.suite ? ` (suite ${escapeHtml(f.walkthrough.suite)})` : ''}</a>`
    : '<p class="hint-line">No walkthrough scanned for this floor yet.</p>';
  return `<div class="fl-detail">
    <h3>Floor ${f.floor} <span class="pill" style="background:${s.color}">${s.label}</span></h3>
    <p>${size} · ${f.vacantSf ? `${number(f.vacantSf)} sq ft available (${pct(f.vacantShare)})` : 'nothing listed'}</p>
    <h4>Listed space</h4>${spaces}
    <h4>Current tenants</h4>${tenants}
    ${scansHtml(f)}
    ${walk}
  </div>`;
}

function renderBuilding() {
  const r = selected.record;
  const floors = [...r.floors].reverse();
  const maxSf = Math.max(...r.floors.map((f) => f.sf || 0));
  const rowH = Math.max(7, Math.min(24, Math.floor(560 / Math.max(1, r.floors.length))));
  const counts = {};
  for (const f of r.floors) counts[f.status] = (counts[f.status] || 0) + 1;
  const convertibleSf = r.floors.filter((f) => f.status === 'convertible').reduce((n, f) => n + f.vacantSf, 0);
  const fit = r.fit;
  $('building').innerHTML = `
    <div class="side-head">
      <a class="back" href="#/">← All buildings</a>
      <h1>${escapeHtml(r.name)}</h1>
      <p class="lede">${escapeHtml(r.address || '')}</p>
      <p class="facts">${[r.stories && `${r.stories} floors`, r.yearBuilt && `built ${r.yearBuilt}`,
        r.sizeSf && `${number(r.sizeSf)} sq ft`, r.buildingClass && `class ${escapeHtml(r.buildingClass)}`].filter(Boolean).join(' · ')}</p>
      <p><span class="pill" style="background:${groupOf(r.status).color}">${escapeHtml(r.statusLabel)}</span>
        ${fit ? `<span class="fit">Fit ${fit.score} / 100</span>` : ''}</p>
    </div>
    <section class="block">
      <h2>Floors</h2>
      <p class="sub">${counts.convertible || 0} convertible now (${number(convertibleSf)} sq ft) · ${counts.partial || 0} partly vacant ·
        ${counts.leased || 0} leased · ${counts.no_data || 0} without a record</p>
      <div class="stack-wrap">
        <div class="stack" id="stack" role="group" aria-label="Floors, top to bottom">${floors.map((f) => floorRowHtml(f, maxSf, rowH)).join('')}</div>
        <div class="stack-side" id="floor-detail">${floorDetailHtml(r, r.floors.find((f) => f.floor === selected.floor))}</div>
      </div>
      <div class="fl-legend">${Object.entries(FLOOR_STATUS).map(([k, s]) => `<span><i class="key-${k}" style="background:${s.color}"></i>${s.label}</span>`).join('')}
        ${r.floors.some((f) => f.scans) ? '<span><b class="fl-walk-key">◇</b>Scanned</span>' : ''}<span><b class="fl-walk-key">◉</b>Walkthrough</span></div>
      ${r.unplacedVacantSf ? `<p class="sub">${number(r.unplacedVacantSf)} sq ft is listed without a floor and is not shown above.</p>` : ''}
    </section>
    <section class="block">
      <h2>Adaptive Reuse eligibility</h2>
      <ul class="checks">${r.checks.map((c) => `<li class="c-${c.result}"><b>${CHECK_MARK[c.result]}</b><span>${escapeHtml(c.name)}<small>${escapeHtml(c.note)}</small></span></li>`).join('')}</ul>
    </section>
    ${fit ? `<section class="block">
      <h2>Fit for apartments</h2>
      <ul class="parts">${fit.parts.map((p) => `<li><span>${escapeHtml(p.name)}<small>${escapeHtml(p.note)}</small></span>
        <span class="bar"><span style="width:${(p.points / p.of) * 100}%"></span></span><b>${p.points}/${p.of}</b></li>`).join('')}</ul>
      ${daylightHtml(r)}
    </section>` : ''}
    <p class="links"><a href="/#/los-angeles/commercial/${r.id}">Open the 3-D site model in Atlas</a></p>`;
  $('stack').querySelectorAll('.floor').forEach((btn) => btn.addEventListener('click', () => {
    selected.floor = Number(btn.dataset.floor);
    history.replaceState(null, '', `#/${r.id}/${selected.floor}`);
    renderBuilding();
  }));
}

async function openBuilding(id, floor) {
  try {
    const record = selected && String(selected.id) === id ? selected.record : await getJson(`/data/conversion/property/${id}.json`);
    const walkFloor = (record.floors.find((f) => f.walkthrough) || {}).floor;
    const bestFloor = (record.floors.find((f) => f.status === 'convertible') || {}).floor;
    selected = { id, record, floor: floor || walkFloor || bestFloor || null };
  } catch (e) {
    $('building').innerHTML = `<div class="side-head"><a class="back" href="#/">← All buildings</a><h1>Not screened</h1>
      <p class="lede">Building ${escapeHtml(id)} has no floor record. Only office buildings in the City of LA are screened.</p></div>`;
    selected = null;
  }
  $('overview').hidden = true;
  $('building').hidden = false;
  $('side').scrollTop = 0;
  if (selected) {
    renderBuilding();
    map.invalidateSize();
    const at = [selected.record.lat, selected.record.lon], zoom = Math.max(map.getZoom(), 15);
    // flyTo needs a sized map; a hidden or collapsed one gets a plain setView
    if (map.getSize().x > 0) map.flyTo(at, zoom, { duration: 0.8 }); else map.setView(at, zoom);
  }
  drawMarkers();
}

function closeBuilding() {
  selected = null;
  $('building').hidden = true;
  $('overview').hidden = false;
  drawMarkers();
}

function route() {
  const m = location.hash.match(/^#\/(\d+)(?:\/(\d+))?/);
  if (m) openBuilding(m[1], m[2] ? Number(m[2]) : null);
  else closeBuilding();
}

// ---- start --------------------------------------------------------------------
async function start() {
  setUpMap();
  try {
    data = await getJson('/data/conversion/los-angeles.json');
  } catch (e) {
    missingData();
    return;
  }
  const c = data.counts || {};
  $('note').textContent = `${number((c.strong || 0) + (c.possible || 0) + (c.review || 0))} candidates · CoStar kit, screened ${data.generated}`;
  renderLegend();
  renderList();
  renderMethod();
  drawMarkers();
  $('search').addEventListener('input', () => { listLimit = PAGE; renderList(); });
  $('side').addEventListener('scroll', () => {
    const el = $('side');
    if ($('overview').hidden) return;
    if (el.scrollTop + el.clientHeight > el.scrollHeight - 300) { listLimit += PAGE; renderList(); }
  });
  addEventListener('hashchange', route);
  route();
}

start();
