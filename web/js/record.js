// The left-hand record for one property: CoStar facts, floor-by-floor leasing, interior scans, aerial facts.
import { obliqueUrl, site } from './api.js';
import { compact, escapeHtml as h, money, moneyCompact, number, rate, squareFeet, CITY_NAMES } from './format.js';

function figures(pairs) {
  const shown = pairs.filter(([, value]) => value);
  return `<dl class="figures">${shown.map(([label, value]) => `<div><dt>${h(label)}</dt><dd>${h(value)}</dd></div>`).join('')}</dl>`;
}

function rows(pairs) {
  const shown = pairs.filter(([, value]) => value);
  if (!shown.length) return '';
  return `<ul class="rows">${shown.map(([k, v]) => `<li><span class="k">${h(k)}</span><span class="v">${h(v)}</span></li>`).join('')}</ul>`;
}

function photoGrid(photos, limit = 9) {
  if (!photos?.length) return '';
  return `<div class="photo-grid">${photos.slice(0, limit).map((p) =>
    `<img src="${h(p.url)}" alt="${h(p.caption || p.label || '')}" loading="lazy" referrerpolicy="no-referrer">`).join('')}</div>`;
}

// ---- overview ---------------------------------------------------------------
function commercialOverview(d, twin) {
  const a = d.availability;
  const apt = d.apartments;
  const heightFt = Math.round(twin.building.top * 3.28084);
  const sale = d.sales?.find((s) => s.price);
  const parts = [];

  parts.push(figures([
    ['Stories', d.stories ? String(d.stories) : `${twin.building.stories} (estimated)`],
    ['Height, from aerial survey', `${number(heightFt)} ft`],
    [apt ? 'Units' : 'Rentable area', apt?.units ? number(apt.units) : d.sizeSf && `${compact(d.sizeSf)} sq ft`],
    ['Built', d.yearBuilt && String(d.yearBuilt)],
    ['Available now', a?.totalSf ? `${compact(a.totalSf)} sq ft` : apt?.unitsAvailable ? `${apt.unitsAvailable} units` : null],
    [apt ? 'Rent' : 'Asking rent', a?.rateLow ? `$${a.rateLow}–${a.rateHigh} / sq ft / yr` : apt?.minRent ? `$${number(apt.minRent)}–${number(apt.maxRent)} / mo` : null],
  ]));

  if (a) {
    parts.push(`<section><h2>Leasing</h2>${rows([
      ['Spaces on the market', `${a.count} with ${a.broker || 'the owner'}`],
      ['Largest contiguous block', squareFeet(a.maxContiguousSf)],
      ['Share of building available', d.sizeSf ? `${((a.totalSf / d.sizeSf) * 100).toFixed(1)}%` : null],
      ['Lease type', a.service],
    ])}</section>`);
  }
  if (apt?.plans?.length) {
    parts.push(`<section><h2>Floor plans</h2><table>
      <tr><th>Plan</th><th>Size</th><th class="num">Rent</th><th class="num">Open</th></tr>
      ${apt.plans.map((p) => `<tr><td>${h(p.name || `${p.beds} bed`)}<br><span class="sub">${p.beds ?? 0} bed, ${p.baths ?? 0} bath</span></td>
        <td>${number(p.sfMin)} sq ft</td><td class="num">${p.rentMin ? `$${number(p.rentMin)}` : ''}</td><td class="num">${p.available ?? ''}</td></tr>`).join('')}
    </table>${apt.manager ? `<p class="sub">Managed by ${h(apt.manager)}</p>` : ''}</section>`);
  }
  if (sale) {
    const whole = sale.interestPercent ? sale.price / (sale.interestPercent / 100) : sale.price;
    parts.push(`<section><h2>Last sale</h2>${rows([
      ['Date', sale.date],
      ['Price', `${moneyCompact(sale.price)}${sale.interestPercent ? ` for a ${sale.interestPercent}% interest` : ''}${sale.portfolio ? ' (portfolio sale)' : ''}`],
      ['Implied value', !sale.portfolio && d.sizeSf ? `${moneyCompact(whole)}, ${money(whole / d.sizeSf)} per sq ft` : null],
      ['Cap rate', sale.capRate ? `${sale.capRate}%` : null],
    ])}</section>`);
  }
  if (d.leed?.length) {
    parts.push(`<section><h2>LEED certification</h2>${rows(d.leed.map((l) => [String(l.year), l.level]))}</section>`);
  }
  return parts.join('');
}

