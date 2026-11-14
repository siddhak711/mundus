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

  const map = new THREE.TextureLoader().load(orthoUrl);
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
