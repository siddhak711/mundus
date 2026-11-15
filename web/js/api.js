// Data access. The index and detail files are static; site models and scans are built on demand by the server.

const indexCache = new Map();

async function getJson(url) {
  const response = await fetch(url);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

export function fetchIndex(city) {
  if (!indexCache.has(city)) indexCache.set(city, getJson(`/data/index/${city}.json`));
  return indexCache.get(city);
}

export const fetchDetail = (kind, id) => getJson(`/data/${kind === 'home' ? 'home' : 'property'}/${id}.json`);
export const fetchTwin = (kind, id) => getJson(`/api/twin?kind=${kind}&id=${id}`);
export const fetchScan = (scanId) => getJson(`/api/scan?id=${encodeURIComponent(scanId)}`);
export const fetchStatus = () => getJson('/api/status');
// office-to-housing screen for one building (pipeline/conversion.py); null when it has not been screened
export const fetchConversion = (id) => getJson(`/data/conversion/property/${id}.json`).catch(() => null);
export const obliqueUrl = (kind, id, direction) => `/api/oblique?kind=${kind}&id=${id}&direction=${direction}`;
