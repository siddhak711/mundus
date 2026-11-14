// Number and text formatting shared by every view.

export const number = (n) => (n == null ? '' : Math.round(n).toLocaleString('en-US'));

export const squareFeet = (n) => (n ? `${number(n)} sq ft` : '');

export function compact(n) {
  if (n == null) return '';
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 1 : 2)}M`;
  if (n >= 1e4) return `${Math.round(n / 1e3)}K`;
  return number(n);
}

export const money = (n) => (n == null ? '' : `$${number(n)}`);
export const moneyCompact = (n) => (n == null ? '' : `$${compact(n)}`);
export const rate = (n) => (n ? `$${n.toFixed(2)}` : 'Not quoted');

export function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export const plural = (n, word) => `${number(n)} ${word}${n === 1 ? '' : 's'}`;

export const CITY_NAMES = { houston: 'Houston', 'los-angeles': 'Los Angeles' };