function homeOverview(d, twin) {
  return [
    figures([
      [d.transaction === 'For Rent' ? 'Rent per month' : 'Price', money(d.price)],
      ['Status', d.status],
      ['Bedrooms', d.beds && String(d.beds)],
      ['Bathrooms', d.baths && String(d.baths)],
      ['Living area', squareFeet(d.sizeSf)],
      ['Roof height, from aerial survey', `${Math.round(twin.building.top * 3.28084)} ft`],
    ]),
    `<section><h2>Listing</h2>${rows([
      ['Listed', d.listDate],
      ['Days on market', d.daysOnMarket && String(d.daysOnMarket)],
      ['Price per sq ft', d.price && d.sizeSf && d.transaction !== 'For Rent' ? money(d.price / d.sizeSf) : null],
      ['Lot', d.lotAcres ? `${d.lotAcres.toFixed(2)} acres` : null],
      ['Built', d.yearBuilt && String(d.yearBuilt)],
      ['Annual taxes', money(d.taxes)],
      ['Subdivision', d.subdivision],
    ])}</section>`,
    d.highlights?.length ? `<section><h2>Highlights</h2><ul class="rows">${d.highlights.filter(Boolean).map((x) => `<li><span>${h(x)}</span></li>`).join('')}</ul></section>` : '',
  ].join('');
}

function overviewPane(d, twin) {
  return `${d.kind === 'home' ? homeOverview(d, twin) : commercialOverview(d, twin)}
    ${d.photos?.length ? `<section><h2>Photos</h2>${photoGrid(d.photos)}</section>` : ''}
    ${d.description ? `<section><h2>About</h2><p class="prose">${h(d.description.slice(0, 900))}${d.description.length > 900 ? '…' : ''}</p></section>` : ''}`;
}

// ---- floors -------------------------------------------------------------------
function floorsPane(d, floors) {
  const current = {};
  for (const t of d.tenancies || []) {
    if (t.to != null) continue;
    const entry = (current[t.tenant] ||= { sf: 0, floors: new Set() });
    entry.sf += t.sf || 0;
    if (t.floor) entry.floors.add(t.floor);
  }
  const tenants = Object.entries(current).sort((a, b) => b[1].sf - a[1].sf).slice(0, 40);
  const spaces = (d.availability?.allSpaces || d.availability?.spaces || []).slice().sort((a, b) => (b.floor || 0) - (a.floor || 0));

  return `
    <p class="legend"><span><i class="key convertible"></i>Convertible now</span><span><i class="key partial"></i>Partly vacant</span><span><i class="key occupied"></i>Leased</span><span><i class="key scanned"></i>Interior scan</span>${floors.walkthroughFloors?.length ? '<span><i class="key walk"></i>Walkthrough: click to go inside</span>' : ''}</p>
    <section id="floor-focus"></section>
    ${spaces.length ? `<section><h2>Available space</h2><table>
      <tr><th>Floor</th><th>Suite</th><th class="num">Size</th><th class="num">Asking</th></tr>
      ${spaces.map((s) => `<tr data-floor="${s.floor || ''}"><td>${s.floor ?? ''}</td><td>${h(s.suite || '')}${s.fullFloor ? '<br><span class="sub">Full floor</span>' : ''}</td>
        <td class="num">${number(s.sf)}</td><td class="num">${s.rate ? `$${s.rate.toFixed(2)}` : ''}</td></tr>`).join('')}
    </table></section>` : ''}
    ${tenants.length ? `<section><h2>Current tenants</h2><ul class="rows" id="tenant-list">
      ${tenants.map(([name, t]) => `<li><button class="rowlink" type="button" data-floors="${[...t.floors].join(',')}">
        <span>${h(name)}</span><span class="v">${number(t.sf)} sq ft</span></button></li>`).join('')}
    </ul><p class="sub">Point at a tenant to mark its floors on the model.</p></section>` : ''}
    ${floors.hasHistory ? '' : '<p class="sub">CoStar has no floor-level tenant records for this property.</p>'}`;
}

