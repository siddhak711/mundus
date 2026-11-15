// The surrounding city: Vexcel's height model as a mesh, textured with the aerial photo.
import * as THREE from 'three';
import { FACADE_GLSL } from './facade.js';

const VERTEX = /* glsl */ `
  attribute float height;
  uniform float uGrow;
  varying vec2 vUv;
  varying vec3 vWorld;
  void main() {
    vec3 p = position;
    p.y = height * uGrow;
    vUv = uv;
    vec4 world = modelMatrix * vec4(p, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }`;

// Roofs and ground show the aerial photo. Building sides have no imagery, so they are drawn as
// plain shaded massing rather than invented facades.
const FRAGMENT = /* glsl */ `
  uniform sampler2D uMap;
  uniform float uHeightMode;
  uniform float uDim;
  uniform float uMaxHeight;
  uniform vec3 uSky;
  varying vec2 vUv;
  varying vec3 vWorld;

  vec3 heightRamp(float t) {
    vec3 low = vec3(0.93, 0.95, 0.96), mid = vec3(0.45, 0.67, 0.78), high = vec3(0.09, 0.20, 0.36);
    return t < 0.5 ? mix(low, mid, t * 2.0) : mix(mid, high, t * 2.0 - 1.0);
  }

  void main() {
    vec3 normal = normalize(cross(dFdx(vWorld), dFdy(vWorld)));
    if (normal.y < 0.0) normal = -normal;
    float side = smoothstep(0.5, 0.8, 1.0 - normal.y) * step(1.5, vWorld.y);
    float light = clamp(dot(normal, normalize(vec3(0.45, 0.6, 0.5))) * 0.5 + 0.62, 0.0, 1.0);

    vec3 photo = texture2D(uMap, vUv).rgb;
    // sides are lit by compass direction only, which keeps tall walls even instead of streaky
    float wallLight = 0.84 + 0.12 * dot(normalize(normal.xz + 1e-4), normalize(vec2(0.45, 0.5)));
    vec3 massing = vec3(0.83, 0.85, 0.87) * wallLight;
    vec3 color = mix(photo, massing, side);

    vec3 ramp = heightRamp(pow(clamp(vWorld.y / uMaxHeight, 0.0, 1.0), 0.6)) * (0.72 + 0.28 * light);
    color = mix(color, ramp, uHeightMode);
    color = mix(color, vec3(0.86, 0.88, 0.90), uDim * 0.72);

    float fog = 1.0 - exp(-length(vWorld - cameraPosition) * 0.00022);
    gl_FragColor = vec4(mix(color, uSky, fog * 0.55), 1.0);
  }`;

export function createTerrain({ extent, grid, heights, orthoUrl, sky, anisotropy }) {
  const geometry = new THREE.PlaneGeometry(extent, extent, grid - 1, grid - 1);
  geometry.rotateX(-Math.PI / 2); // plane rows run north to south, matching the height raster
  geometry.setAttribute('height', new THREE.BufferAttribute(heights, 1));

  let maxHeight = 1;
  for (const h of heights) if (h > maxHeight) maxHeight = h;
  geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, maxHeight / 2, 0), extent);

  // ready resolves once the aerial photo has loaded (or failed), so the viewer can upload it before animating
  let resolveReady;
  const ready = new Promise((resolve) => { resolveReady = resolve; });
  const map = new THREE.TextureLoader().load(orthoUrl, () => resolveReady(), undefined, () => resolveReady());
  map.colorSpace = THREE.SRGBColorSpace;
  map.anisotropy = anisotropy;

  const uniforms = {
    uMap: { value: map },
    uGrow: { value: 0 },
    uHeightMode: { value: 0 },
    uDim: { value: 0 },
    uMaxHeight: { value: maxHeight },
    uSky: { value: new THREE.Color(sky) },
  };
  const mesh = new THREE.Mesh(geometry, new THREE.ShaderMaterial({ uniforms, vertexShader: VERTEX, fragmentShader: FRAGMENT }));
  mesh.frustumCulled = false;

  return {
    mesh,
    uniforms,
    maxHeight,
    ready,
    dispose() {
      geometry.dispose();
      map.dispose();
      mesh.material.dispose();
    },
  };
}

/** Roof outlines of neighbouring buildings, from Vexcel's structure footprints. */
export function createFootprints(neighbours) {
  const points = [];
  for (const { ring, height } of neighbours) {
    const y = height + 0.6;
    for (let i = 0; i < ring.length - 1; i++) {
      points.push(ring[i][0], y, -ring[i][1], ring[i + 1][0], y, -ring[i + 1][1]);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
  const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: 0x17212b, transparent: true, opacity: 0.7 }));
  lines.visible = false;
  return lines;
}

