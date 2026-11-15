// LA office-to-housing map: every commercial building in the kit, coloured by its conversion screen. A building opens in
// Atlas's 3-D model, where each floor shows its tenants and vacancy and a walkthrough floor can be entered directly.
import * as L from 'leaflet';
import { escapeHtml, number } from '/js/format.js';

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

let data = null;
let map, layer;
const markers = new Map();
const shownGroups = new Set(GROUPS.filter((g) => g.on).map((g) => g.key));
let listLimit = PAGE;
const modelUrl = (id) => `/#/los-angeles/commercial/${id}`;   // Atlas's 3-D model of the building

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
    const m = L.circleMarker([b.lat, b.lon], {
      radius: g.radius, weight: g.key === 'other' ? 0 : 1,
      color: '#ffffff', fillColor: g.color, fillOpacity: g.key === 'other' ? 0.55 : 0.92,
    });
    m.bindTooltip(`<span class="map-tip">${escapeHtml(b.name)}</span><br>${escapeHtml(data.statusLabels[b.status] || b.status)}`
      + (b.score != null ? ` · fit ${b.score}` : ''), { direction: 'top' });
    m.on('click', () => { location.href = modelUrl(b.id); });      // every building opens in Atlas's 3-D model
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
    return `<li><a class="row" href="${modelUrl(b.id)}">
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
    if (el.scrollTop + el.clientHeight > el.scrollHeight - 300) { listLimit += PAGE; renderList(); }
  });
}

start();