export function floorFocusHtml(info, scans) {
  if (!info) return '';
  const lines = [];
  for (const t of info.tenants) lines.push([t.tenant, `${number(t.sf)} sq ft${t.from ? `, since ${t.from}` : ''}`]);
  for (const s of info.available) lines.push([`Suite ${s.suite || ''} available`, `${number(s.sf)} sq ft at ${rate(s.rate)}`]);
  const scanButtons = scans.map((s) => `<button class="quiet" type="button" data-open-scan="${s.id}">Show the scan of ${h(s.name)}</button>`).join('');
  const c = info.conversion;
  const status = c ? `<p class="sub">${h(FLOOR_STATUS[c.status] || '')}${c.vacantSf ? `: ${number(c.vacantSf)} sq ft available (${Math.round((c.vacantShare || 0) * 100)}%)` : ''}</p>` : '';
  const walk = info.walkthrough ? `<a class="walk-link" href="${h(info.walkthrough.href)}">Walk floor ${info.floor}${info.walkthrough.suite ? ` (suite ${h(info.walkthrough.suite)})` : ''}</a>` : '';
  return `<h2>Floor ${info.floor}</h2>${status}${lines.length ? rows(lines) : '<p class="sub">No tenant or listing on record for this floor.</p>'}${walk}${scanButtons}`;
}

// ---- conversion (pipeline/conversion.py) ------------------------------------------
const FLOOR_STATUS = { convertible: 'Convertible now', partial: 'Partly vacant', leased: 'Leased', no_data: 'No record' };
const CHECK_MARK = { pass: '✓', fail: '✕', review: '!', unknown: '?' };
const STATUS_CLASS = { strong: 'strong', possible: 'possible', review: 'review' };
const pct = (x) => (x == null ? '' : `${Math.round(x * 100)}%`);

function conversionPane(c) {
  const fit = c.fit;
  const open = c.floors.filter((f) => f.status === 'convertible' || f.status === 'partial').sort((a, b) => b.floor - a.floor);
  const d = c.daylightPlate;
  return `
    <section><p><span class="conv-pill ${STATUS_CLASS[c.status] || 'other'}">${h(c.statusLabel)}</span>
      ${fit ? `<b class="conv-fit">Fit ${fit.score} / 100</b>` : ''}</p>
      <p class="sub">Screened against LA's Citywide Adaptive Reuse Ordinance and for how well the floors suit apartments.
        <a href="${site('city/')}">See every LA office on the map</a>.</p></section>
    ${open.length ? `<section><h2>Floors with space now</h2><table>
      <tr><th>Floor</th><th>Status</th><th class="num">Available</th></tr>
      ${open.map((f) => `<tr data-floor="${f.floor}"><td>${f.floor}</td><td>${h(FLOOR_STATUS[f.status])}${f.walkthrough ? '<br><span class="sub">Walkthrough</span>' : ''}</td>
        <td class="num">${number(f.vacantSf)} sq ft<br><span class="sub">${pct(f.vacantShare)}</span></td></tr>`).join('')}
    </table><p class="sub">A floor is convertible now when half or more of it is listed. Pick a row to mark it on the model.</p></section>` : ''}
    <section><h2>Adaptive Reuse eligibility</h2>
      <ul class="conv-checks">${c.checks.map((k) => `<li class="c-${k.result}"><b>${CHECK_MARK[k.result]}</b><span>${h(k.name)}<span class="sub">${h(k.note)}</span></span></li>`).join('')}</ul></section>
    ${fit ? `<section><h2>Fit for apartments</h2>
      <ul class="conv-parts">${fit.parts.map((p) => `<li><span>${h(p.name)}<span class="sub">${h(p.note)}</span></span>
        <span class="bar"><span style="width:${(p.points / p.of) * 100}%"></span></span><b>${p.points}/${p.of}</b></li>`).join('')}</ul></section>` : ''}
    ${d ? `<section><h2>Daylight, measured on floor ${d.floor}</h2>
      <ul class="conv-parts">${[25, 30, 35].map((ft) => `<li><span>Within ${ft} ft of a window</span>
        <span class="bar day"><span style="width:${(d[`within${ft}ft`] || 0) * 100}%"></span></span><b>${pct(d[`within${ft}ft`])}</b></li>`).join('')}</ul>
      <p class="sub">Share of the floor plate, measured from the Matterport floor plan of ${h(d.name)}. Plate about
        ${number(d.plateSf)} sq ft; the deepest point is ${Math.round(d.deepestFt)} ft from a window, and
        ${number(d.beyond30ftSf)} sq ft (core and interior rooms) lies beyond 30 ft.</p></section>` : ''}`;
}