// ---- the diorama: a ground plate with the aerial photo, the neighbours as real-looking buildings, and trees -----

const GROUND_VERTEX = /* glsl */ `
  varying vec3 vWorld;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }`;

const GROUND_FRAGMENT = /* glsl */ `
  uniform sampler2D uMap;
  uniform float uExtent;
  uniform float uDim;
  varying vec3 vWorld;
  ${FACADE_GLSL}
  void main() {
    vec3 color = texture2D(uMap, vec2(vWorld.x / uExtent + 0.5, -vWorld.z / uExtent + 0.5)).rgb;
    color = atmosphere(color, vWorld);
    color = mix(color, vec3(0.86, 0.88, 0.90), uDim * 0.72);
    gl_FragColor = vec4(color, 1.0);
  }`;

const BLOCK_VERTEX = /* glsl */ `
  uniform float uGrow;
  attribute float aSeed;
  attribute float aHeight;
  varying vec3 vWorld;
  varying vec3 vNormal;
  varying float vAlong;
  varying float vUp;
  varying float vSeed;
  varying float vHeight;
  void main() {
    vec3 p = position;
    vUp = p.y;                       // the facade pattern stays put while the block rises
    vAlong = uv.x;                   // metres along the wall (ExtrudeGeometry side-wall UVs)
    vSeed = aSeed;
    vHeight = aHeight;
    p.y *= uGrow;
    vec4 world = modelMatrix * vec4(p, 1.0);
    vWorld = world.xyz;
    vNormal = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * viewMatrix * world;
  }`;

// Roofs are the real aerial photo; walls are drawn as plausible facades for each building's height (facade.js).
const BLOCK_FRAGMENT = /* glsl */ `
  uniform sampler2D uMap;
  uniform float uExtent;
  uniform float uDim;
  varying vec3 vWorld;
  varying vec3 vNormal;
  varying float vAlong;
  varying float vUp;
  varying float vSeed;
  varying float vHeight;
  ${FACADE_GLSL}
  void main() {
    vec3 n = normalize(vNormal);
    vec3 color;
    if (n.y > 0.5) {
      color = texture2D(uMap, vec2(vWorld.x / uExtent + 0.5, -vWorld.z / uExtent + 0.5)).rgb;
      color *= 0.94 + 0.08 * max(dot(n, SUN), 0.0);
    } else {
      color = facade(n, vWorld, vAlong, vUp, vHeight, vSeed, 0.0);
    }
    color = atmosphere(color, vWorld);
    color = mix(color, vec3(0.86, 0.88, 0.90), uDim * 0.72);
    gl_FragColor = vec4(color, 1.0);
  }`;

/** Ground plate with the aerial photo, a solid base under it and a light rim, like a cut-out model of the block. */
export function createPlate({ extent, orthoUrl, anisotropy }) {
  let resolveReady;
  const ready = new Promise((resolve) => { resolveReady = resolve; });
  const map = new THREE.TextureLoader().load(orthoUrl, () => resolveReady(), undefined, () => resolveReady());
  map.colorSpace = THREE.SRGBColorSpace;
  map.anisotropy = anisotropy;
  // uTime drifts the cloud shadows; the viewer advances it each frame (left at 0, the clouds simply stand still)
  const uniforms = { uMap: { value: map }, uExtent: { value: extent }, uDim: { value: 0 }, uGrow: { value: 0 }, uTime: { value: 0 } };

  const group = new THREE.Group();
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(extent, extent).rotateX(-Math.PI / 2),
    new THREE.ShaderMaterial({ uniforms: { uMap: uniforms.uMap, uExtent: uniforms.uExtent, uDim: uniforms.uDim, uTime: uniforms.uTime },
      vertexShader: GROUND_VERTEX, fragmentShader: GROUND_FRAGMENT }));

  const depth = extent * 0.035;
  const base = new THREE.Mesh(new THREE.BoxGeometry(extent, depth, extent), [
    ...Array(2).fill(new THREE.MeshLambertMaterial({ color: 0x3b4654 })),   // +x, -x
    new THREE.MeshLambertMaterial({ color: 0x3b4654 }), new THREE.MeshLambertMaterial({ color: 0x2b333d }),  // top, bottom
    ...Array(2).fill(new THREE.MeshLambertMaterial({ color: 0x46525f })),   // +z, -z
  ]);
  base.position.y = -depth / 2 - 0.05;
  // a low wall all round the plate, like the raised edge of a model tray: slate sides, light tops
  const wallHeight = extent * 0.016;
  const wallThick = extent * 0.012;
  const side = new THREE.MeshLambertMaterial({ color: 0x4a5664 });
  const top = new THREE.MeshLambertMaterial({ color: 0xeef2f5 });
  const wallMaterials = [side, side, top, side, side, side];          // box faces: +x, -x, +y (top), -y, +z, -z
  const h = extent / 2;
  const tall = wallHeight + depth;
  const walls = [
    [extent, wallThick, 0, h - wallThick / 2], [extent, wallThick, 0, -(h - wallThick / 2)],
    [wallThick, extent - 2 * wallThick, h - wallThick / 2, 0], [wallThick, extent - 2 * wallThick, -(h - wallThick / 2), 0],
  ].map(([w, d, x, z]) => {
    const wall = new THREE.Mesh(new THREE.BoxGeometry(w, tall, d), wallMaterials);
    wall.position.set(x, (wallHeight - depth) / 2, z);
    return wall;
  });
  group.add(ground, base, ...walls);

  return {
    group, uniforms, ready, map,
    inset: wallThick,                 // the neighbours are cut to fit inside the wall
    dispose() {
      map.dispose();
      group.traverse((o) => { o.geometry?.dispose(); [].concat(o.material || []).forEach((m) => m.dispose()); });
    },
  };
}

