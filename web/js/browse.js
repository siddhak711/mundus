// City view: a filterable list of every property and home, mirrored on a map.
import * as L from 'leaflet';
import { fetchIndex } from './api.js';
import { onHoverIntent, prefetchProperty } from './prefetch.js';
import { compact, escapeHtml, moneyCompact, number, plural, CITY_NAMES } from './format.js';

const PAGE = 60;
const SORTS = {
  scans: (a, b) => b.scans - a.scans || (b.sizeSf || 0) - (a.sizeSf || 0),
  size: (a, b) => (b.sizeSf || 0) - (a.sizeSf || 0),
  stories: (a, b) => (b.stories || 0) - (a.stories || 0),
  available: (a, b) => b.availableSf - a.availableSf,
  tenancies: (a, b) => b.tenancies - a.tenancies,
  newest: (a, b) => (b.yearBuilt || 0) - (a.yearBuilt || 0),
};
const TYPE_COLORS = { Office: '#1d4fd7', Multifamily: '#c2761b', Home: '#1c8a68', Industrial: '#6a3fc0' };
const CITY_VIEW = { houston: [[29.76, -95.37], 11], 'los-angeles': [[34.05, -118.33], 11] };

const els = {
  search: document.querySelector('#search'),
  type: document.querySelector('#type-filter'),
  sort: document.querySelector('#sort'),
  count: document.querySelector('#result-count'),
  results: document.querySelector('#results'),
};

let map;
let markerLayer;
let state = { city: null, items: [], shown: [], limit: PAGE };

export const linkTo = (city, item) => `#/${city}/${item.kind}/${item.id}`;

function facts(item) {
  if (item.kind === 'home') {
    const price = item.price ? `${moneyCompact(item.price)}${item.forRent ? ' a month' : ''}` : null;
    return [price, item.beds && `${item.beds} bed`, item.baths && `${item.baths} bath`, item.sizeSf && `${number(item.sizeSf)} sq ft`];
  }
  return [
    item.stories && `${item.stories} ${item.stories === 1 ? 'story' : 'stories'}`,
    item.units ? `${number(item.units)} units` : item.sizeSf && `${compact(item.sizeSf)} sq ft`,
    item.availableSf > 0 && `${compact(item.availableSf)} sq ft available`,
    item.rentFrom && `from $${number(item.rentFrom)}`,
  ];
}

function resultHtml(item) {
  const photo = item.photo
    ? `<img src="${escapeHtml(item.photo)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : '<div class="no-photo"></div>';
  const line = facts(item).filter(Boolean).join(', ');
  const scans = item.scans ? `${plural(item.scans, 'interior scan')}` : 'No interior scan';
  return `<li><a class="result" href="${linkTo(state.city, item)}" data-id="${item.id}">
    ${photo}
    <div>
      <h3>${escapeHtml(item.name)}</h3>
      <p>${escapeHtml(item.type)}${item.name !== item.address ? `, ${escapeHtml(item.address)}` : ''}</p>
      <p class="facts">${escapeHtml(line)}</p>
      <p>${scans}</p>
    </div></a></li>`;
}

function applyFilters() {
  const text = els.search.value.trim().toLowerCase();
  const type = els.type.value;
  state.shown = state.items
    .filter((item) => (!type || item.type === type) && (!text || `${item.name} ${item.address}`.toLowerCase().includes(text)))
    .sort(SORTS[els.sort.value]);
  state.limit = PAGE;
  renderList();
  renderMarkers();
}

function renderList() {
  const visible = state.shown.slice(0, state.limit);
  els.results.innerHTML = visible.map(resultHtml).join('');
  const total = state.shown.length;
  els.count.textContent = total
    ? `${number(total)} in ${CITY_NAMES[state.city]}${total > visible.length ? `, showing the first ${visible.length}` : ''}`
    : 'Nothing matches. Clear the search or pick another type.';
}

function renderMarkers() {
  markerLayer.clearLayers();
  for (const item of state.shown) {
    const marker = L.circleMarker([item.lat, item.lon], {
      radius: Math.min(9, 3 + Math.sqrt(item.scans)), weight: 1, color: '#ffffff',
      fillColor: TYPE_COLORS[item.type] || '#5d6975', fillOpacity: 0.85,
    });
    marker.bindTooltip(`<span class="map-tip">${escapeHtml(item.name)}</span><br>${escapeHtml(item.type)}`, { direction: 'top' });
    marker.on('click', () => { location.hash = linkTo(state.city, item); });
    marker.on('mouseover', () => prefetchProperty(item.kind, item.id));
    markerLayer.addLayer(marker);
  }
}

function setUpOnce() {
  if (map) return;
  map = L.map('map', { preferCanvas: true, zoomControl: true });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors', maxZoom: 19,
  }).addTo(map);
  markerLayer = L.layerGroup().addTo(map);

  els.search.addEventListener('input', applyFilters);
  onHoverIntent(els.results, '.result[data-id]', (a) => {
    const item = state.shown.find((i) => String(i.id) === a.dataset.id);
    return item && [item.kind, item.id];
  });
  els.type.addEventListener('change', applyFilters);
  els.sort.addEventListener('change', applyFilters);
  els.results.addEventListener('scroll', () => {
    const nearEnd = els.results.scrollTop + els.results.clientHeight > els.results.scrollHeight - 400;
    if (nearEnd && state.limit < state.shown.length) {
      state.limit += PAGE;
      renderList();
    }
  });
}

export async function showCity(city) {
  setUpOnce();
  if (state.city !== city) {
    state.city = city;
    state.items = await fetchIndex(city);
    const counts = {};
    for (const item of state.items) counts[item.type] = (counts[item.type] || 0) + 1;
    els.type.innerHTML = `<option value="">All types (${number(state.items.length)})</option>` + Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([type, n]) => `<option value="${escapeHtml(type)}">${escapeHtml(type)} (${number(n)})</option>`).join('');
    els.search.value = '';
    map.setView(...CITY_VIEW[city]);
    applyFilters();
  }
  requestAnimationFrame(() => map.invalidateSize());
}

/** Used by the agent to narrow the list to specific properties. */
export function showOnly(ids) {
  const wanted = new Set(ids.map(String));
  state.shown = state.items.filter((item) => wanted.has(String(item.id)));
  state.limit = PAGE;
  renderList();
  renderMarkers();
  if (state.shown.length) map.fitBounds(L.latLngBounds(state.shown.map((i) => [i.lat, i.lon])).pad(0.3));
}