// ---- interiors ------------------------------------------------------------------
function scanCard(s, design) {
  return `<article class="scan-card" data-scan="${s.id}">
    <h3>${h(s.name)}</h3>
    <p class="sub">${[s.floor && `Floor ${s.floor}`, s.areaSf && `${number(s.areaSf)} sq ft scanned`, `${s.capturePoints} capture points`].filter(Boolean).join(', ')}</p>
    ${s.roomTypes.length ? `<p class="sub">${h(s.roomTypes.slice(0, 6).join(', '))}</p>` : ''}
    <div class="scan-detail"></div>
    <div class="actions">
      <button class="primary" type="button" data-open-scan="${s.id}">Show in model</button>
      <button class="quiet" type="button" data-tour="${s.id}">Walk through</button>
      ${design ? `<button class="quiet" type="button" data-design="${s.id}" title="Ask the apartment agent to lay out units on this space">Design apartments</button>` : ''}
    </div>
  </article>`;
}

function interiorsPane(twin, design) {
  if (!twin.scans.length) return '<p class="sub">No Matterport scan is linked to this property.</p>';
  return `${twin.scans.map((s) => scanCard(s, design)).join('')}
    ${twin.scansOmitted ? `<p class="sub">${twin.scansOmitted} more scans are linked to this property and not listed here.</p>` : ''}`;
}

// ---- aerial ------------------------------------------------------------------
function aerialPane(d, twin) {
  const directions = ['north', 'east', 'south', 'west'];
  return `<section><h2>From Vexcel aerial survey</h2>${rows(twin.aerialFacts)}
      ${rows([['Ground elevation', `${twin.groundElevation} m`], ['Buildings mapped nearby', String(twin.neighbours.length)]])}</section>
    <section><h2>Angled views</h2><div class="photo-grid" id="obliques">
      ${directions.map((dir) => `<img data-src="${obliqueUrl(d.kind, d.id, dir)}" alt="Looking ${dir}">`).join('')}
    </div><p class="sub">Looking north, east, south and west. Views are missing where the aircraft did not capture one.</p></section>`;
}

