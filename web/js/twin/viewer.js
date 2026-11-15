// Owns the three.js scene for one property: a model of the block on a plate under the sky, the building's floors,
// and an optional interior scan.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createBlocks, createFootprints, createPlate, createTerrain } from './terrain.js';
import * as terrainModule from './terrain.js';      // createTrees, when this terrain.js has it
import { createBuilding } from './building.js';
import { loadScanModel } from './scan.js';

const REVEAL_SECONDS = 3.2;
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const clamp01 = (t) => Math.min(1, Math.max(0, t));
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const IDLE_MS = 8000;          // no input for this long: the camera starts a slow drift round the building
const DRIFT_SPEED = 0.35;      // OrbitControls autoRotateSpeed at full drift

// Camera interpolation around a moving target: the target slides, the distance eases and the viewing direction turns
// on a sphere, so a move arcs over the scene instead of cutting straight through it.
const scratchQ = new THREE.Quaternion();
const identityQ = new THREE.Quaternion();
function orbitLerp(camera, controls, from, to, k) {
  const target = new THREE.Vector3().lerpVectors(from.target, to.target, k);
  const a = new THREE.Vector3().subVectors(from.position, from.target);
  const b = new THREE.Vector3().subVectors(to.position, to.target);
  const da = a.length() || 1, db = b.length() || 1;
  a.divideScalar(da); b.divideScalar(db);
  scratchQ.setFromUnitVectors(a, b);
  const dir = a.applyQuaternion(identityQ.clone().slerp(scratchQ, k));
  camera.position.copy(target).addScaledVector(dir, da + (db - da) * k);
  controls.target.copy(target);
  camera.lookAt(target);
}

