// Data access. The index and detail files are static; site models and scans are built on demand by the server.

import { API_BASE } from './config.js';

const indexCache = new Map();
const SITE_ROOT = new URL('../', import.meta.url);   // web/, wherever the site is mounted (GitHub Pages: /mundus/)

// A static file of the site: site('data/index/houston.json')
export const site = (path) => new URL(path, SITE_ROOT).href;
// A data file (licensed CoStar index, conversion screen): from the API's server when the site is hosted elsewhere,
// because it is never committed and a static host such as GitHub Pages cannot have it
export const data = (path) => (API_BASE ? `${API_BASE.replace(/\/$/, '')}/${path}` : site(path));
// An API route or a file the API built: api('/api/twin?...'), api('/cache/twin/...')
export const api = (path) => (path.startsWith('/') ? API_BASE.replace(/\/$/, '') + path : path);

// The server answers with paths on its own origin ("/cache/twin/..."); make them absolute when it is elsewhere.
function onApi(value) {
  if (typeof value === 'string') return value.startsWith('/cache/') ? api(value) : value;
  if (Array.isArray(value)) return value.map(onApi);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, onApi(v)]));
  return value;
}

async function getJson(url) {
  const response = await fetch(url);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

export function fetchIndex(city) {
  if (!indexCache.has(city)) indexCache.set(city, getJson(data(`data/index/${city}.json`)));
  return indexCache.get(city);
}

export const fetchDetail = (kind, id) => getJson(data(`data/${kind === 'home' ? 'home' : 'property'}/${id}.json`));
export const fetchTwin = (kind, id) => getJson(api(`/api/twin?kind=${kind}&id=${id}`)).then(onApi);
export const fetchScan = (scanId) => getJson(api(`/api/scan?id=${encodeURIComponent(scanId)}`)).then(onApi);
export const fetchStatus = () => getJson(api('/api/status'));
// office-to-housing screen for one building (pipeline/conversion.py); null when it has not been screened
export const fetchConversion = (id) => getJson(data(`data/conversion/property/${id}.json`)).catch(() => null);
export const obliqueUrl = (kind, id, direction) => api(`/api/oblique?kind=${kind}&id=${id}&direction=${direction}`);
