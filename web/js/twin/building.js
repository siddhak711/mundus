// The subject building, drawn as one storey-high slab per floor so each floor can be pointed at and pressed.
//
// The slabs carry the same realistic facade as the street around them (facade.js, tower style), with the real aerial
// photo as the roof, so in the Model view they are the building itself; the Floors and Stacked views cut it apart
// along its own outline, floor by floor on springs. A floor slides out and brightens when hovered or marked; a floor
// with a walkthrough carries a soft blue; vacancy colours tint the floors when switched on.
import * as THREE from 'three';
import { FACADE_GLSL } from './facade.js';

// vacancy colours: the empty floors stand out on the real building; leased floors keep the building's own look
const VACANCY = { convertible: [new THREE.Color('#16a06e'), 0.72], partial: [new THREE.Color('#f2a900'), 0.64] };
const NEUTRAL = new THREE.Color('#e9ecef');
const TOWER_SEED = 0.137;          // fixed: the subject always gets the same facade

const VERTEX = /* glsl */ `
  uniform float uFloorBase;        // metres from the street to this floor, for the facade pattern
  varying vec3 vWorld;
  varying vec3 vNormal;
  varying float vAlong;
  varying float vUp;
  void main() {
    vAlong = uv.x;                 // metres along the wall (ExtrudeGeometry side-wall UVs)
    vUp = uFloorBase + position.y; // the pattern belongs to the floor, so it travels with it when the floors open
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    vNormal = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * viewMatrix * world;
  }`;

const FRAGMENT = /* glsl */ `
  uniform sampler2D uMap;
  uniform float uExtent;
  uniform float uIsTop;      // 1 on the top floor, whose upper face is the real roof
  uniform float uHeight;     // the whole building's height
  uniform float uStorey;     // storey height, so the facade's floors line up with the slabs
  uniform float uHover;      // 0..1, on a spring
  uniform float uWalk;       // 1 on a floor with a walkthrough
  uniform vec3 uTint;        // vacancy colour
  uniform float uTintAmount; // 0 unless vacancy colours are on
  uniform float uDim;
  varying vec3 vWorld;
  varying vec3 vNormal;
  varying float vAlong;
  varying float vUp;
  ${FACADE_GLSL}

  void main() {
    vec3 n = normalize(vNormal);
    vec3 color;
    if (n.y > 0.5) {
      vec3 photo = texture2D(uMap, vec2(vWorld.x / uExtent + 0.5, -vWorld.z / uExtent + 0.5)).rgb;
      color = mix(vec3(0.78, 0.79, 0.80), photo * (0.94 + 0.08 * max(dot(n, SUN), 0.0)), uIsTop);   // section, or roof
    } else if (n.y < -0.5) {
      color = vec3(0.58, 0.60, 0.62);                                          // underside of a cut floor
    } else {
      color = facade(n, vWorld, vAlong, vUp, uHeight, ${TOWER_SEED.toFixed(3)}, uStorey);
      float shade = 0.72 + 0.28 * max(dot(n, SUN), 0.0);
      color = mix(color, uTint * shade, uTintAmount);
      color = mix(color, vec3(0.42, 0.62, 1.0) * shade, uWalk * 0.30);
      color = mix(color, min(color * 1.25 + 0.06, vec3(1.0)), uHover);       // the hovered floor brightens (and slides out)
    }
    color = atmosphere(color, vWorld);
    color = mix(color, vec3(0.86, 0.88, 0.90), uDim * 0.72);
    gl_FragColor = vec4(color, 1.0);
  }`;

const ease = (t) => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);

// Critically damped spring, integrated implicitly so it is stable at any frame time. Returns [x, v].
function spring(x, v, target, omega, dt) {
  const f = 1 + 2 * dt * omega;
  const oo = omega * omega;
  const hoo = dt * oo;
  const hhoo = dt * hoo;
  const inv = 1 / (f + hhoo);
  return [(f * x + dt * v + hhoo * target) * inv, (v + hoo * (target - x)) * inv];
}

const STAGGER_MS = 18;             // each floor starts this long after its neighbour when the building opens or closes
const OMEGA = 11;                  // spring stiffness (rad/s): settles in about half a second
const HOVER_OMEGA = 16;

