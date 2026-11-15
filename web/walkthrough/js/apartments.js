// Realistic apartments for the walkthrough: finished floors, plaster walls, kitchens, baths and furniture, built from a
// "rooms-v1" layout file (layouts/<scan>.json, made by scripts/layout_v4_to_viewer.py). Scan (x, y) lands on world (x, -y).
//
// Everything is boxes and flat quads with UVs in metres, merged per material so the whole floor is a dozen draw calls.
// Textures are CC0 from Poly Haven (vendor/materials/LICENSE.md).
import * as THREE from 'three';

const MAT_DIR = new URL('../vendor/materials/', import.meta.url).href;
const SETS = {   // folder, real-world size of one texture tile in metres
  oak: ['laminate_floor_02', 1.7], tile: ['floor_tiles_06', 1.5], marble: ['marble_01', 1.5],
  plaster: ['white_plaster_02', 1.0], veneer: ['white_oak_veneer', 0.6],
};

async function loadSet(renderer, name) {
  const [dir, size] = SETS[name];
  const loader = new THREE.TextureLoader();
  const aniso = renderer.capabilities.getMaxAnisotropy();
  const [map, normalMap, roughnessMap] = await Promise.all(['diff', 'nor_gl', 'rough'].map((k) => loader.loadAsync(`${MAT_DIR}${dir}/${k}.jpg`)));
  for (const t of [map, normalMap, roughnessMap]) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(1 / size, 1 / size); t.anisotropy = aniso; }
  map.colorSpace = THREE.SRGBColorSpace;
  return { map, normalMap, roughnessMap };
}

// a box whose UVs run in metres on every face, so textures keep their real scale whatever the box size
function boxM(w, h, d) {
  const g = new THREE.BoxGeometry(w, h, d);
  const uv = g.attributes.uv, dims = [[d, h], [d, h], [w, d], [w, d], [w, h], [w, h]];
  for (let f = 0; f < 6; f++) for (let k = 0; k < 4; k++) { const i = f * 4 + k; uv.setXY(i, uv.getX(i) * dims[f][0], uv.getY(i) * dims[f][1]); }
  return g;
}
// a flat rectangle on the floor, scan rect [x0, y0, x1, y1], UVs in metres from the scan origin (so tiles line up across rooms)
function floorRect([ax, ay, bx, by], y) {
  const x0 = Math.min(ax, bx), x1 = Math.max(ax, bx), y0 = Math.min(ay, by), y1 = Math.max(ay, by);
  const p = [x0, y, -y0, x1, y, -y0, x1, y, -y1, x0, y, -y1], uv = [x0, y0, x1, y0, x1, y1, x0, y1];
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3)); g.setAttribute('normal', new THREE.Float32BufferAttribute([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0], 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2)); g.setIndex([0, 1, 2, 0, 2, 3]);   // counter-clockwise from above, so it faces up
  return g;
}
function floorPoly(poly, y) {
  const g = new THREE.ShapeGeometry(new THREE.Shape(poly.map(([x, yy]) => new THREE.Vector2(x, yy))));
  const pos = g.attributes.position, uv = g.attributes.uv;
  for (let i = 0; i < pos.count; i++) { const x = pos.getX(i), yy = pos.getY(i); uv.setXY(i, x, yy); pos.setXYZ(i, x, y, -yy); }
  g.computeVertexNormals(); const n = g.attributes.normal; for (let i = 0; i < n.count; i++) n.setXYZ(i, 0, 1, 0);
  return g;
}

