import { site } from './api.js';
// Turns a property's CoStar records into per-floor facts for a given year.

export const CURRENT_YEAR = 2026;

export function createFloorModel(detail, twin, conversion = null) {
  const stories = twin.building.stories;
  const tenancies = (detail.tenancies || []).filter((t) => t.floor);
  // every active listing when the index has them (allSpaces), else the main listing
  const available = (detail.availability?.allSpaces || detail.availability?.spaces || []).filter((s) => s.floor);
  // the conversion screen's view of each floor, and the floors that have a baked walkthrough
  const screened = new Map((conversion?.floors || []).map((f) => [f.floor, f]));
  const walkthrough = (floor) => {
    const w = screened.get(floor)?.walkthrough;
    return w ? { ...w, href: `${site(w.url.replace(/^\//, ''))}?building=${detail.id}&floor=${floor}${w.scanId ? `&scan=${w.scanId}` : ''}` } : null;
  };
  const scans = twin.scans.filter((s) => s.floor);
  const years = tenancies.map((t) => t.from).filter(Boolean);

  // indexed by floor once: a repaint asks about every floor, and a big tower has hundreds of tenancies
  const byFloor = (rows) => rows.reduce((m, r) => (m.get(r.floor) || m.set(r.floor, []).get(r.floor)).push(r) && m, new Map());
  const tenanciesOn = byFloor(tenancies);
  const availableOn = byFloor(available);
  const scansOn = byFloor(scans);

  function capacity(floor) {
    return detail.floorSf?.[floor] || detail.typicalFloorSf || (detail.sizeSf ? detail.sizeSf / stories : 0);
  }

  // how empty a floor is today: the conversion screen's verdict where the building was screened, otherwise listed space
  // against the floor's size (half or more listed is 'convertible', any is 'partial')
  function vacancyOf(floor) {
    const s = screened.get(floor)?.status;
    if (s) return s;
    const listed = (availableOn.get(floor) || []).reduce((n, sp) => n + (sp.fullFloor ? capacity(floor) : sp.sf || 0), 0);
    const cap = capacity(floor);
    if (listed && cap && listed / cap >= 0.5) return 'convertible';
    return listed ? 'partial' : 'leased';
  }

  function at(floor, year = CURRENT_YEAR) {
    const tenants = (tenanciesOn.get(floor) || []).filter((t) => (t.from ?? 0) <= year && (t.to == null || t.to >= year));
    const leasedSf = tenants.reduce((sum, t) => sum + (t.sf || 0), 0);
    const cap = capacity(floor);
    const isNow = year >= CURRENT_YEAR;
    return {
      floor,
      tenants,
      leasedSf,
      leasedShare: cap ? Math.min(1, leasedSf / cap) : tenants.length ? 1 : 0,
      available: isNow ? availableOn.get(floor) || [] : [],
      scans: isNow ? scansOn.get(floor) || [] : [],
      walkthrough: isNow ? walkthrough(floor) : null,
      conversion: isNow ? screened.get(floor) || null : null,
      vacancy: isNow ? vacancyOf(floor) : null,
    };
  }

  function summary(year = CURRENT_YEAR) {
    const names = new Set();
    let leasedSf = 0;
    for (const t of tenancies) {
      if ((t.from ?? 0) <= year && (t.to == null || t.to >= year)) {
        names.add(t.tenant);
        leasedSf += t.sf || 0;
      }
    }
    return { tenants: names.size, leasedSf };
  }

  return {
    stories,
    at,
    summary,
    hasHistory: tenancies.length > 0,
    walkthroughFloors: [...screened.values()].filter((f) => f.walkthrough).map((f) => f.floor),
    walkthrough,
    firstYear: years.length ? Math.max(1980, Math.min(...years)) : CURRENT_YEAR,
    floorsOf: (tenantName) => [...new Set(tenancies.filter((t) => t.tenant === tenantName && t.to == null).map((t) => t.floor))],
  };
}
