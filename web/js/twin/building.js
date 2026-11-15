// The subject building, drawn as one storey-high slab per floor so each floor can be pointed at and pressed.
//
// The slabs look exactly like the neighbouring buildings, so in the Model view they are the building itself; the
// Floors and Stacked views cut it apart along its own outline. A floor slides out and warms when hovered or marked; a
// floor with a walkthrough carries a soft blue; vacancy colours appear only when switched on.
import * as THREE from 'three';

// vacancy colours: the empty floors stand out on the real building; leased floors keep the building's own colour
const VACANCY = { convertible: [new THREE.Color('#16a06e'), 0.78], partial: [new THREE.Color('#f2a900'), 0.7] };
const NEUTRAL = new THREE.Color('#e9ecef');

const VERTEX = /* glsl */ `
  varying vec3 vWorld;
  varying vec3 vNormal;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    vNormal = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * viewMatrix * world;
  }`;

// The same look as the neighbouring blocks (terrain.js): light walls shaded by compass direction, and the aerial photo
// on the roof. Cut apart, a floor shows a clean section where it was joined to the next one.
const FRAGMENT = /* glsl */ `
  uniform sampler2D uMap;
  uniform float uExtent;
  uniform float uIsTop;      // 1 on the top floor, whose upper face is the real roof
  uniform float uHover;      // 0..1, eased
  uniform float uWalk;       // 1 on a floor with a walkthrough
  uniform vec3 uTint;        // vacancy colour
  uniform float uTintAmount; // 0 unless vacancy colours are on
  uniform float uDim;
  varying vec3 vWorld;
  varying vec3 vNormal;

  void main() {
    vec3 n = normalize(vNormal);
    vec3 color;
    if (n.y > 0.5) {
      vec3 photo = texture2D(uMap, vec2(vWorld.x / uExtent + 0.5, -vWorld.z / uExtent + 0.5)).rgb;
      color = mix(vec3(0.80, 0.81, 0.82), photo, uIsTop);
    } else if (n.y < -0.5) {
      color = vec3(0.62, 0.64, 0.66);
    } else {
      float facing = 0.80 + 0.14 * dot(normalize(n.xz + 1e-4), normalize(vec2(0.45, 0.6)));
      color = vec3(0.90, 0.91, 0.92) * facing;
      color = mix(color, uTint * facing, uTintAmount);
      color = mix(color, vec3(0.42, 0.62, 1.0) * facing, uWalk * 0.32);
      color = mix(color, min(color * 1.25 + 0.06, vec3(1.0)), uHover);       // the hovered floor brightens (and slides out)
    }
    color = mix(color, vec3(0.86, 0.88, 0.90), uDim * 0.72);
    gl_FragColor = vec4(color, 1.0);
  }`;

const ease = (t) => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);

export function createBuilding({ ring, roof, stories }, plate) {
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
        uMap: plate.uniforms.uMap, uExtent: plate.uniforms.uExtent, uIsTop: { value: floor === stories ? 1 : 0 },
        uHover: { value: 0 }, uWalk: { value: 0 }, uTint: { value: NEUTRAL.clone() }, uTintAmount: { value: 0 }, uDim: dim,
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
  const state = { spread: 1, spreadTarget: 1, fill: 1, fillTarget: 1, built: 0, vacancy: true };
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