export function createBuilding({ ring, roof, stories }, plate) {
  const group = new THREE.Group();
  const centre2 = ring.reduce((acc, [x, y]) => [acc[0] + x / ring.length, acc[1] + y / ring.length], [0, 0]);
  const centre = new THREE.Vector3(centre2[0], 0, -centre2[1]);
  // outline around the centre, so a floor can lift out by scaling about its own middle
  const outline = new THREE.Shape(ring.map(([x, y]) => new THREE.Vector2(x - centre2[0], y - centre2[1])));
  const height = Math.max(roof, 3);
  const storeyHeight = height / stories;

  const slabGeometry = new THREE.ExtrudeGeometry(outline, { depth: storeyHeight, bevelEnabled: false });
  slabGeometry.rotateX(-Math.PI / 2);
  const dim = { value: 0 };
  const slabs = [];
  for (let floor = 1; floor <= stories; floor++) {
    const material = new THREE.ShaderMaterial({
      uniforms: {
        uMap: plate.uniforms.uMap, uExtent: plate.uniforms.uExtent, uTime: plate.uniforms.uTime,
        uIsTop: { value: floor === stories ? 1 : 0 }, uHeight: { value: height }, uStorey: { value: storeyHeight },
        uFloorBase: { value: (floor - 1) * storeyHeight },
        uHover: { value: 0 }, uWalk: { value: 0 }, uTint: { value: NEUTRAL.clone() }, uTintAmount: { value: 0 }, uDim: dim,
      },
      vertexShader: VERTEX, fragmentShader: FRAGMENT,
    });
    const slab = new THREE.Mesh(slabGeometry, material);
    const base = (floor - 1) * storeyHeight;
    slab.position.set(centre.x, base, centre.z);
    slab.userData = {
      floor, grow: 0,
      y: base, vy: 0, fill: 1, vfill: 0,                         // where the floor sits and how much storey it fills
      spread: 1, fillTarget: 1, switchAt: 0, nextSpread: 1, nextFill: 1,
      hover: 0, vhover: 0, hoverTarget: 0, tint: 0,
    };
    slab.visible = false;
    group.add(slab);
    slabs.push(slab);
  }

  const state = { built: 0, vacancy: true, spread: 1, fill: 1, last: 0 };

  return {
    group,
    slabs,
    stories,
    storeyHeight,
    centre,
    eastEdge: Math.max(...ring.map(([x]) => x)),
    dim,
    floorMid: (floor) => { const d = slabs[floor - 1].userData; return d.y + (storeyHeight * d.fill) / 2; },
    height: () => { const d = slabs[stories - 1].userData; return d.y + storeyHeight * d.fill; },

    /** paint(floor) -> { vacancy: 'convertible' | 'partial' | 'leased' | 'no_data', emphasised, walk } */
    paint(describe) {
      for (const slab of slabs) {
        const { vacancy = null, emphasised = false, walk = false } = describe(slab.userData.floor);
        const u = slab.material.uniforms;
        const [color, amount] = VACANCY[vacancy] || [NEUTRAL, 0];
        u.uTint.value.copy(color);
        slab.userData.tint = amount;
        u.uTintAmount.value = state.vacancy ? amount : 0;
        u.uWalk.value = walk ? 1 : 0;
        slab.userData.hoverTarget = emphasised ? 1 : 0;
      }
    },

    setVacancy(on) {
      state.vacancy = on;
      slabs.forEach((slab) => { slab.material.uniforms.uTintAmount.value = on ? slab.userData.tint || 0 : 0; });
    },

    /** view: 'model' closes the floors into one tower; 'floors' opens them; 'stacked' pulls them well apart.
     *  The floors follow one after another: from the bottom when opening, from the top when closing. */
    setLayout(view) {
      const spread = view === 'stacked' ? 2.4 : view === 'floors' ? 1.4 : 1;
      const fill = view === 'model' ? 1 : 0.8;
      const opening = spread >= state.spread;
      const now = performance.now();
      for (const slab of slabs) {
        const d = slab.userData;
        const order = opening ? d.floor - 1 : stories - d.floor;
        d.switchAt = now + order * STAGGER_MS;
        d.nextSpread = spread;
        d.nextFill = fill;
      }
      state.spread = spread;
      state.fill = fill;
    },
    setBuilt(share) { state.built = share; },

    update() {
      const now = performance.now();
      const dt = state.last ? Math.min(0.05, (now - state.last) / 1000) : 1 / 60;
      state.last = now;
      for (const slab of slabs) {
        const d = slab.userData;
        if (now >= d.switchAt) { d.spread = d.nextSpread; d.fillTarget = d.nextFill; }
        [d.y, d.vy] = spring(d.y, d.vy, (d.floor - 1) * storeyHeight * d.spread, OMEGA, dt);
        [d.fill, d.vfill] = spring(d.fill, d.vfill, d.fillTarget, OMEGA, dt);
        [d.hover, d.vhover] = spring(d.hover, d.vhover, d.hoverTarget, HOVER_OMEGA, dt);
        // the reveal raises the tower floor by floor, each one growing smoothly instead of popping in
        d.grow = ease(state.built * stories - (d.floor - 1));
        slab.visible = d.grow > 0.001;
        const h = Math.max(0, d.hover);
        slab.material.uniforms.uHover.value = Math.min(1, h);
        const lift = 1 + 0.03 * h;                                       // the hovered floor slides out a little
        slab.scale.set(lift, Math.max(0.001, d.fill * d.grow), lift);
        slab.position.y = d.y;
      }
    },

    dispose() {
      slabGeometry.dispose();
      slabs.forEach((slab) => slab.material.dispose());
    },
  };
}
