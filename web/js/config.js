// Where the API lives (server.py: /api/*, /data/, /cache/ and the baked walkthrough floors). Empty means this same
// origin: server.py serving the whole site locally, or Vercel, which proxies those paths to the VM (vercel.json).
// GitHub Pages is static, so there the browser calls the VM's server.py directly.
const VM = 'https://34-132-39-199.sslip.io/atlas';
export const API_BASE = location.hostname.endsWith('github.io') ? VM : '';