// collects geometry per material and merges it into one mesh each
class Batch {
  constructor() { this.parts = new Map(); }
  add(key, geom, matrix) {
    const g = geom.index ? geom.toNonIndexed() : geom; if (matrix) g.applyMatrix4(matrix);
    if (!this.parts.has(key)) this.parts.set(key, []); this.parts.get(key).push(g);
  }
  build(materials, parent, { shadows = true } = {}) {
    for (const [key, list] of this.parts) {
      const n = list.reduce((a, g) => a + g.attributes.position.count, 0);
      const pos = new Float32Array(n * 3), nrm = new Float32Array(n * 3), uv = new Float32Array(n * 2); let o = 0;
      for (const g of list) { pos.set(g.attributes.position.array, o * 3); nrm.set(g.attributes.normal.array, o * 3); uv.set(g.attributes.uv.array, o * 2); o += g.attributes.position.count; }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('normal', new THREE.BufferAttribute(nrm, 3)); g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
      const m = new THREE.Mesh(g, materials[key]); m.castShadow = shadows; m.receiveShadow = true; m.frustumCulled = false; parent.add(m);
    }
  }
}

// a room's own frame: u runs along its "back" edge (the glass, or the wall a fitting stands against), v points into the room
function frame(rect, edge) {
  const x0 = Math.min(rect[0], rect[2]), x1 = Math.max(rect[0], rect[2]), y0 = Math.min(rect[1], rect[3]), y1 = Math.max(rect[1], rect[3]);
  const F = { y0: [[x0, y0], [1, 0], [0, 1], x1 - x0, y1 - y0], y1: [[x1, y1], [-1, 0], [0, -1], x1 - x0, y1 - y0],
    x0: [[x0, y1], [0, -1], [1, 0], y1 - y0, x1 - x0], x1: [[x1, y0], [0, 1], [-1, 0], y1 - y0, x1 - x0] }[edge];
  const [o, u, v, W, D] = F;
  return { W, D, at: (cu, cv) => [o[0] + u[0] * cu + v[0] * cv, o[1] + u[1] * cu + v[1] * cv], yaw: Math.atan2(u[1], u[0]) };
}
const edgesOf = (r) => { const x0 = Math.min(r[0], r[2]), x1 = Math.max(r[0], r[2]), y0 = Math.min(r[1], r[3]), y1 = Math.max(r[1], r[3]); return { x0, x1, y0, y1 }; };
// distance from a point to each edge line of a rect, inside the edge's span
function nearestEdge(rect, [px, py]) {
  const e = edgesOf(rect); const d = { x0: Math.abs(px - e.x0), x1: Math.abs(px - e.x1), y0: Math.abs(py - e.y0), y1: Math.abs(py - e.y1) };
  return Object.entries(d).sort((a, b) => a[1] - b[1])[0][0];
}
const OPP = { x0: 'x1', x1: 'x0', y0: 'y1', y1: 'y0' };

