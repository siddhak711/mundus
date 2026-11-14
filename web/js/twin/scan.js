// A Matterport interior scan shown as a cut-open model beside the building.
import * as THREE from 'three';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';

const VERTEX = /* glsl */ `
  varying vec3 vModel;
  varying vec3 vWorld;
  void main() {
    vModel = position;
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }`;

// The mesh has no texture coordinates. Matterport's top-down photo plan covers the same
// footprint, so it is projected straight down onto floors and furniture; walls stay plain.
const FRAGMENT = /* glsl */ `
  uniform sampler2D uPlan;
  uniform vec4 uPlanRect;   // x, y, width, height in model metres
  uniform float uHasPlan;
  uniform float uCut;       // everything above this height is removed
  varying vec3 vModel;
  varying vec3 vWorld;
  void main() {
    if (vModel.z > uCut) discard;
    vec3 normal = normalize(cross(dFdx(vWorld), dFdy(vWorld)));
    float facingUp = smoothstep(0.55, 0.85, abs(normal.y));
    float light = 0.6 + 0.4 * clamp(dot(normal, normalize(vec3(0.4, 0.8, 0.3))) * 0.5 + 0.5, 0.0, 1.0);

    vec4 plan = texture2D(uPlan, (vModel.xy - uPlanRect.xy) / uPlanRect.zw);
    vec3 surface = mix(vec3(0.78, 0.80, 0.82), min(plan.rgb * 1.3, vec3(1.0)), plan.a * uHasPlan);
    vec3 wall = vec3(0.90, 0.91, 0.92);
    vec3 color = mix(wall, surface, facingUp) * light;
    if (!gl_FrontFacing) color *= 0.7;
    gl_FragColor = vec4(color, 1.0);
  }`;

const meshLoader = new OBJLoader();
const textureLoader = new THREE.TextureLoader();
const CUT_HEIGHT = 2.0; // metres above the scan's floor; clears doors, removes ceilings

export async function loadScanModel(assets) {
  const [object, plan] = await Promise.all([
    meshLoader.loadAsync(assets.mesh),
    assets.plan ? textureLoader.loadAsync(assets.plan) : null,
  ]);
  if (plan) {
    plan.colorSpace = THREE.SRGBColorSpace;
    plan.anisotropy = 8;
  }
  const rect = assets.planRect || { x: 0, y: 0, width: 1, height: 1 };
  const uniforms = {
    uPlan: { value: plan },
    uPlanRect: { value: new THREE.Vector4(rect.x, rect.y, rect.width, rect.height) },
    uHasPlan: { value: plan ? 1 : 0 },
    uCut: { value: 0 },
  };
  const material = new THREE.ShaderMaterial({ uniforms, vertexShader: VERTEX, fragmentShader: FRAGMENT, side: THREE.DoubleSide });

  // Matterport models are z-up; stand them upright for three.js (y-up).
  const upright = new THREE.Group();
  upright.rotation.x = -Math.PI / 2;
  let floorLevel = Infinity;
  let ceiling = -Infinity;
  object.traverse((child) => {
    if (!child.isMesh) return;
    child.geometry.computeBoundingBox();
    floorLevel = Math.min(floorLevel, child.geometry.boundingBox.min.z);
    ceiling = Math.max(ceiling, child.geometry.boundingBox.max.z);
    upright.add(new THREE.Mesh(child.geometry, material));
  });

  if (assets.capturePoints.length) {
    const positions = new THREE.Float32BufferAttribute(assets.capturePoints.flat(), 3);
    const points = new THREE.Points(
      new THREE.BufferGeometry().setAttribute('position', positions),
      new THREE.PointsMaterial({ color: 0x6a3fc0, size: 0.22, sizeAttenuation: true }),
    );
    upright.add(points);
  }

  const bounds = new THREE.Box3().setFromObject(upright);
  const size = bounds.getSize(new THREE.Vector3());
  const centre = bounds.getCenter(new THREE.Vector3());
  upright.position.set(-centre.x, -bounds.min.y, -centre.z);

  const model = new THREE.Group();
  model.add(upright);
  const base = new THREE.Mesh(
    new THREE.PlaneGeometry(size.x + 6, size.z + 6).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({ color: 0xffffff }),
  );
  base.position.y = -0.3;
  const frame = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(size.x + 6, 0.05, size.z + 6)),
    new THREE.LineBasicMaterial({ color: 0x6a3fc0 }),
  );
  frame.position.y = -0.28;
  model.add(base, frame);

  const defaultCut = Math.min(floorLevel + CUT_HEIGHT, ceiling);
  return {
    model,
    footprint: Math.max(size.x, size.z),
    cutRange: { min: floorLevel + 0.3, max: ceiling + 0.1, initial: defaultCut },
    setCut(height) { uniforms.uCut.value = height; },
    dispose() {
      material.dispose();
      plan?.dispose();
      upright.traverse((child) => child.geometry?.dispose());
    },
  };
}
