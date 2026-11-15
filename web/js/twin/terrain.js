// The surrounding city: Vexcel's height model as a mesh, textured with the aerial photo.
import * as THREE from 'three';

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

// ---- the diorama: a ground plate with the aerial photo, and the neighbours as clean blocks ------------------------

const PLATE_VERTEX = /* glsl */ `
  uniform float uGrow;
  varying vec3 vWorld;
  varying vec3 vNormal;
  void main() {
    vec3 p = position;
    p.y *= uGrow;
    vec4 world = modelMatrix * vec4(p, 1.0);
    vWorld = world.xyz;
    vNormal = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * viewMatrix * world;
  }`;

// Roofs and the ground show the aerial photo, mapped from above by world position; walls are plain light massing,
// shaded by compass direction, so the city reads cleanly around the subject building.
const PLATE_FRAGMENT = /* glsl */ `
  uniform sampler2D uMap;
  uniform float uExtent;
  uniform float uDim;
  varying vec3 vWorld;
  varying vec3 vNormal;
  void main() {
    vec2 uv = vec2(vWorld.x / uExtent + 0.5, -vWorld.z / uExtent + 0.5);
    vec3 photo = texture2D(uMap, uv).rgb;
    vec3 n = normalize(vNormal);
    vec3 color;
    if (n.y > 0.5) {
      color = photo;
    } else {
      float facing = 0.80 + 0.14 * dot(normalize(n.xz + 1e-4), normalize(vec2(0.45, 0.6)));
      float foot = smoothstep(0.0, 6.0, vWorld.y);                 // a little darker where walls meet the street
      color = vec3(0.90, 0.91, 0.92) * facing * (0.86 + 0.14 * foot);
    }
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
  const uniforms = { uMap: { value: map }, uExtent: { value: extent }, uDim: { value: 0 }, uGrow: { value: 0 } };

  const group = new THREE.Group();
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(extent, extent).rotateX(-Math.PI / 2),
    new THREE.ShaderMaterial({ uniforms: { ...uniforms, uGrow: { value: 1 } }, vertexShader: PLATE_VERTEX, fragmentShader: PLATE_FRAGMENT }));
  ground.material.uniforms.uDim = uniforms.uDim;                     // shared, so the scan dimming reaches it

  const depth = extent * 0.035;
  const base = new THREE.Mesh(new THREE.BoxGeometry(extent, depth, extent), [
    ...Array(2).fill(new THREE.MeshLambertMaterial({ color: 0x3b4654 })),   // +x, -x
    new THREE.MeshLambertMaterial({ color: 0x3b4654 }), new THREE.MeshLambertMaterial({ color: 0x2b333d }),  // top, bottom
    ...Array(2).fill(new THREE.MeshLambertMaterial({ color: 0x46525f })),   // +z, -z
  ]);
  base.position.y = -depth / 2 - 0.05;
  const h = extent / 2;
  const rimPoints = [[-h, -h], [h, -h], [h, h], [-h, h], [-h, -h]].map(([x, z]) => new THREE.Vector3(x, 0.15, z));
  const rim = new THREE.Line(new THREE.BufferGeometry().setFromPoints(rimPoints), new THREE.LineBasicMaterial({ color: 0xf4f7fa }));
  const lowerRim = new THREE.Line(new THREE.BufferGeometry().setFromPoints(rimPoints.map((p) => p.clone().setY(-depth))),
    new THREE.LineBasicMaterial({ color: 0x1d242c }));
  group.add(ground, base, rim, lowerRim);

  return {
    group, uniforms, ready, map,
    dispose() {
      map.dispose();
      group.traverse((o) => { o.geometry?.dispose(); [].concat(o.material || []).forEach((m) => m.dispose()); });
    },
  };
}

/** Neighbouring buildings as clean extruded blocks, cut to the plate. One merged mesh: one draw call. */
export function createBlocks({ neighbours, extent, plate }) {
  const h = extent / 2 - 0.5;
  const clamp = (v) => Math.max(-h, Math.min(h, v));
  const parts = [];
  for (const { ring, height } of neighbours) {
    if (!ring?.length || !(height > 1)) continue;
    const pts = ring.map(([x, y]) => new THREE.Vector2(clamp(x), clamp(y)));
    const shape = new THREE.Shape(pts);
    if (Math.abs(THREE.ShapeUtils.area(pts)) < 4) continue;          // slivers left after cutting to the plate
    const g = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false });
    g.rotateX(-Math.PI / 2);                                         // shape y (north) -> -z, depth -> up
    g.deleteAttribute('uv');
    parts.push(g.index ? g.toNonIndexed() : g);
  }
  const positions = [], normals = [];
  for (const g of parts) {
    positions.push(...g.getAttribute('position').array);
    normals.push(...g.getAttribute('normal').array);
    g.dispose();
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  const mesh = new THREE.Mesh(geometry, new THREE.ShaderMaterial({
    uniforms: { uMap: plate.uniforms.uMap, uExtent: plate.uniforms.uExtent, uDim: plate.uniforms.uDim, uGrow: plate.uniforms.uGrow },
    vertexShader: PLATE_VERTEX, fragmentShader: PLATE_FRAGMENT,
  }));
  return { mesh, dispose() { geometry.dispose(); mesh.material.dispose(); } };
}