export class Viewer {
  constructor({ canvas, labelLayer, onFloorHover, onFloorMove, onFloorClick }) {
    this.canvas = canvas;
    this.labelLayer = labelLayer;
    this.onFloorHover = onFloorHover;   // the floor under the pointer changed
    this.onFloorMove = onFloorMove;     // same floor, pointer moved: only the tooltip follows
    this.onFloorClick = onFloorClick;

    // transparent: the sky is the stage's CSS gradient behind the canvas, so it is there before the first frame
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setClearColor(0x000000, 0);
    // 1.5x is sharp on a retina screen at about half the pixels of 2x: the terrain shader runs per pixel
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    this.renderer.autoClear = false;

    this.scene = new THREE.Scene();
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xb9c2cc, 1.9));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(0.45, 0.8, 0.5);
    this.scene.add(sun);
    this.overlay = new THREE.Scene(); // drawn after the city with a fresh depth buffer, so it is never hidden

    this.camera = new THREE.PerspectiveCamera(40, 1, 1, 12000);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.maxPolarAngle = Math.PI * 0.49;

    this.pins = [];
    this.flight = null;
    this.reveal = null;
    this.hoveredFloor = 0;
    this.pointer = new THREE.Vector2();
    this.raycaster = new THREE.Raycaster();
    this.layers = { heights: false, footprints: false };
    this.pendingPointer = null;   // latest pointermove, handled once per frame
    this.rect = canvas.getBoundingClientRect();

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas.parentElement);
    canvas.addEventListener('pointermove', (e) => this.handlePointerMove(e));
    canvas.addEventListener('pointerleave', () => this.setHover(0));
    canvas.addEventListener('pointerdown', (e) => { this.pressAt = [e.clientX, e.clientY]; });
    canvas.addEventListener('pointerup', (e) => this.handlePointerUp(e));
    // any input stops the idle drift at once and restarts its clock
    this.lastInput = performance.now();
    this.drift = 0;
    this.onInput = () => { this.lastInput = performance.now(); this.drift = 0; this.controls.autoRotate = false; };
    for (const type of ['pointerdown', 'pointermove', 'wheel']) canvas.addEventListener(type, this.onInput, { passive: true });
    addEventListener('keydown', this.onInput);

    this.running = true;
    this.frame = this.frame.bind(this);
    requestAnimationFrame(this.frame);
  }

  // ---- loading -------------------------------------------------------------
  /** opts.metresPerPixel: the map's scale when the building was opened from it; the opening view then matches it. */
  async load(twin, opts = {}) {
    const heights = new Float32Array(await (await fetch(twin.heights)).arrayBuffer());
    this.extent = twin.extent;
    this.twin = twin;
    this.heightsData = heights;                       // the detailed surface model, drawn only as the Height map layer
    this.plate = createPlate({ extent: twin.extent, orthoUrl: twin.ortho, anisotropy: this.renderer.capabilities.getMaxAnisotropy() });
    this.blocks = createBlocks({ neighbours: twin.neighbours, extent: twin.extent, plate: this.plate });
    // the street trees, from the surface model (twin version 2); an older cached model simply has none
    if (twin.trees && typeof terrainModule.createTrees === 'function') {
      this.trees = terrainModule.createTrees({ url: twin.trees, count: twin.treeCount || 0, extent: twin.extent, plate: this.plate });
      this.scene.add(this.trees.mesh);
    }
    this.footprints = createFootprints(twin.neighbours);
    this.building = createBuilding(twin.building, this.plate);    // same look as the neighbours, cut into floors
    this.scene.add(this.plate.group, this.blocks.mesh, this.footprints, this.building.group);

    this.controls.minDistance = twin.extent * 0.04;
    this.controls.maxDistance = twin.extent * 3;
    this.view = 'model';
    this.resize();
    // Where the opening animation starts. From the map: straight down, north up, centred on the dot and at the map's
    // scale, so the cross-fade lines the aerial photo up with the map. Otherwise the usual plan view.
    this.startView = opts.metresPerPixel ? this.cameraForScale(opts.metresPerPixel) : this.cameraFor('plan');
    this.placeCamera(this.startView);
    this.controls.enabled = false;

    // Upload the aerial photo and compile every shader now, not on the first frame that needs them: otherwise both
    // land in the middle of the opening animation as a visible stall.
    await Promise.all([this.plate.ready, this.trees?.ready]);
    this.renderer.initTexture(this.plate.map);
    this.building.setBuilt(1);                       // floors start hidden; show them so their material compiles too
    this.building.update();
    this.footprints.visible = true;
    this.renderer.compile(this.scene, this.camera);
    this.building.setBuilt(0);
    this.building.update();
    this.footprints.visible = this.layers.footprints;

    if (reducedMotion()) {
      this.plate.uniforms.uGrow.value = 1;
      this.building.setBuilt(1);
      this.placeCamera(this.cameraFor('model'));
      this.controls.enabled = true;
    } else {
      this.controls.enabled = false;
      this.reveal = { start: performance.now(), from: this.startView, to: this.cameraFor('model') };
    }
    this.resize();
  }

  /** Start the opening fly-in over, so it plays when the view becomes visible rather than while it was hidden. */
  restartReveal() {
    if (this.reveal) this.reveal.start = performance.now();
  }

  // ---- camera --------------------------------------------------------------
  cameraFor(view) {
    const e = this.extent;
    const c = this.building.centre;
    const h = this.building.storeyHeight * this.building.stories;
    if (view === 'plan') {
      return { position: new THREE.Vector3(c.x, e * 1.25, c.z + e * 0.02), target: new THREE.Vector3(c.x, 0, c.z) };
    }
    if (view === 'stacked') {
      const tall = h * 2.4;
      return { position: new THREE.Vector3(c.x + e * 0.8, tall * 0.6 + e * 0.2, c.z + e), target: new THREE.Vector3(c.x, tall * 0.45, c.z) };
    }
    return { position: new THREE.Vector3(c.x - e * 0.5, Math.max(e * 0.4, h * 1.15), c.z + e * 0.62), target: new THREE.Vector3(c.x, h * 0.42, c.z) };
  }

  placeCamera({ position, target }) {
    this.camera.position.copy(position);
    this.controls.target.copy(target);
    this.camera.lookAt(target);
  }

  /** Straight down over the property's point (the map dot), north up, showing metresPerPixel at this canvas width. */
  cameraForScale(metresPerPixel) {
    const width = (this.rect?.width || this.canvas.clientWidth || 1000) * metresPerPixel;
    const halfFov = THREE.MathUtils.degToRad(this.camera.fov / 2);
    const height = width / (2 * Math.tan(halfFov) * (this.camera.aspect || 1.5));
    // about a degree off vertical: straight down, lookAt is unstable and the first frames of the tilt can roll
    return { position: new THREE.Vector3(0, height, height * 0.02), target: new THREE.Vector3(0, 0, 0) };
  }

  /**
   * Fly the camera to a view, arcing around the target. destination is { position, target } or a function returning
   * one each frame (for a target that is itself moving). The duration follows the distance unless given.
   * Resolves when the camera arrives.
   */
  flyTo(destination, milliseconds) {
    const resolveDest = typeof destination === 'function' ? destination : () => destination;
    if (reducedMotion()) { this.placeCamera(resolveDest()); return Promise.resolve(); }
    const first = resolveDest();
    const travel = first.position.distanceTo(this.camera.position) + first.target.distanceTo(this.controls.target);
    const ms = milliseconds ?? Math.min(1600, Math.max(700, 700 + 900 * (travel / (this.extent || 600))));
    this.flight?.done?.();                                      // a newer flight replaces an unfinished one
    return new Promise((done) => {
      this.flight = {
        start: performance.now(), milliseconds: ms, destination: resolveDest, done,
        from: { position: this.camera.position.clone(), target: this.controls.target.clone() },
      };
    });
  }

  /** Open the floors and fly up close to one, facing it from the side the camera is already on. */
  flyToFloor(floor) {
    this.view = 'floors';
    this.building.setLayout('floors');
    const c = this.building.centre;
    const side = new THREE.Vector3().subVectors(this.camera.position, this.controls.target).setY(0);
    if (side.lengthSq() < 1) side.set(-0.6, 0, 0.8);
    side.normalize();
    const span = Math.max(40, Math.min(this.extent * 0.22, 140));
    // the floor keeps moving while the floors open: aim at where it is on every frame
    return this.flyTo(() => {
      const y = this.building.floorMid(floor);
      const target = new THREE.Vector3(c.x, y, c.z);
      return { target, position: target.clone().addScaledVector(side, span).add(new THREE.Vector3(0, span * 0.18, 0)) };
    }, 1500);
  }

  setView(view) {
    this.view = view;
    this.building.setLayout(view);
    // During the opening reveal, steer the reveal to this view rather than starting a second camera move: two moves at
    // once fought over the camera, landing it early and then pulling it back up.
    if (this.reveal && !this.flight) { this.reveal.to = this.cameraFor(view); return; }
    this.flyTo(this.cameraFor(view));
  }

  setLayer(name, on) {
    this.layers[name] = on;
    if (name === 'footprints') this.footprints.visible = on;
    if (name === 'heights') {
      // the detailed surface model (trees, every roof) replaces the clean blocks while this layer is on
      if (on && !this.terrain) {
        this.terrain = createTerrain({ extent: this.twin.extent, grid: this.twin.grid, heights: this.heightsData,
          orthoUrl: this.twin.ortho, sky: '#dfe7ee', anisotropy: this.renderer.capabilities.getMaxAnisotropy() });
        this.terrain.uniforms.uGrow.value = 1;
        this.scene.add(this.terrain.mesh);
      }
      if (this.terrain) this.terrain.mesh.visible = on;
      this.blocks.mesh.visible = !on;
      if (this.trees) this.trees.mesh.visible = !on;   // the surface model has its own trees
      this.plate.group.children[0].visible = !on;     // the flat ground under the photo
    }
  }

  setVacancy(on) { this.building?.setVacancy(on);
  }

  // ---- floors --------------------------------------------------------------
  paint(describe) { this.building?.paint(describe); }

  setPins(pins) {
    this.labelLayer.replaceChildren();
    this.pins = pins.map((pin) => {
      const el = document.createElement(pin.onClick ? 'button' : 'div');
      el.className = `pin${pin.onClick ? '' : ' is-height'}${pin.walk ? ' is-walk' : ''}`;
      el.textContent = pin.label;
      if (pin.onClick) { el.type = 'button'; el.addEventListener('click', pin.onClick); }
      this.labelLayer.append(el);
      return { ...pin, el };
    });
  }

  updatePins() {
    const visible = !this.reveal && !this.scan;
    const rect = this.rect;            // measured on resize, not every frame: reading layout here forces a reflow
    const anchor = this.anchor || (this.anchor = new THREE.Vector3());
    for (const pin of this.pins) {
      const y = pin.floor ? this.building.floorMid(pin.floor) : this.building.height() + this.extent * 0.01;
      anchor.set(this.building.eastEdge, y, this.building.centre.z).project(this.camera);
      const shown = visible && anchor.z < 1;
      if (pin.el.hidden === shown) pin.el.hidden = !shown;
      if (!shown) continue;
      const x = Math.round((anchor.x * 0.5 + 0.5) * rect.width * 2) / 2;
      const y2 = Math.round((-anchor.y * 0.5 + 0.5) * rect.height * 2) / 2;
      if (x !== pin.x || y2 !== pin.y) {     // only touch the DOM when the pin actually moves
        pin.x = x; pin.y = y2;
        pin.el.style.setProperty('--x', `${x}px`);
        pin.el.style.setProperty('--y', `${y2}px`);
      }
    }
  }

  floorUnder(event) {
    if (!this.building || this.reveal) return 0;
    const rect = this.rect;
    this.pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = this.raycaster.intersectObjects(this.building.slabs, false)[0];
    return hit ? hit.object.userData.floor : 0;
  }

  setHover(floor, event) {
    if (floor === this.hoveredFloor) return;
    this.hoveredFloor = floor;
    this.canvas.style.cursor = floor ? 'pointer' : 'grab';
    this.onFloorHover?.(floor, event);
  }

  // pointermove can fire far more often than frames are drawn: keep the latest and raycast once per frame
  handlePointerMove(event) { this.pendingPointer = event; }

  hoverStep() {
    const event = this.pendingPointer;
    if (!event) return;
    this.pendingPointer = null;
    const floor = this.floorUnder(event);
    if (floor !== this.hoveredFloor) this.setHover(floor, event);
    else if (floor) this.onFloorMove?.(event);
  }

  handlePointerUp(event) {
    const moved = this.pressAt ? Math.hypot(event.clientX - this.pressAt[0], event.clientY - this.pressAt[1]) : 99;
    const floor = this.floorUnder(event);
    if (moved < 5 && floor) this.onFloorClick?.(floor);
  }

  // ---- interior scan ---------------------------------------------------------
  async showScan(assets, floor) {
    const scan = await loadScanModel(assets);
    this.hideScan();
    const e = this.extent;
    const c = this.building.centre;
    const toCamera = new THREE.Vector3().subVectors(this.camera.position, this.controls.target).setY(0).normalize();
    const right = new THREE.Vector3(-toCamera.z, 0, toCamera.x);
    const scale = Math.min(8, Math.max(0.4, (e * 0.2) / scan.footprint));
    const fromHeight = floor ? this.building.floorMid(floor) : this.building.height() / 2;
    const y = Math.max(fromHeight, e * 0.1);

    scan.model.scale.setScalar(scale);
    scan.model.position.copy(c).addScaledVector(right, e * 0.19).setY(y);
    scan.model.rotation.y = Math.atan2(toCamera.x, toCamera.z);
    const link = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(c.x, fromHeight, c.z), scan.model.position.clone()]),
      new THREE.LineBasicMaterial({ color: 0x6a3fc0 }),
    );
    this.overlay.add(scan.model, link);
    this.scan = { ...scan, link, opened: performance.now(), cut: scan.cutRange.initial };

    const target = scan.model.position.clone();
    this.flyTo({ position: target.clone().addScaledVector(toCamera, e * 0.25).add(new THREE.Vector3(0, e * 0.2, 0)), target }, 1300);
    return scan.cutRange;
  }

  setScanCut(height) { if (this.scan) this.scan.cut = height; }

  hideScan() {
    if (!this.scan) return;
    this.overlay.remove(this.scan.model, this.scan.link);
    this.scan.dispose();
    this.scan = null;
  }

  // ---- frame loop ------------------------------------------------------------
  resize() {
    const { clientWidth: width, clientHeight: height } = this.canvas.parentElement;
    if (!width || !height) return;
    this.rect = this.canvas.getBoundingClientRect();
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  stepReveal(now) {
    const t = clamp01((now - this.reveal.start) / (REVEAL_SECONDS * 1000));
    const move = easeInOut(clamp01((t - 0.08) / 0.8));
    // tilts down from overhead; a flight the user starts meanwhile takes the camera, and the reveal keeps only the growth
    if (!this.flight) orbitLerp(this.camera, this.controls, this.reveal.from, this.reveal.to, move);
    this.plate.uniforms.uGrow.value = easeInOut(clamp01((t - 0.1) / 0.45));     // the neighbours rise
    this.building.setBuilt(clamp01((t - 0.5) / 0.45));
    if (t >= 1) {
      this.reveal = null;
      this.controls.enabled = true;
      this.lastInput = performance.now();        // the idle drift waits from when the camera lands, not from load
    }
  }

  // After a while without input the camera drifts slowly round the building, easing in; any input stops it at once.
  stepDrift(now) {
    const idle = !this.reveal && !this.flight && !this.scan && !reducedMotion() && now - this.lastInput > IDLE_MS;
    this.drift += ((idle ? DRIFT_SPEED : 0) - this.drift) * (idle ? 0.01 : 0.2);
    this.controls.autoRotate = this.drift > 0.002;
    this.controls.autoRotateSpeed = this.drift;
  }

  frame(now) {
    if (!this.running) return;
    requestAnimationFrame(this.frame);
    if (!this.plate) return;

    if (this.reveal) this.stepReveal(now);
    if (this.flight) {
      const f = this.flight;
      const t = clamp01((now - f.start) / f.milliseconds);
      orbitLerp(this.camera, this.controls, f.from, f.destination(), easeInOut(t));
      if (t >= 1) { this.flight = null; f.done(); }
    }
    this.stepDrift(now);
    if (!this.reveal) this.controls.update();
    if (this.plate.uniforms.uTime) this.plate.uniforms.uTime.value = now / 1000;   // drifting cloud shadows

    const dimTarget = this.scan ? 1 : 0;
    const dim = this.plate.uniforms.uDim;
    dim.value += (dimTarget - dim.value) * 0.1;
    this.building.dim.value = dim.value;
    if (this.terrain) {
      const t = this.terrain.uniforms;
      t.uHeightMode.value += ((this.layers.heights ? 1 : 0) - t.uHeightMode.value) * 0.12;
      t.uDim.value = dim.value;
    }
    this.footprints.scale.y = Math.max(this.plate.uniforms.uGrow.value, 0.001);
    this.building.update();

    if (this.scan) {
      const opening = clamp01((now - this.scan.opened) / 1200);
      const { min } = this.scan.cutRange;
      this.scan.setCut(min + (this.scan.cut - min) * easeInOut(opening));
    }

    this.hoverStep();
    this.updatePins();
    this.renderer.clear();
    this.renderer.render(this.scene, this.camera);
    this.renderer.clearDepth();
    this.renderer.render(this.overlay, this.camera);
  }

  dispose() {
    this.running = false;
    this.resizeObserver.disconnect();
    this.hideScan();
    removeEventListener('keydown', this.onInput);
    this.flight?.done?.();
    this.terrain?.dispose();
    this.trees?.dispose();
    this.plate?.dispose();
    this.blocks?.dispose();
    this.building?.dispose();
    this.controls.dispose();
    this.renderer.dispose();
    this.labelLayer.replaceChildren();
  }
}
