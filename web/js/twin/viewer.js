// Owns the three.js scene for one property: city terrain, the building's floors, and an optional interior scan.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createTerrain, createFootprints } from './terrain.js';
import { createBuilding } from './building.js';
import { loadScanModel } from './scan.js';

const SKY = '#dfe7ee';
const REVEAL_SECONDS = 3.2;
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const clamp01 = (t) => Math.min(1, Math.max(0, t));
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

export class Viewer {
  constructor({ canvas, labelLayer, onFloorHover, onFloorClick }) {
    this.canvas = canvas;
    this.labelLayer = labelLayer;
    this.onFloorHover = onFloorHover;
    this.onFloorClick = onFloorClick;

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.autoClear = false;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(SKY);
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

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas.parentElement);
    canvas.addEventListener('pointermove', (e) => this.handlePointerMove(e));
    canvas.addEventListener('pointerleave', () => this.setHover(0));
    canvas.addEventListener('pointerdown', (e) => { this.pressAt = [e.clientX, e.clientY]; });
    canvas.addEventListener('pointerup', (e) => this.handlePointerUp(e));

    this.running = true;
    this.frame = this.frame.bind(this);
    requestAnimationFrame(this.frame);
  }

  // ---- loading -------------------------------------------------------------
  async load(twin) {
    const heights = new Float32Array(await (await fetch(twin.heights)).arrayBuffer());
    this.extent = twin.extent;
    this.terrain = createTerrain({
      extent: twin.extent, grid: twin.grid, heights, orthoUrl: twin.ortho, sky: SKY,
      anisotropy: this.renderer.capabilities.getMaxAnisotropy(),
    });
    this.footprints = createFootprints(twin.neighbours);
    this.building = createBuilding(twin.building);
    this.scene.add(this.terrain.mesh, this.footprints, this.building.group);

    this.controls.minDistance = twin.extent * 0.04;
    this.controls.maxDistance = twin.extent * 3;
    this.view = 'model';

    if (reducedMotion()) {
      this.terrain.uniforms.uGrow.value = 1;
      this.building.setBuilt(1);
      this.placeCamera(this.cameraFor('model'));
    } else {
      this.controls.enabled = false;
      this.reveal = { start: performance.now(), from: this.cameraFor('plan'), to: this.cameraFor('model') };
    }
    this.resize();
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

  flyTo(destination, milliseconds = 1100) {
    if (reducedMotion()) return this.placeCamera(destination);
    this.flight = {
      start: performance.now(), milliseconds,
      fromPosition: this.camera.position.clone(), fromTarget: this.controls.target.clone(), ...destination,
    };
  }

  setView(view) {
    this.view = view;
    this.building.setSpread(view === 'stacked' ? 2.4 : 1);
    this.building.setShell(view === 'model' ? 0.16 : 0);
    this.flyTo(this.cameraFor(view));
  }

  setLayer(name, on) {
    this.layers[name] = on;
    if (name === 'footprints') this.footprints.visible = on;
  }

  // ---- floors --------------------------------------------------------------
  paint(describe) { this.building?.paint(describe); }

  setPins(pins) {
    this.labelLayer.replaceChildren();
    this.pins = pins.map((pin) => {
      const el = document.createElement(pin.onClick ? 'button' : 'div');
      el.className = `pin${pin.onClick ? '' : ' is-height'}`;
      el.textContent = pin.label;
      if (pin.onClick) { el.type = 'button'; el.addEventListener('click', pin.onClick); }
      this.labelLayer.append(el);
      return { ...pin, el };
    });
  }

  updatePins() {
    const visible = !this.reveal && !this.scan;
    const rect = this.canvas.getBoundingClientRect();
    const anchor = new THREE.Vector3();
    for (const pin of this.pins) {
      const y = pin.floor ? this.building.floorMid(pin.floor) : this.building.height() + this.extent * 0.01;
      anchor.set(this.building.eastEdge, y, this.building.centre.z).project(this.camera);
      const shown = visible && anchor.z < 1;
      pin.el.hidden = !shown;
      pin.el.style.left = `${(anchor.x * 0.5 + 0.5) * rect.width}px`;
      pin.el.style.top = `${(-anchor.y * 0.5 + 0.5) * rect.height}px`;
    }
  }

  floorUnder(event) {
    if (!this.building || this.reveal) return 0;
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = this.raycaster.intersectObjects(this.building.slabs, false)[0];
    return hit ? hit.object.userData.floor : 0;
  }

  setHover(floor, event) {
    if (floor === this.hoveredFloor && !floor) return;
    this.hoveredFloor = floor;
    this.canvas.style.cursor = floor ? 'pointer' : 'grab';
    this.onFloorHover?.(floor, event);
  }

  handlePointerMove(event) { this.setHover(this.floorUnder(event), event); }

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
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  stepReveal(now) {
    const t = clamp01((now - this.reveal.start) / (REVEAL_SECONDS * 1000));
    const move = easeInOut(clamp01((t - 0.08) / 0.8));
    this.camera.position.lerpVectors(this.reveal.from.position, this.reveal.to.position, move);
    this.controls.target.lerpVectors(this.reveal.from.target, this.reveal.to.target, move);
    this.camera.lookAt(this.controls.target);
    this.terrain.uniforms.uGrow.value = easeInOut(clamp01((t - 0.1) / 0.45));
    this.building.setBuilt(clamp01((t - 0.5) / 0.45));
    if (t >= 1) {
      this.reveal = null;
      this.controls.enabled = true;
    }
  }

  frame(now) {
    if (!this.running) return;
    requestAnimationFrame(this.frame);
    if (!this.terrain) return;

    if (this.reveal) this.stepReveal(now);
    if (this.flight) {
      const t = clamp01((now - this.flight.start) / this.flight.milliseconds);
      this.camera.position.lerpVectors(this.flight.fromPosition, this.flight.position, easeInOut(t));
      this.controls.target.lerpVectors(this.flight.fromTarget, this.flight.target, easeInOut(t));
      if (t >= 1) this.flight = null;
    }
    if (!this.reveal) this.controls.update();

    const u = this.terrain.uniforms;
    u.uHeightMode.value += ((this.layers.heights ? 1 : 0) - u.uHeightMode.value) * 0.12;
    u.uDim.value += ((this.scan ? 1 : 0) - u.uDim.value) * 0.1;
    this.footprints.scale.y = Math.max(u.uGrow.value, 0.001);
    this.building.update();

    if (this.scan) {
      const opening = clamp01((now - this.scan.opened) / 1200);
      const { min } = this.scan.cutRange;
      this.scan.setCut(min + (this.scan.cut - min) * easeInOut(opening));
    }

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
    this.terrain?.dispose();
    this.building?.dispose();
    this.controls.dispose();
    this.renderer.dispose();
    this.labelLayer.replaceChildren();
  }
}
