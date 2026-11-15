// The subject building, drawn as one storey-high slab per floor so each floor can be pointed at and pressed.
//
// The slabs carry a facade (spandrel band, glass, mullions), so in the Model view they read as one tower. In the
// Floors and Stacked views they open apart along the same outline. A floor lifts out and glows when hovered or
// marked; a floor with a walkthrough has a blue spandrel edge; vacancy colours appear only when switched on.
import * as THREE from 'three';

const LEASED = new THREE.Color('#c2761b');
const AVAILABLE = new THREE.Color('#1c8a68');
const NEUTRAL = new THREE.Color('#e9ecef');

const VERTEX = /* glsl */ `
  varying vec3 vWorld;
  varying vec3 vNormal;
  varying float vLevel;      // 0 at the bottom of the storey, 1 at the top
  uniform float uStorey;
  void main() {
    vLevel = position.y / uStorey;
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    vNormal = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * viewMatrix * world;
  }`;

const FRAGMENT = /* glsl */ `
  uniform float uHover;      // 0..1, eased
  uniform float uWalk;       // 1 on a floor with a walkthrough
  uniform vec3 uTint;        // vacancy colour
  uniform float uTintAmount; // 0 unless vacancy colours are on
  uniform float uDim;
  varying vec3 vWorld;
  varying vec3 vNormal;
  varying float vLevel;

  void main() {
    vec3 n = normalize(vNormal);
    vec3 sun = normalize(vec3(0.45, 0.8, 0.5));
    float diffuse = 0.62 + 0.38 * max(dot(n, sun), 0.0);
    vec3 concrete = vec3(0.86, 0.85, 0.82);
    vec3 color;
    if (abs(n.y) > 0.5) {
      color = concrete * (n.y > 0.0 ? 0.97 : 0.7);                     // floor plate and roof
    } else {
      // where the eye is along the wall, to space the mullions every 1.6 m
      float along = abs(n.x) > abs(n.z) ? vWorld.z : vWorld.x;
      float mullion = step(fract(along / 1.6), 0.07);
      float spandrel = step(vLevel, 0.3);
      // glass: darker low, catching the sky high up, with the facade's compass shading
      vec3 glass = mix(vec3(0.20, 0.29, 0.38), vec3(0.55, 0.68, 0.80), smoothstep(0.3, 1.0, vLevel));
      glass = mix(glass, uTint, uTintAmount * 0.75);
      glass = mix(glass, vec3(1.0, 0.86, 0.52), uHover * 0.6);            // a warm glow on the hovered floor
      vec3 band = mix(concrete, vec3(0.12, 0.42, 1.0), uWalk * 0.9);   // the walkthrough floor: a blue band all round
      color = mix(glass, band, max(spandrel, mullion * (1.0 - spandrel) * 0.85));
    }
    color *= diffuse;
    color += vec3(0.10, 0.07, 0.0) * uHover;
    color = mix(color, vec3(0.86, 0.88, 0.90), uDim * 0.6);
    gl_FragColor = vec4(color, 1.0);
  }`;

const ease = (t) => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);

export function createBuilding({ ring, roof, stories }) {
  const group = new THREE.Group();
  const centre2 = ring.reduce((acc, [x, y]) => [acc[0] + x / ring.length, acc[1] + y / ring.length], [0, 0]);
  const centre = new THREE.Vector3(centre2[0], 0, -centre2[1]);
  // outline around the centre, so a floor can lift out by scaling about its own middle
  const outline = new THREE.Shape(ring.map(([x, y]) => new THREE.Vector2(x - centre2[0], y - centre2[1])));
  const storeyHeight = Math.max(roof, 3) / stories;

  const slabGeometry = new THREE.ExtrudeGeometry(outline, { depth: storeyHeight, bevelEnabled: false });
  slabGeometry.rotateX(-Math.PI / 2);
  const dim = { value: 0 };
  const slabs = [];
  for (let floor = 1; floor <= stories; floor++) {
    const material = new THREE.ShaderMaterial({
      uniforms: {
        uStorey: { value: storeyHeight }, uHover: { value: 0 }, uWalk: { value: 0 },
        uTint: { value: NEUTRAL.clone() }, uTintAmount: { value: 0 }, uDim: dim,
      },
      vertexShader: VERTEX, fragmentShader: FRAGMENT,
    });
    const slab = new THREE.Mesh(slabGeometry, material);
    slab.position.set(centre.x, 0, centre.z);
    slab.userData = { floor, hover: 0, hoverTarget: 0, grow: 0 };
    slab.visible = false;
    group.add(slab);
    slabs.push(slab);
  }

  // spread: how far apart the floors sit (1 = touching); fill: how much of each storey the slab fills (1 = solid)
  const state = { spread: 1, spreadTarget: 1, fill: 1, fillTarget: 1, built: 0, vacancy: false };
  const scratch = new THREE.Color();
  const floorBase = (floor) => (floor - 1) * storeyHeight * state.spread;

  return {
    group,
    slabs,
    stories,
    storeyHeight,
    centre,
    eastEdge: Math.max(...ring.map(([x]) => x)),
    dim,
    floorMid: (floor) => floorBase(floor) + (storeyHeight * state.fill) / 2,
    height: () => floorBase(stories) + storeyHeight * state.fill,

    /** paint(floor) -> { leasedShare, available, emphasised, walk } */
    paint(describe) {
      for (const slab of slabs) {
        const { leasedShare = 0, available = false, emphasised = false, walk = false } = describe(slab.userData.floor);
        const u = slab.material.uniforms;
        scratch.copy(NEUTRAL);
        if (leasedShare > 0) scratch.lerp(LEASED, 0.35 + 0.65 * leasedShare);
        if (available) scratch.lerp(AVAILABLE, leasedShare > 0 ? 0.55 : 0.9);
        u.uTint.value.copy(scratch);
        u.uTintAmount.value = state.vacancy ? 1 : 0;
        u.uWalk.value = walk ? 1 : 0;
        slab.userData.hoverTarget = emphasised ? 1 : 0;
      }
    },

    setVacancy(on) {
      state.vacancy = on;
      slabs.forEach((slab) => { slab.material.uniforms.uTintAmount.value = on ? 1 : 0; });
    },
    /** view: 'model' closes the floors into one tower; 'floors' opens them; 'stacked' pulls them well apart */
    setLayout(view) {
      state.spreadTarget = view === 'stacked' ? 2.4 : view === 'floors' ? 1.4 : 1;
      state.fillTarget = view === 'model' ? 1 : 0.8;
    },
    setBuilt(share) { state.built = share; },

    update() {
      state.spread += (state.spreadTarget - state.spread) * 0.12;
      state.fill += (state.fillTarget - state.fill) * 0.12;
      for (const slab of slabs) {
        const d = slab.userData;
        // the reveal raises the tower floor by floor, each one growing smoothly instead of popping in
        d.grow = ease(state.built * stories - (d.floor - 1));
        slab.visible = d.grow > 0.001;
        d.hover += (d.hoverTarget - d.hover) * 0.2;
        slab.material.uniforms.uHover.value = d.hover;
        const lift = 1 + 0.03 * d.hover;                                   // the hovered floor slides out a little
        slab.scale.set(lift, state.fill * d.grow, lift);
        slab.position.y = floorBase(d.floor);
      }
    },

    dispose() {
      slabGeometry.dispose();
      slabs.forEach((slab) => slab.material.dispose());
    },
  };
}
