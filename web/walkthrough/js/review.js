// The review page after Submit: everything the agents produced for one floor, from the same saved study the walkthrough
// draws (layouts/<scan>.json) and the floor's facts (floors.json). Read-only; "Send to architect" prints it to PDF.
const Q = new URLSearchParams(location.search);
const SCAN = /^[A-Za-z0-9]{11}$/.test(Q.get('scan') || '') ? Q.get('scan') : 'cEvQ8q5GKZd';
const BUILDING = /^\d+$/.test(Q.get('building') || '') ? Q.get('building') : null;
const $ = (id) => document.getElementById(id);
const esc = (t) => String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const n0 = (v) => Math.round(v).toLocaleString('en-US');
const usd = (v) => `${v < 0 ? '−' : ''}$${n0(Math.abs(v))}`;
const usdM = (v) => `${v < 0 ? '−' : ''}$${(Math.abs(v) / 1e6).toFixed(2)}M`;
const pct = (v, d = 1) => `${(v * 100).toFixed(d)}%`;
const pill = (kind, text) => `<span class="pill ${kind}">${esc(text)}</span>`;

$('back').href = `./?scan=${SCAN}${BUILDING ? `&building=${BUILDING}` : ''}`;

const [L, floors] = await Promise.all([
  fetch(`layouts/${SCAN}.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  fetch('floors.json').then((r) => (r.ok ? r.json() : null)).catch(() => null),
]);
const F = floors?.floors?.[SCAN] || {};
if (!L) {
  $('main').innerHTML = `<div class="error"><h2>No agent results for this floor yet</h2><p class="muted" style="margin-top:8px">The review reads <code>layouts/${esc(SCAN)}.json</code>, which is made from a layout study by <code>scripts/layout_v4_to_viewer.py</code>.</p></div>`;
  throw new Error('no layout');
}
document.title = `${F.address ? F.address.split(',')[0] + ', ' : ''}floor ${F.floor ?? L.floor}: conversion review`;
$('top-title').textContent = `${F.building || 'Floor'} · floor ${F.floor ?? L.floor}`;

const M = L.money || {}, A = L.areas || {}, E = L.egress || {}, items = L.self_score?.items || {};
const units = L.units, n = units.length;
const checks = units.flatMap((u) => Object.entries(u.checks || {}).map(([k, c]) => ({ unit: u.id, rule: k, ...c })));
const fails = checks.filter((c) => !c.ok);
const groups = {
  compliance: ['LA zoning', 'Room size, daylight, escape', 'Exits and stairs', 'Accessibility', 'Fire, sound, ventilation', 'No hard failures'],
  structure: ['Detected columns', 'Hidden columns', 'Drains to the core', 'Loads and earthquake'],
  cost: ['Buyer yield', 'Owner view vs office', 'Share of floor rented', 'Unit size vs market'],
};
const sum = (names, k) => names.reduce((a, x) => a + (items[x]?.[k] || 0), 0);
const status = (it) => (!it ? pill('na', 'n/a') : it.points >= it.max - 1e-6 ? pill('ok', 'Pass') : it.points >= it.max * 0.6 ? pill('flag', 'Partial') : pill('bad', 'Weak'));
const scoreTable = (names) => `<table><thead><tr><th>Check</th><th>What the agent measured</th><th class="num">Points</th><th></th></tr></thead><tbody>${names.map((k) => {
  const it = items[k]; if (!it) return '';
  const w = Math.max(0, Math.min(1, it.points / it.max));
  return `<tr><td><b>${esc(k)}</b></td><td>${esc(it.measured)}</td><td class="num">${(+it.points.toFixed(2))} / ${it.max}<div class="meter" style="margin-top:4px"><i class="${w < 1 ? 'part' : ''}" style="width:${w * 100}%"></i></div></td><td>${status(it)}</td></tr>`;
}).join('')}</tbody></table>`;

// ---------- verdict ----------
const ownerOk = M.yoc_owner >= 0.055, buyerTarget = (() => { const m = /vs\s+([\d.]+)%/.exec(items['Buyer yield']?.measured || ''); return m ? +m[1] / 100 : null; })();
const money = `The owner earns ${pct(M.yoc_owner, 2)} on the conversion cost, ${M.vs_office < 0 ? `${usd(-M.vs_office)} a year less than the floor earns as office` : `${usd(M.vs_office)} a year more than as office`}, and a buyer paying ${usdM(M.acq)} for the floor would earn ${pct(M.yoc_buyer, 2)}${buyerTarget ? ` against the ${pct(buyerTarget, 2)} a buyer needs` : ''}.`;
const hardN = (L.self_score?.hard_breaks || []).length;
const verdict = (hardN ? `${hardN} hard failure${hardN > 1 ? 's' : ''} must be fixed before this goes to an architect. `
  : fails.length ? `No hard failures. ${fails.length} unit check${fails.length > 1 ? 's' : ''} ${fails.length > 1 ? 'miss their targets' : 'misses its target'}: ${fails.map((f) => `${f.unit}, ${f.rule} (${f.measured})`).join('; ')}. `
  : 'The layout passes every code and structure check the agents could measure. ') + money;

// ---------- plan ----------
function planSvg() {
  const pts = [...units.flatMap((u) => u.poly), ...(L.corridor || []).flatMap((r) => [[r[0], r[1]], [r[2], r[3]]])];
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]), pad = 1.2;
  const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
  const X = (x) => (x - x0).toFixed(2), Y = (y) => (y1 - y).toFixed(2);
  const rect = (r, fill, extra = '') => { const a = Math.min(r[0], r[2]), b = Math.max(r[0], r[2]), c = Math.min(r[1], r[3]), d = Math.max(r[1], r[3]); return `<rect x="${X(a)}" y="${Y(d)}" width="${(b - a).toFixed(2)}" height="${(d - c).toFixed(2)}" fill="${fill}" ${extra}/>`; };
  const fillFor = { bath: 'var(--tile)', wardrobe: '#d9c4a5', closet: '#d9c4a5' };
  let s = `<svg viewBox="0 0 ${(x1 - x0).toFixed(2)} ${(y1 - y0).toFixed(2)}" role="img" aria-label="Floor plan of the ${n} homes">`;
  s += (L.corridor || []).map((r) => rect(r, 'var(--corr)')).join('');
  s += [...(L.stairs || []), ...(L.lobbies || []), ...(L.stair_links || [])].map((x) => rect(x.rect, 'var(--core)', 'stroke="#b9b6b0" stroke-width="0.06"')).join('');
  for (const u of units) {
    s += `<polygon points="${u.poly.map((p) => `${X(p[0])},${Y(p[1])}`).join(' ')}" fill="var(--oak)"/>`;
    s += u.rooms.filter((r) => fillFor[r.type]).map((r) => rect(r.rect, fillFor[r.type])).join('');
  }
  s += `<g stroke="#2b3138" stroke-linecap="square">${(L.walls || []).map((w) => `<line x1="${X(w.a[0])}" y1="${Y(w.a[1])}" x2="${X(w.b[0])}" y2="${Y(w.b[1])}" stroke-width="${w.kind === 'interior' ? 0.1 : 0.17}"/>`).join('')}</g>`;
  s += (L.columns || []).map((c) => `<rect x="${(c.x - x0 - c.size / 2).toFixed(2)}" y="${(y1 - c.y - c.size / 2).toFixed(2)}" width="${c.size}" height="${c.size}" fill="${c.kind === 'probable' ? '#17212b' : 'none'}" stroke="#17212b" stroke-width="0.07" ${c.kind === 'hidden' ? 'stroke-dasharray="0.15 0.1"' : ''}><title>${esc(c.id)} · ${esc(c.kind)} column${c.where ? ` · ${esc(c.where)}` : ''}</title></rect>`).join('');
  for (const u of units) {
    const ux = u.poly.map((p) => p[0]), uy = u.poly.map((p) => p[1]), cx = (Math.min(...ux) + Math.max(...ux)) / 2, cy = (Math.min(...uy) + Math.max(...uy)) / 2;
    s += `<g font-family="Archivo, sans-serif" text-anchor="middle"><text x="${X(cx)}" y="${Y(cy)}" font-size="0.95" font-weight="700" fill="#17212b">${esc(u.id)}</text><text x="${X(cx)}" y="${(y1 - cy + 1.05).toFixed(2)}" font-size="0.7" fill="#5d6975">${n0(u.sf)} sf</text></g>`;
  }
  return s + '</svg>';
}

// ---------- money bars ----------
function bars(rows, scale) {
  return `<div class="bars">${rows.map(([k, v, cls = '']) => `<div class="bar ${cls.includes('total') ? 'total' : ''}"><span class="k">${esc(k)}</span><span class="track"><span class="fill ${cls.includes('neg') ? 'neg' : ''}" style="left:0;width:${Math.max(0.5, Math.abs(v) / scale * 100)}%"></span></span><span class="v">${usdM(v)}</span></div>`).join('')}</div>`;
}
const opex = M.gpr - M.noi;
const cols = L.columns || [], kinds = cols.reduce((a, c) => ({ ...a, [c.kind]: (a[c.kind] || 0) + 1 }), {});
const fit = M.fitout_sensitivity;
const open = [
  ...Object.entries(items).filter(([, it]) => it.points < it.max - 1e-6).map(([k, it]) => `${k}: ${it.measured} (${(+it.points.toFixed(2))} of ${it.max} points).`),
  `${kinds.possible || 0} possible and ${kinds.hidden || 0} hidden columns are inferred from the scan, not confirmed: check them against the landlord's structural drawings.`,
  'Beams, slab thickness and floor-to-floor height are not in the scan; confirm them before any plumbing or ceiling drop is designed.',
  'Rents come from nearby CoStar apartment comps; the build cost is a rule-of-thumb rate, not a contractor estimate.',
  fit ? `Fit-out sensitivity: ${fit.assumption}. ${fit.note}.` : null,
  L.storage?.note ? `Lockers (${n0(L.storage.lockers_sf)} sf) and co-working (${n0(L.storage.cowork_sf)} sf) fill the deep core zone; ${L.storage.note}.` : null,
].filter(Boolean);

const mix = Object.entries(L.summary.unit_mix || {}).map(([k, v]) => `${v} × ${k}`).join(' · ');
$('main').innerHTML = `
<section class="hero">
  <p class="eyebrow">Conversion review · submitted by the agents</p>
  <h1>${esc(F.title || `Floor ${L.floor}`)}, as ${n} homes</h1>
  <p class="sub">${esc([F.building, F.address, F.floor && `floor ${F.floor} of ${F.stories}`, F.built && `built ${F.built}`].filter(Boolean).join(' · '))}</p>
  <p class="verdict ${ownerOk && M.vs_office >= 0 ? 'good' : ''}">${esc(verdict)}</p>
</section>
<dl class="kpis" id="summary">
  <div class="kpi"><dt>Homes</dt><dd>${n}</dd><div class="note">${esc(mix)}</div></div>
  <div class="kpi"><dt>Rentable area</dt><dd>${n0(L.summary.rentable_sf)}</dd><div class="note">sq ft · ${pct(A.efficiency, 0)} of the floor</div></div>
  <div class="kpi"><dt>Average rent</dt><dd>${usd(M.avg_rent)}</dd><div class="note">a month · CoStar comps</div></div>
  <div class="kpi"><dt>Net operating income</dt><dd>${usdM(M.noi)}</dd><div class="note">a year</div></div>
  <div class="kpi"><dt>Owner yield on cost</dt><dd>${pct(M.yoc_owner, 2)}</dd><div class="note">buyer ${pct(M.yoc_buyer, 2)}</div></div>
  <div class="kpi"><dt>Agents' score</dt><dd>${L.self_score?.total ?? '–'}</dd><div class="note">of 100 · ${(L.self_score?.hard_breaks || []).length} hard failures</div></div>
</dl>

<section class="card plan" id="plan">
  <h2>Plan <span class="tag">${n} homes · ${(L.walls || []).length} wall runs · ${(L.doors || []).length} doors</span></h2>
  <p class="lede">Drawn by the layout agent in the scan's own metres. Bedrooms and living rooms sit on the glass; kitchens and baths back onto the corridor, near the risers.</p>
  ${planSvg()}
  <div class="legend"><span><i style="background:var(--oak)"></i>Oak floor</span><span><i style="background:var(--tile)"></i>Tiled bath</span><span><i style="background:#d9c4a5"></i>Wardrobe / closet</span><span><i style="background:var(--corr)"></i>Corridor</span><span><i style="background:var(--core)"></i>Stairs and lobbies</span><span><i style="background:#17212b"></i>Probable column</span><span><i style="background:#fff;border:1.5px solid #17212b"></i>Possible / hidden column</span></div>
</section>

<section class="card" id="compliance">
  <h2>Compliance <span class="tag">${(+sum(groups.compliance, 'points').toFixed(1))} of ${sum(groups.compliance, 'max')} points · ${checks.length - fails.length} of ${checks.length} unit checks pass</span></h2>
  <p class="lede">Los Angeles Adaptive Reuse Ordinance 188,793 (effective 1 Feb 2026): a 1969 building converts by right through LADBS. Fire stairs ${E.stair_separation_m} m apart; worst walk to a stair door ${E.worst_travel_to_stair_m} m; corridor loop ${E.corridor_loop ? 'yes' : 'no'}.</p>
  ${scoreTable(groups.compliance)}
  <h3 style="font-size:14px;margin:18px 0 8px">Every home</h3>
  <div class="units-table"><table><thead><tr><th>Home</th><th>Type</th><th class="num">Size</th><th class="num">Rent / mo</th><th class="num">To a stair</th><th>Access</th><th>Unit checks</th></tr></thead><tbody>
  ${units.map((u) => { const cs = Object.values(u.checks || {}), ok = cs.filter((c) => c.ok).length; return `<tr><td><b>${esc(u.id)}</b></td><td>${esc(u.type)}</td><td class="num">${n0(u.sf)} sf</td><td class="num">${usd(u.rent_mo || 0)}</td><td class="num">${u.egress_to_stair_m ?? '–'} m</td><td>${u.access ? pill('ok', u.access) : '<span class="muted">standard</span>'}</td><td>${ok === cs.length ? pill('ok', `${ok}/${cs.length} pass`) : pill('bad', `${cs.length - ok} fail`)}</td></tr>`; }).join('')}
  </tbody></table></div>
  ${fails.length ? `<p class="small" style="margin-top:10px"><b>Failing:</b> ${fails.map((f) => esc(`${f.unit} ${f.rule} (${f.measured})`)).join('; ')}</p>` : ''}
</section>

<div class="grid2">
  <section class="card" id="cost">
    <h2>Cost-benefit <span class="tag">${n} homes · ${usd(M.avg_rent)} average rent</span></h2>
    <p class="lede">What the floor earns as homes, what the conversion costs, and how that compares with keeping it as office.</p>
    <h3 style="font-size:13px;color:var(--muted);margin:4px 0 8px">Income, a year</h3>
    ${bars([['Gross rent', M.gpr], ['Operating cost', -opex, 'neg'], ['Net operating income', M.noi, 'total']], M.gpr)}
    <h3 style="font-size:13px;color:var(--muted);margin:18px 0 8px">Cost</h3>
    ${bars([['Build-out', M.build], ['Linkage fee', M.linkage], ['Owner cost', M.owner_cost, 'total'], ['Buying the floor', M.acq, 'neg'], ['Buyer cost', M.buyer_cost, 'total']], M.buyer_cost)}
    <div class="rows" style="margin-top:16px">
      <div><span>Owner yield on cost</span><span>${pct(M.yoc_owner, 2)}</span></div>
      <div><span>Buyer yield on cost</span><span>${pct(M.yoc_buyer, 2)}${buyerTarget ? ` <span class="muted">(needs ${pct(buyerTarget, 2)})</span>` : ''}</span></div>
      <div><span>NOI vs staying office</span><span class="${M.vs_office < 0 ? 'warn' : 'ok'}">${usd(M.vs_office)} a year</span></div>
      <div><span>Break-even build cost</span><span>${usd(M.breakeven_cost_per_rentable_sf)} / rentable sf</span></div>
      <div><span>Value at completion</span><span>${usdM(M.value)}</span></div>
      <div><span>Buyer profit at completion</span><span class="${M.profit_buyer < 0 ? 'warn' : 'ok'}">${usdM(M.profit_buyer)}</span></div>
      ${M.storage_noi ? `<div><span>Storage income (lockers)</span><span>${usd(M.storage_noi)} a year</span></div>` : ''}
    </div>
    <div style="margin-top:16px">${scoreTable(groups.cost)}</div>
  </section>
  <section class="card" id="structure">
    <h2>Structure <span class="tag">${cols.length} columns · ${cols.filter((c) => c.hard).length} conflicts</span></h2>
    <p class="lede">Columns found in the scan were kept out of baths and halls; plumbing chases sit at least 0.6 m from any column.</p>
    ${scoreTable(groups.structure)}
    <h3 style="font-size:14px;margin:18px 0 8px">Columns</h3>
    <div class="units-table"><table><thead><tr><th>Column</th><th>Kind</th><th class="num">Size</th><th>Where it lands</th><th></th></tr></thead><tbody>
    ${cols.map((c) => `<tr><td><b>${esc(c.id)}</b></td><td>${esc(c.kind)}</td><td class="num">${c.size} m</td><td>${esc(c.where || '–')}</td><td>${c.hard ? pill('bad', 'Conflict') : c.ok ? pill('ok', 'OK') : pill('flag', 'Check')}</td></tr>`).join('')}
    </tbody></table></div>
  </section>
</div>

<section class="card" id="open">
  <h2>Assumptions and open questions</h2>
  <p class="lede">What the architect should check first.</p>
  <ul class="list">${open.map((o) => `<li>${esc(o)}</li>`).join('')}</ul>
  <p class="small muted" style="margin-top:14px">Source: ${esc(L.source)}. Scan ${esc(SCAN)} (Matterport). Building facts: CoStar.</p>
</section>`;

if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();

$('dl').addEventListener('click', () => {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(L, null, 2)], { type: 'application/json' }));
  a.download = `layout-${SCAN}-floor${L.floor}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});
$('send').addEventListener('click', () => window.print());   // the architect's packet: this page as a PDF, plus the layout file above
