// Realistic facades for every building in the 3-D view: one GLSL chunk shared by the neighbouring blocks (terrain.js)
// and the subject tower's floors (building.js), so the tower always matches its street.
//
// Nothing here is data: the walls are drawn plausibly for the building's height (LA stucco low-rise, precast mid-rise,
// glass towers), varied by a stable per-building seed. Roofs stay the real aerial photo; every number shown elsewhere
// stays real.

/** Shared uniforms the chunk reads. uTime drifts the cloud shadows (0 is fine: still clouds). */
export const ATMOSPHERE_UNIFORMS = ['uTime'];

export const FACADE_GLSL = /* glsl */ `
  uniform float uTime;

  const vec3 SUN = vec3(0.4472, 0.7155, 0.5367);           // normalize(0.5, 0.8, 0.6): late-morning sun from the south-east
  const vec3 HORIZON = vec3(0.914, 0.945, 0.969);           // #e9f1f7, the bottom of the CSS sky
  const vec3 ZENITH = vec3(0.42, 0.62, 0.86);

  float fHash(float n) { return fract(sin(n * 127.1) * 43758.5453); }
  float fHash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

  // value noise, for the slow cloud shadows
  float fNoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(fHash2(i), fHash2(i + vec2(1.0, 0.0)), f.x), mix(fHash2(i + vec2(0.0, 1.0)), fHash2(i + vec2(1.0, 1.0)), f.x), f.y);
  }

  // 1 inside [start, start + width) of every period, anti-aliased by the pixel footprint of x
  float fBand(float x, float period, float start, float width) {
    float f = mod(x, period);
    float w = fwidth(x) * 0.75 + 1e-4;
    return smoothstep(start - w, start + w, f) - smoothstep(start + width - w, start + width + w, f);
  }

  // the sky a window reflects, by the reflected ray's height
  vec3 fSky(vec3 r) {
    float y = r.y + 0.28;                       // seen from above, vertical glass mostly catches the street and facades opposite
    vec3 sky = mix(HORIZON, ZENITH, pow(clamp(y, 0.0, 1.0), 0.7));
    vec3 street = mix(vec3(0.66, 0.68, 0.69), vec3(0.48, 0.50, 0.50), clamp(-y * 2.0, 0.0, 1.0));
    return mix(street, sky, smoothstep(-0.18, 0.18, y));       // a soft horizon, so no line runs across the glass
  }

  // sun and sky light on a wall or roof: compass shading, darker where walls meet the street, sky-tinted high up
  vec3 fLight(vec3 color, vec3 n, float up, float height) {
    float sun = 0.66 + 0.34 * max(dot(n, SUN), 0.0);
    float ao = 0.80 + 0.20 * smoothstep(0.0, 5.0, up);
    vec3 sky = vec3(0.025, 0.035, 0.055) * smoothstep(0.0, max(height, 1.0), up);
    return color * sun * ao + sky;
  }

  // glass: dark body, sky reflection by view angle, a touch brighter higher up the building
  vec3 fGlass(vec3 tint, vec3 n, vec3 world, float up, float height) {
    vec3 view = normalize(cameraPosition - world);
    float fres = 0.18 + 0.82 * pow(1.0 - clamp(dot(n, view), 0.0, 1.0), 4.0);
    vec3 refl = fSky(reflect(-view, n));
    float high = smoothstep(0.0, max(height, 1.0), up);
    return mix(tint * (0.72 + 0.30 * high) + 0.02, refl, clamp(0.32 + 0.45 * fres + 0.08 * high, 0.0, 0.88));
  }

  // The wall at one point. along: metres along the wall, up: metres above the street, height: the building's height,
  // seed: 0..1 per building, storey: storey height in metres (0 = by style).
  // Each style builds the detailed pattern and its own average (the same glass and wall, mixed by how much of the wall
  // is glass); far away the pattern fades into that average, lit the same way, so there is no seam and no shimmer.
  vec3 facade(vec3 n, vec3 world, float along, float up, float height, float seed, float storey) {
    float px = max(fwidth(along), fwidth(up));
    float detail = 1.0 - smoothstep(0.22, 0.9, px);
    float pick = fHash(seed * 91.7);
    vec3 c, far;
    float glassy;                                                        // how much the sun matters less (reflective wall)

    if (height < 15.0) {
      // LA low-rise: stucco with punched windows, white frames and sills; some ground-floor shopfronts
      vec3 stucco = pick < 0.25 ? vec3(0.93, 0.89, 0.80) : pick < 0.5 ? vec3(0.95, 0.95, 0.93)
                  : pick < 0.75 ? vec3(0.86, 0.80, 0.69) : vec3(0.89, 0.76, 0.66);
      vec3 wall = stucco * (0.96 + 0.08 * fHash(seed * 13.1));
      float st = storey > 0.0 ? storey : 3.0;
      float bay = 3.0 + 1.4 * fHash(seed * 7.3);
      float winW = 1.2 + 0.5 * fHash(seed * 3.9), winH = 1.45;
      float a = along + seed * 17.0;
      float inWin = fBand(a, bay, (bay - winW) * 0.5, winW) * fBand(up, st, 0.95, winH);
      float frameMask = fBand(a, bay, (bay - winW) * 0.5 - 0.08, winW + 0.16) * fBand(up, st, 0.87, winH + 0.16) - inWin;
      float sill = fBand(a, bay, (bay - winW) * 0.5 - 0.12, winW + 0.24) * fBand(up, st, 0.83, 0.06);
      float shop = step(0.6, fHash(seed * 5.1)) * (1.0 - step(st * 1.15, up)) * step(0.35, up);
      vec3 g = fGlass(vec3(0.10, 0.13, 0.16), n, world, up, height);
      c = mix(wall, vec3(0.97), clamp(frameMask + sill, 0.0, 1.0) * 0.8);
      c = mix(c, g, max(inWin, shop * fBand(along, 6.0, 0.25, 5.5)));
      far = mix(wall, g, 0.18 + 0.6 * shop);
      glassy = 0.0;
    } else if (height < 40.0) {
      // mid-rise: precast or concrete with continuous window bands and mullions, a storefront at street level
      vec3 wall = pick < 0.33 ? vec3(0.80, 0.79, 0.76) : pick < 0.66 ? vec3(0.73, 0.73, 0.71) : vec3(0.84, 0.79, 0.70);
      vec3 glassTint = pick < 0.5 ? vec3(0.16, 0.22, 0.28) : vec3(0.20, 0.23, 0.22);
      float st = storey > 0.0 ? storey : 3.7;
      float ground = 4.6;
      float band = fBand(max(up - ground, 0.0), st, 1.0, 1.75) * step(ground, up);
      float mull = fBand(along, 1.6, 0.0, 0.09);
      vec3 g = fGlass(glassTint, n, world, up, height);
      c = mix(wall, g, band);
      c = mix(c, wall * 0.78, band * mull);
      float shop = (1.0 - step(ground - 0.5, up)) * step(0.3, up);
      vec3 sg = fGlass(vec3(0.06, 0.08, 0.10), n, world, up, height);
      c = mix(c, sg, shop * (1.0 - fBand(along, 4.5, 0.0, 0.25)));
      far = mix(mix(wall, g, 0.45), sg, shop * 0.9);
      glassy = 0.2;
    } else {
      // tower: glass curtain wall, a spandrel at each floor slab, mullions, a glazed lobby
      vec3 glassTint = pick < 0.3 ? vec3(0.22, 0.33, 0.45) : pick < 0.55 ? vec3(0.24, 0.36, 0.36)
                     : pick < 0.75 ? vec3(0.32, 0.30, 0.27) : vec3(0.36, 0.42, 0.50);
      vec3 spandrel = pick < 0.5 ? vec3(0.76, 0.77, 0.78) : vec3(0.62, 0.64, 0.66);
      float st = storey > 0.0 ? storey : 3.6;
      float ground = max(st * 1.25, 5.0);
      float sp = fBand(up - ground, st, 0.0, 0.85) * step(ground, up);
      float mull = fBand(along, 1.5, 0.0, 0.07);
      vec3 g = fGlass(glassTint, n, world, up, height);
      c = mix(g, spandrel, sp);
      c = mix(c, spandrel * 0.85, mull * (1.0 - sp) * 0.9);
      float lobby = 1.0 - step(ground, up);
      vec3 lg = mix(fGlass(vec3(0.05, 0.07, 0.09), n, world, up, height), vec3(0.78), fBand(along, 3.0, 0.0, 0.3));
      c = mix(c, lg, lobby);
      far = mix(mix(g, spandrel, 0.85 / st + 0.04), lg, lobby);
      glassy = 0.55;
    }
    // parapet coping along the roof edge
    float coping = smoothstep(height - 0.55, height - 0.45, up);
    c = mix(c, vec3(0.86, 0.86, 0.84), coping);
    far = mix(far, vec3(0.86, 0.86, 0.84), coping);
    vec3 base = mix(far, c, detail);
    // glass is mostly reflection: the sun and the street-level shading matter less on it
    return mix(fLight(base, n, up, height), base * 0.95 + vec3(0.015), glassy * 0.6);
  }

  // slow drifting cloud shadows, very soft
  float cloudShade(vec3 world) {
    vec2 p = world.xz * 0.0028 + vec2(uTime * 0.006, uTime * 0.0035);
    float c = fNoise(p) * 0.65 + fNoise(p * 2.3 + 7.1) * 0.35;
    return 1.0 - 0.10 * smoothstep(0.55, 0.8, c);
  }

  // distance haze toward the horizon colour
  vec3 atmosphere(vec3 color, vec3 world) {
    color *= cloudShade(world);
    float d = length(world - cameraPosition);
    float f = 1.0 - exp(-d * 0.00042);
    return mix(color, HORIZON, f * 0.55);
  }
`;