/** Neighbouring buildings as real-looking blocks, cut to the plate. One merged mesh: one draw call. */
export function createBlocks({ neighbours, extent, plate }) {
  const h = extent / 2 - plate.inset - 0.5;
  const clamp = (v) => Math.max(-h, Math.min(h, v));
  const positions = [], normals = [], uvs = [], seeds = [], heights = [];
  for (const { ring, height } of neighbours) {
    if (!ring?.length || !(height > 1)) continue;
    const pts = ring.map(([x, y]) => new THREE.Vector2(clamp(x), clamp(y)));
    const area = Math.abs(THREE.ShapeUtils.area(pts));
    if (area < 4) continue;                                          // slivers left after cutting to the plate
    let g = new THREE.ExtrudeGeometry(new THREE.Shape(pts), { depth: height, bevelEnabled: false });
    g.rotateX(-Math.PI / 2);                                         // shape y (north) -> -z, depth -> up
    if (g.index) g = g.toNonIndexed();
    // a stable seed per building, from where it is and how big it is: the same block always gets the same facade
    const seed = (Math.abs(Math.sin(ring[0][0] * 12.9898 + ring[0][1] * 78.233 + area * 0.0137)) * 43758.5453) % 1;
    const count = g.getAttribute('position').count;
    positions.push(...g.getAttribute('position').array);
    normals.push(...g.getAttribute('normal').array);
    uvs.push(...g.getAttribute('uv').array);
    for (let i = 0; i < count; i++) { seeds.push(seed); heights.push(height); }
    g.dispose();
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setAttribute('aSeed', new THREE.Float32BufferAttribute(seeds, 1));
  geometry.setAttribute('aHeight', new THREE.Float32BufferAttribute(heights, 1));
  const u = plate.uniforms;
  const mesh = new THREE.Mesh(geometry, new THREE.ShaderMaterial({
    uniforms: { uMap: u.uMap, uExtent: u.uExtent, uDim: u.uDim, uGrow: u.uGrow, uTime: u.uTime },
    vertexShader: BLOCK_VERTEX, fragmentShader: BLOCK_FRAGMENT,
  }));
  return { mesh, dispose() { geometry.dispose(); mesh.material.dispose(); } };
}

// ---- trees: real canopy positions and heights from the surface model (pipeline/twin.py, trees.bin) -------------------

const TREE_VERTEX = /* glsl */ `
  uniform float uGrow;
  attribute vec3 aTree;            // x, z of the trunk, and a 0..1 variation
  varying vec3 vWorld;
  varying vec3 vNormal;
  varying vec3 vTree;
  void main() {
    vec4 world = modelMatrix * instanceMatrix * vec4(position, 1.0);
    world.y *= uGrow;                 // the trees rise with the neighbours
    vWorld = world.xyz;
    vNormal = normalize(mat3(modelMatrix) * mat3(instanceMatrix) * normal);
    vTree = aTree;
    gl_Position = projectionMatrix * viewMatrix * world;
  }`;

const TREE_FRAGMENT = /* glsl */ `
  uniform sampler2D uMap;
  uniform float uExtent;
  uniform float uDim;
  uniform float uTrunk;            // 1 for the trunk mesh
  varying vec3 vWorld;
  varying vec3 vNormal;
  varying vec3 vTree;
  ${FACADE_GLSL}
  void main() {
    vec3 n = normalize(vNormal);
    vec3 color;
    if (uTrunk > 0.5) {
      color = vec3(0.33, 0.27, 0.22) * (0.7 + 0.3 * max(dot(n, SUN), 0.0));
    } else {
      // the canopy's own colour, from the aerial photo where the tree stands, kept green and a little richer
      vec3 photo = texture2D(uMap, vec2(vTree.x / uExtent + 0.5, vTree.y / uExtent + 0.5)).rgb;
      vec3 leaf = mix(vec3(0.24, 0.34, 0.18), photo, 0.6);
      leaf = mix(vec3(dot(leaf, vec3(0.333))), leaf, 1.25);
      leaf *= 0.85 + 0.3 * vTree.z;
      float light = 0.55 + 0.45 * max(dot(n, SUN), 0.0);
      light *= 0.75 + 0.25 * smoothstep(-0.6, 0.6, n.y);           // darker underneath
      color = leaf * light;
    }
    color = atmosphere(color, vWorld);
    color = mix(color, vec3(0.86, 0.88, 0.90), uDim * 0.72);
    gl_FragColor = vec4(color, 1.0);
  }`;

/** Trees as instanced crowns and trunks. url: trees.bin, Float32 rows (x east, y north, height m); world z = -y.
 *  Returns { mesh (a group), ready, dispose }. With no trees or a failed fetch the group stays empty. */
export function createTrees({ url, count, extent, plate }) {
  const group = new THREE.Group();
  const owned = [];
  const u = plate.uniforms;
  const material = (trunk) => {
    const m = new THREE.ShaderMaterial({
      uniforms: { uMap: u.uMap, uExtent: u.uExtent, uDim: u.uDim, uGrow: u.uGrow, uTime: u.uTime, uTrunk: { value: trunk ? 1 : 0 } },
      vertexShader: TREE_VERTEX, fragmentShader: TREE_FRAGMENT,
    });
    owned.push(m);
    return m;
  };
  const ready = (!url || !count ? Promise.resolve(null) : fetch(url).then((r) => (r.ok ? r.arrayBuffer() : null)).catch(() => null))
    .then((buffer) => {
      if (!buffer) return;
      const rows = new Float32Array(buffer);
      const n = Math.floor(rows.length / 3);
      if (!n) return;
      const limit = extent / 2 - (plate.inset || 0) - 2;
      const crownGeo = new THREE.IcosahedronGeometry(1, 1);
      const trunkGeo = new THREE.CylinderGeometry(0.12, 0.18, 1, 5).translate(0, 0.5, 0);
      owned.push(crownGeo, trunkGeo);
      const crowns = new THREE.InstancedMesh(crownGeo, material(false), n);
      const trunks = new THREE.InstancedMesh(trunkGeo, material(true), n);
      const tree = new Float32Array(n * 3);
      const m = new THREE.Matrix4(), q = new THREE.Quaternion(), pos = new THREE.Vector3(), scl = new THREE.Vector3();
      let k = 0;
      for (let i = 0; i < n; i++) {
        const x = rows[i * 3], y = rows[i * 3 + 1], h = rows[i * 3 + 2];
        if (Math.abs(x) > limit || Math.abs(y) > limit) continue;
        const v = (Math.abs(Math.sin(x * 12.99 + y * 78.23)) * 43758.55) % 1;
        const radius = Math.max(1.4, Math.min(7.5, h * (0.24 + 0.08 * v)));
        const crownH = h * (0.34 + 0.08 * v);
        q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), v * Math.PI * 2);
        crowns.setMatrixAt(k, m.compose(pos.set(x, h - crownH, -y), q, scl.set(radius, crownH, radius * (0.9 + 0.2 * v))));
        trunks.setMatrixAt(k, m.compose(pos.set(x, 0, -y), q, scl.set(1 + h * 0.03, Math.max(1, h - crownH * 1.4), 1 + h * 0.03)));
        tree[k * 3] = x; tree[k * 3 + 1] = y; tree[k * 3 + 2] = v;
        k += 1;
      }
      crowns.count = trunks.count = k;
      crownGeo.setAttribute('aTree', new THREE.InstancedBufferAttribute(tree, 3));
      trunkGeo.setAttribute('aTree', new THREE.InstancedBufferAttribute(tree, 3));
      crowns.frustumCulled = trunks.frustumCulled = false;
      group.add(trunks, crowns);
    });
  return { mesh: group, ready, dispose() { owned.forEach((o) => o.dispose()); } };
}