export async function buildApartments({ LAY, SH, renderer, z0, z1 }) {
  const [oak, tile, marble, plaster, veneer] = await Promise.all(['oak', 'tile', 'marble', 'plaster', 'veneer'].map((n) => loadSet(renderer, n)));
  const std = (o) => new THREE.MeshStandardMaterial(o);
  const M = {
    oak: std({ ...oak, roughness: 0.75, color: 0xf2e6d6 }),
    tile: std({ ...tile, roughness: 0.6, color: 0xffffff, normalScale: new THREE.Vector2(0.6, 0.6) }),
    corridor: std({ color: 0x8e8a84, roughness: 0.95 }),
    core: std({ color: 0xd9d6d0, roughness: 0.9 }),
    wall: std({ normalMap: plaster.normalMap, color: 0xf8f7f3, roughness: 0.92, normalScale: new THREE.Vector2(0.12, 0.12) }),   // smooth painted drywall: only a hint of the plaster's relief
    base: std({ color: 0xf6f5f2, roughness: 0.45 }),
    cabinet: std({ ...veneer, roughness: 0.6, color: 0xffffff }),
    paint: std({ color: 0xe9e6df, roughness: 0.5 }),            // painted cabinet fronts and doors
    counter: std({ ...marble, roughness: 0.25, color: 0xffffff }),
    steel: std({ color: 0xc7cacd, roughness: 0.3, metalness: 0.6 }),
    porcelain: std({ color: 0xfbfbfa, roughness: 0.15 }),
    linen: std({ color: 0xece7de, roughness: 0.95 }),
    duvet: std({ color: 0xb7b0a5, roughness: 0.95 }),
    sofa: std({ color: 0x8c8f8a, roughness: 0.95 }),
    rug: std({ color: 0xd8cfc0, roughness: 1 }),
    dark: std({ color: 0x3b3a38, roughness: 0.6 }),
    glass: std({ color: 0xd4e4ec, roughness: 0.05, transparent: true, opacity: 0.35 }),
  };
  M.wall.polygonOffset = true; M.wall.polygonOffsetFactor = 1;
  const floorMats = [M.oak, M.tile, M.corridor, M.core];
  floorMats.forEach((m) => { m.polygonOffset = true; m.polygonOffsetFactor = -1; m.polygonOffsetUnits = -1; });

  const H = z1 - z0;
  const floors = new Batch(), rise = new Batch(), obstacles = [];
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
  // place a box: centre (x, y) in scan metres, bottom at height y0 above the floor, yaw from a room frame
  const put = (key, [cx, cy], y0, [w, h, d], yaw = 0, block = true) => {
    q.setFromAxisAngle(up, yaw); m4.compose(new THREE.Vector3(cx, y0 + h / 2, -cy), q, new THREE.Vector3(1, 1, 1));
    rise.add(key, boxM(w, h, d), m4);
    if (block && h > 0.3) obstacles.push({ cx, cy, hw: w / 2, hd: d / 2, yaw });
  };
  const putF = (f, key, cu, cv, y0, w, h, d, block) => put(key, f.at(cu, cv), y0, [w, h, d], f.yaw, block);

  // ---- floors ----
  for (const r of LAY.corridor || []) floors.add('corridor', floorRect(r, 0.004));
  for (const s of [...(LAY.stairs || []), ...(LAY.lobbies || []), ...(LAY.stair_links || [])]) floors.add('core', floorRect(s.rect, 0.004));
  for (const u of LAY.units) {
    floors.add('oak', floorPoly(u.poly, 0.004));
    for (const r of u.rooms) if (r.type === 'bath') floors.add('tile', floorRect(r.rect, 0.008));
  }

  // ---- walls, with a baseboard on each face ----
  const T = { demising: 0.16, corridor: 0.16, interior: 0.11 };
  for (const w of LAY.walls) {
    const ax = w.a[0], ay = w.a[1], bx = w.b[0], by = w.b[1], L = Math.hypot(bx - ax, by - ay), t = T[w.kind] || 0.12;
    const yaw = Math.atan2(by - ay, bx - ax), c = [(ax + bx) / 2, (ay + by) / 2];
    put('wall', c, 0, [L + t, H, t], yaw, false);
    put('base', c, 0, [L + t, 0.09, t + 0.024], yaw, false);
    obstacles.push({ cx: c[0], cy: c[1], hw: L / 2 + t / 2, hd: t / 2, yaw });
  }
  // door leaves standing open against the wall, so openings read as doors
  for (const d of LAY.doors || []) {
    const L = Math.hypot(d.b[0] - d.a[0], d.b[1] - d.a[1]); if (L < 0.5) continue;
    const yaw = Math.atan2(d.b[1] - d.a[1], d.b[0] - d.a[0]), nx = -Math.sin(yaw), ny = Math.cos(yaw), leaf = Math.min(0.86, L - 0.04);
    const hx = d.a[0] + nx * leaf / 2, hy = d.a[1] + ny * leaf / 2;   // hinged at a, swung 90 degrees into the room
    put('paint', [hx, hy], 0, [leaf, 2.05, 0.04], yaw + Math.PI / 2, false);
    put('base', [(d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2], 2.05, [L, 0.06, 0.18], yaw, false);   // head trim
  }

  const [gx0, gx1, gy0, gy1] = SH.rect;
  const glassEdge = (rect) => { const e = edgesOf(rect); const d = { x0: e.x0 - gx0, x1: gx1 - e.x1, y0: e.y0 - gy0, y1: gy1 - e.y1 }; const best = Object.entries(d).sort((a, b) => a[1] - b[1])[0]; return best[1] < 0.6 ? best[0] : null; };
  const doorEdge = (rect, unitId, type) => {
    const d = (LAY.doors || []).find((x) => x.unit === unitId && x.room === type && (() => { const e = edgesOf(rect), m = [(x.a[0] + x.b[0]) / 2, (x.a[1] + x.b[1]) / 2]; return m[0] > e.x0 - 0.2 && m[0] < e.x1 + 0.2 && m[1] > e.y0 - 0.2 && m[1] < e.y1 + 0.2; })());
    return d ? nearestEdge(rect, [(d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2]) : null;
  };

  for (const u of LAY.units) {
    const fixtures = u.fixtures || [];
    for (const r of u.rooms) {
      const rect = r.rect;
      if (r.type === 'bed') {
        const g = glassEdge(rect) || 'y0', f = frame(rect, g);
        const bw = f.W >= 3.0 ? 1.6 : 1.4, bl = 2.05, cu = f.W / 2, cv = Math.max(bl / 2 + 0.6, f.D - bl / 2 - 0.02);   // headboard on the wall opposite the glass
        putF(f, 'cabinet', cu, cv, 0, bw + 0.08, 0.32, bl + 0.06);
        putF(f, 'linen', cu, cv, 0.32, bw, 0.2, bl - 0.02, false);
        putF(f, 'duvet', cu, cv - 0.25, 0.52, bw + 0.04, 0.05, bl - 0.5, false);
        for (const s of [-1, 1]) putF(f, 'linen', cu + s * bw / 4, f.D - 0.32, 0.52, bw / 2 - 0.08, 0.12, 0.38, false);
        putF(f, 'cabinet', cu, f.D - 0.05, 0, bw + 0.2, 1.05, 0.08, false);   // headboard
        if (f.W - bw > 1.1) for (const s of [-1, 1]) putF(f, 'cabinet', cu + s * (bw / 2 + 0.3), f.D - 0.25, 0, 0.45, 0.55, 0.4);
      } else if (r.type === 'wardrobe' || r.type === 'closet') {
        const e = edgesOf(rect), w = e.x1 - e.x0, d = e.y1 - e.y0;
        if (r.type === 'wardrobe') put('cabinet', [(e.x0 + e.x1) / 2, (e.y0 + e.y1) / 2], 0, [w - 0.04, 2.25, d - 0.04], 0);
        else { const f = frame(rect, w > d ? 'y0' : 'x0'); putF(f, 'paint', f.W / 2, 0.22, 1.55, f.W - 0.05, 0.03, 0.4, false); }   // a shelf
      } else if (r.type === 'living') {
        const g = glassEdge(rect) || 'y0', f = frame(rect, g);
        const sw = Math.min(2.3, f.W - 0.6), sv = Math.min(f.D - 0.55, 3.1);   // sofa faces the glass
        putF(f, 'rug', f.W / 2, sv - 1.05, 0, Math.min(2.6, f.W - 0.4), 0.012, 1.9, false);
        putF(f, 'sofa', f.W / 2, sv, 0, sw, 0.42, 0.95);
        putF(f, 'sofa', f.W / 2, sv + 0.36, 0.42, sw, 0.4, 0.22, false);
        for (const s of [-1, 1]) putF(f, 'sofa', f.W / 2 + s * (sw / 2 - 0.1), sv, 0.42, 0.2, 0.2, 0.95, false);
        putF(f, 'cabinet', f.W / 2, sv - 1.05, 0, 1.1, 0.4, 0.6);   // coffee table
        putF(f, 'dark', f.W / 2, 0.55, 0, Math.min(1.8, f.W - 0.8), 0.5, 0.42);   // low media unit by the window
        putF(f, 'dark', f.W / 2, 0.6, 0.5, Math.min(1.4, f.W - 1), 0.75, 0.04, false);   // screen
      } else if (r.type === 'kitchen') {
        const sink = fixtures.find((x) => x.kind === 'sink');
        const g = sink ? nearestEdge(rect, sink.pos) : (glassEdge(rect) ? OPP[glassEdge(rect)] : 'y1'), f = frame(rect, g);
        const run = Math.min(f.W - 0.1, 4.2);
        let s0 = sink ? (() => { const e = edgesOf(rect); const along = { y0: sink.pos[0] - e.x0, y1: e.x1 - sink.pos[0], x0: e.y1 - sink.pos[1], x1: sink.pos[1] - e.y0 }[g]; return along - run / 2; })() : 0.05;
        s0 = Math.min(Math.max(s0, 0.05), f.W - run - 0.05);
        const cu = s0 + run / 2;
        putF(f, 'paint', cu, 0.31, 0.1, run, 0.78, 0.6);              // base cabinets
        putF(f, 'dark', cu, 0.27, 0, run, 0.1, 0.52, false);          // toe kick
        putF(f, 'counter', cu, 0.32, 0.88, run + 0.02, 0.04, 0.64, false);
        putF(f, 'paint', cu, 0.18, 1.45, run, 0.75, 0.35, false);     // upper cabinets
        putF(f, 'counter', cu, 0.01, 0.92, run, 0.53, 0.02, false);   // backsplash
        const sk = sink ? Math.min(Math.max(s0 + run / 2, s0 + 0.5), s0 + run - 0.5) : cu;
        putF(f, 'steel', sk, 0.33, 0.915, 0.62, 0.012, 0.42, false);  // sink
        putF(f, 'steel', s0 + run - 0.45, 0.32, 0.92, 0.6, 0.01, 0.52, false);   // hob
        if (f.W - run > 0.8) putF(f, 'steel', s0 > 0.8 ? s0 - 0.42 : s0 + run + 0.42, 0.36, 0, 0.78, 2.05, 0.7);   // fridge at the end of the run
        if (f.D > 2.9) {   // dining table and chairs in the open part of the kitchen
          const tv = Math.min(f.D - 0.9, 0.62 + 1.25 + 0.45), tu = f.W / 2;
          putF(f, 'cabinet', tu, tv, 0.72, 1.4, 0.04, 0.85, false); putF(f, 'dark', tu, tv, 0, 1.2, 0.72, 0.06);
          for (const [du, dv] of [[-0.4, -0.65], [0.4, -0.65], [-0.4, 0.65], [0.4, 0.65]]) { putF(f, 'dark', tu + du, tv + dv, 0.44, 0.44, 0.04, 0.44, false); putF(f, 'dark', tu + du, tv + dv, 0, 0.36, 0.44, 0.36, false); }
        }
      } else if (r.type === 'bath') {
        const de = doorEdge(rect, u.id, 'bath') || (glassEdge(rect) ? glassEdge(rect) : 'y1'), f = frame(rect, OPP[de]);   // back wall faces the door
        const tubL = Math.min(1.7, f.W - 0.05);
        if (f.D >= 2.0 && tubL >= 1.4) {
          putF(f, 'porcelain', f.W / 2, 0.38, 0, tubL, 0.55, 0.75);
          putF(f, 'glass', f.W / 2 + tubL / 4, 0.76, 0.55, tubL / 2, 1.4, 0.015, false);
        } else {   // shower in the back corner
          putF(f, 'tile', 0.48, 0.48, 0, 0.92, 0.05, 0.92, false);
          putF(f, 'glass', 0.48, 0.95, 0.05, 0.92, 1.95, 0.015, false);
          putF(f, 'glass', 0.95, 0.48, 0.05, 0.015, 1.95, 0.92, false);
        }
        const sideV = f.D >= 2.0 ? 0.75 + Math.max(0.3, (f.D - 0.75) / 2) : f.D / 2 + 0.2;
        // toilet against one side wall, vanity against the other
        putF(f, 'porcelain', 0.33, sideV, 0, 0.66, 0.4, 0.38);
        putF(f, 'porcelain', 0.1, sideV, 0.4, 0.18, 0.4, 0.4, false);
        putF(f, 'paint', f.W - 0.26, sideV, 0, 0.5, 0.82, 0.8);
        putF(f, 'counter', f.W - 0.26, sideV, 0.82, 0.52, 0.03, 0.84, false);
        putF(f, 'glass', f.W - 0.02, sideV, 1.05, 0.02, 0.8, 0.7, false);   // mirror
      }
    }
    for (const fx of fixtures) if (fx.kind === 'washer') {
      const room = u.rooms.find((r) => { const e = edgesOf(r.rect); return fx.pos[0] >= e.x0 && fx.pos[0] <= e.x1 && fx.pos[1] >= e.y0 && fx.pos[1] <= e.y1; });
      if (!room || room.type === 'kitchen') continue;   // in the kitchen run the cabinets already cover it
      const f = frame(room.rect, nearestEdge(room.rect, fx.pos)); const e = edgesOf(room.rect);
      const along = { y0: fx.pos[0] - e.x0, y1: e.x1 - fx.pos[0], x0: e.y1 - fx.pos[1], x1: fx.pos[1] - e.y0 }[nearestEdge(room.rect, fx.pos)];
      putF(f, 'porcelain', Math.min(Math.max(along, 0.32), f.W - 0.32), 0.33, 0, 0.6, 0.85, 0.6);
    }
  }

  const floorGroup = new THREE.Group(), riseGroup = new THREE.Group();
  floors.build(M, floorGroup, { shadows: false });
  rise.build(M, riseGroup);
  riseGroup.children.forEach((m) => { if (m.material === M.glass) { m.castShadow = false; m.renderOrder = 3; } });

  // labels in plan view: unit type and size on a light chip
  const labels = new THREE.Group();
  const chip = (a, b) => {
    const cv = document.createElement('canvas'); cv.width = 512; cv.height = 150; const c = cv.getContext('2d');
    c.fillStyle = 'rgba(255,255,255,.92)'; c.strokeStyle = 'rgba(23,33,43,.18)'; c.lineWidth = 3; c.beginPath(); c.roundRect(4, 4, 504, 142, 30); c.fill(); c.stroke();
    c.textAlign = 'center'; c.fillStyle = '#17212b'; c.font = '600 52px Archivo, -apple-system, sans-serif'; c.fillText(a, 256, 66);
    c.fillStyle = '#5d6975'; c.font = '40px Archivo, -apple-system, sans-serif'; c.fillText(b, 256, 120);
    const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace;
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthTest: false, transparent: true })); s.scale.set(3.0, 0.88, 1); s.renderOrder = 8; return s;
  };
  for (const u of LAY.units) {
    const xs = u.poly.map((p) => p[0]), ys = u.poly.map((p) => p[1]);
    const s = chip(`${u.id} · ${u.type.replace(' corner', '')}`, `${u.sf.toLocaleString('en-US')} sq ft`);
    s.position.set((Math.min(...xs) + Math.max(...xs)) / 2, H + 0.6, -(Math.min(...ys) + Math.max(...ys)) / 2); labels.add(s);
  }

  // collision for walking among the apartments: walls and furniture as rotated boxes, with a 0.25 m body radius
  const blocked = (x, z) => {
    const y = -z;
    for (const o of obstacles) {
      const dx = x - o.cx, dy = y - o.cy, c = Math.cos(o.yaw), s = Math.sin(o.yaw);
      if (Math.abs(dx * c + dy * s) < o.hw + 0.25 && Math.abs(-dx * s + dy * c) < o.hd + 0.25) return true;
    }
    return false;
  };
  const floorMatsAll = [M.oak, M.tile, M.corridor, M.core];
  const setFloorOpacity = (o) => floorMatsAll.forEach((m) => { const tr = o < 0.999; if (m.transparent !== tr) { m.transparent = tr; m.needsUpdate = true; } m.opacity = o; });
  return { floorGroup, riseGroup, labels, blocked, setFloorOpacity, materials: M };
}
