// The subject building, drawn as one slab per floor so each floor can carry data.
import * as THREE from 'three';

const NEUTRAL = new THREE.Color('#e9ecef');
const LEASED = new THREE.Color('#c2761b');
const AVAILABLE = new THREE.Color('#1c8a68');
const EMPHASIS = new THREE.Color('#17212b');
const WALK = new THREE.Color('#1f6bff');  // a floor with a walkthrough: press it to go inside
const SLAB_FILL = 0.8; // share of each storey that is slab; the rest is a visible gap

export function createBuilding({ ring, roof, stories }) {
  const group = new THREE.Group();
  const outline = new THREE.Shape(ring.map(([x, y]) => new THREE.Vector2(x, y)));
  const storeyHeight = Math.max(roof, 3) / stories;

  const slabGeometry = new THREE.ExtrudeGeometry(outline, { depth: storeyHeight * SLAB_FILL, bevelEnabled: false });
  slabGeometry.rotateX(-Math.PI / 2);
  const slabs = [];
  for (let floor = 1; floor <= stories; floor++) {
    const slab = new THREE.Mesh(slabGeometry, new THREE.MeshLambertMaterial({ color: NEUTRAL.clone() }));
    slab.userData.floor = floor;
    slab.visible = false;
    group.add(slab);
    slabs.push(slab);
  }

  const shellGeometry = new THREE.ExtrudeGeometry(outline, { depth: 1, bevelEnabled: false });
  shellGeometry.rotateX(-Math.PI / 2);
  const shell = new THREE.Mesh(shellGeometry, new THREE.MeshBasicMaterial({ color: 0x8fa9bf, transparent: true, opacity: 0, depthWrite: false }));
  const shellEdges = new THREE.LineSegments(new THREE.EdgesGeometry(shellGeometry, 20), new THREE.LineBasicMaterial({ color: 0x4f6272, transparent: true, opacity: 0 }));
  shell.renderOrder = 2;
  group.add(shell, shellEdges);

  const centre = ring.reduce((acc, [x, y]) => [acc[0] + x / ring.length, acc[1] + y / ring.length], [0, 0]);
  const state = { spread: 1, spreadTarget: 1, shell: 0, shellTarget: 0.16, built: 0 };
  const scratch = new THREE.Color();

  const floorBase = (floor) => (floor - 1) * storeyHeight * state.spread;

  return {
    group,
    slabs,
    stories,
    storeyHeight,
    centre: new THREE.Vector3(centre[0], 0, -centre[1]),
    eastEdge: Math.max(...ring.map(([x]) => x)),
    floorMid: (floor) => floorBase(floor) + (storeyHeight * SLAB_FILL) / 2,
    height: () => floorBase(stories) + storeyHeight,

    /** paint(floor) -> { leasedShare, available, emphasised, walk } */
    paint(describe) {
      for (const slab of slabs) {
        const { leasedShare = 0, available = false, emphasised = false, walk = false } = describe(slab.userData.floor);
        scratch.copy(NEUTRAL);
        if (leasedShare > 0) scratch.lerp(LEASED, 0.35 + 0.65 * leasedShare);
        if (available) scratch.lerp(AVAILABLE, leasedShare > 0 ? 0.55 : 0.9);
        if (walk) scratch.copy(WALK);
        if (emphasised) scratch.lerp(EMPHASIS, 0.55);
        slab.material.color.copy(scratch);
      }
    },

    setSpread(value) { state.spreadTarget = value; },
    setShell(value) { state.shellTarget = value; },
    setBuilt(share) {
      state.built = share;
      const shown = Math.floor(share * stories + 1e-6);
      slabs.forEach((slab, i) => { slab.visible = i < shown; });
    },

    update() {
      state.spread += (state.spreadTarget - state.spread) * 0.1;
      state.shell += ((state.built >= 1 ? state.shellTarget : 0) - state.shell) * 0.1;
      slabs.forEach((slab) => { slab.position.y = floorBase(slab.userData.floor); });
      const top = floorBase(stories) + storeyHeight;
      shell.scale.y = shellEdges.scale.y = top;
      shell.material.opacity = state.shell;
      shellEdges.material.opacity = Math.min(1, state.shell * 4);
      shell.visible = shellEdges.visible = state.shell > 0.01;
    },

    dispose() {
      slabGeometry.dispose();
      shellGeometry.dispose();
      slabs.forEach((slab) => slab.material.dispose());
    },
  };
}