// ---- controller -----------------------------------------------------------------
export function renderRecord(container, { detail, twin, floors, city, conversion = null, handlers }) {
  const tabs = [['overview', 'Overview']];
  if (detail.kind !== 'home' && twin.building.stories > 1) tabs.push(['floors', 'Floors']);
  if (conversion?.floors) tabs.push(['conversion', 'Conversion']);
  tabs.push(['interiors', `Interiors (${twin.scans.length})`], ['aerial', 'Aerial']);

  const subtitle = detail.kind === 'home'
    ? detail.type
    : [detail.type, detail.buildingClass && `Class ${detail.buildingClass}`, detail.stars && `${detail.stars}-star`].filter(Boolean).join(', ');

  container.innerHTML = `
    <div class="record-head">
      <a class="back" href="#/${city}">All ${h(CITY_NAMES[city])} properties</a>
      <h1>${h(detail.name)}</h1>
      <p class="address">${h(detail.address)}</p>
      <p class="sub">${h(subtitle)}</p>
    </div>
    <div class="tabs" role="tablist">${tabs.map(([id, label]) => `<button type="button" role="tab" data-tab="${id}">${h(label)}</button>`).join('')}</div>
    <div class="pane" id="pane"></div>`;
  container.scrollTop = 0;

  const pane = container.querySelector('#pane');
  const builders = {
    overview: () => overviewPane(detail, twin),
    floors: () => floorsPane(detail, floors),
    conversion: () => conversionPane(conversion),
    interiors: () => interiorsPane(twin, detail.kind !== 'home' && Boolean(handlers.onDesign)),
    aerial: () => aerialPane(detail, twin),
  };
  let active = null;
  let openScan = null; // { id, cutRange, photos }

  function decorateOpenScan() {
    pane.querySelectorAll('.scan-card').forEach((card) => {
      const isOpen = openScan && card.dataset.scan === openScan.id;
      card.classList.toggle('is-open', Boolean(isOpen));
      const detailBox = card.querySelector('.scan-detail');
      const button = card.querySelector('[data-open-scan]');
      button.textContent = isOpen ? 'Put back' : 'Show in model';
      if (!isOpen) { detailBox.innerHTML = ''; return; }
      const { min, max, initial } = openScan.cutRange;
      detailBox.innerHTML = `<label class="sub">Cut height
          <input type="range" min="${min.toFixed(2)}" max="${max.toFixed(2)}" step="0.02" value="${initial.toFixed(2)}" data-cut></label>
        ${photoGrid(openScan.photos, 6)}`;
      card.scrollIntoView({ block: 'nearest' });
    });
  }

  function show(tab) {
    if (!builders[tab]) return;
    active = tab;
    container.querySelectorAll('[data-tab]').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === tab)));
    pane.innerHTML = builders[tab]();
    if (tab === 'interiors') decorateOpenScan();
    if (tab === 'aerial') {
      pane.querySelectorAll('#obliques img').forEach((img) => {
        img.addEventListener('error', () => img.remove());
        img.src = img.dataset.src;
      });
    }
  }

  container.addEventListener('click', (event) => {
    const tab = event.target.closest('[data-tab]');
    if (tab) return show(tab.dataset.tab);
    const open = event.target.closest('[data-open-scan]');
    if (open) {
      const id = open.dataset.openScan;
      return openScan?.id === id ? handlers.onCloseScan() : handlers.onOpenScan(twin.scans.find((s) => s.id === id));
    }
    const tour = event.target.closest('[data-tour]');
    if (tour) return handlers.onTour(twin.scans.find((s) => s.id === tour.dataset.tour));
    const design = event.target.closest('[data-design]');
    if (design) return handlers.onDesign(twin.scans.find((s) => s.id === design.dataset.design));
    const row = event.target.closest('tr[data-floor]');
    if (row?.dataset.floor) handlers.onFloorFocus(Number(row.dataset.floor));
  });
  container.addEventListener('input', (event) => {
    if (event.target.matches('[data-cut]')) handlers.onCut(Number(event.target.value));
  });
  container.addEventListener('pointerover', (event) => {
    const tenant = event.target.closest('[data-floors]');
    handlers.onTenantHover(tenant ? tenant.dataset.floors.split(',').filter(Boolean).map(Number) : []);
  });

  show('overview');

  return {
    show,
    focusFloor(info) {
      if (active !== 'floors') show('floors');
      const box = pane.querySelector('#floor-focus');
      if (box) {
        box.innerHTML = floorFocusHtml(info, info.scans);
        container.scrollTo({ top: 0, behavior: 'smooth' });
      }
    },
    setOpenScan(scan) {
      openScan = scan;
      if (scan && active !== 'interiors') show('interiors');
      else if (active === 'interiors') decorateOpenScan();
    },
  };
}
