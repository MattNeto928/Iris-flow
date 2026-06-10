---
name: remotion-segments
description: Generates React-based programmatic videos using Remotion
---

# Remotion Segment Generation

Remotion segments generate programmatic video components using React.js and TypeScript. The output must be valid React code representing a Remotion "component" that will be dynamically imported and rendered into an MP4 video at 1080x1920 (9:16 vertical) resolution at 30 FPS.

Every component must be sleek, cinematic, and deterministic.

## Component Structure

Your generated code will be injected into a file named `Scene.tsx`. It MUST export a default React component taking no props. Do NOT render a `<Composition>`, just the component itself.

```tsx
import React from 'react';
import { useCurrentFrame, useVideoConfig, AbsoluteFill, interpolate, spring } from 'remotion';

export default function Scene() {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();

  // Your animation logic...

  return (
    <AbsoluteFill style={{ backgroundColor: '#0D0D0D' }}>
      {/* Visuals */}
    </AbsoluteFill>
  );
}
```

## Coordinate System & Styling

The composition is statically configured for `width: 1080` and `height: 1920`.
- Use standard CSS, flexbox, and grid for layout inside standard `<div>` or `AbsoluteFill` tags.
- Safe zone for text/labels is roughly avoiding the outer 50px edges.

### Aesthetic Standards
- Use vibrant colors but avoid harsh pure `#FFFFFF` against `#000000`. Use deep blacks (`#0D0D0D`, `#121212`) and soft whites/greys.
- Add fluid motion for all entrances/exits.
- **The screen must NEVER be static for more than 15 frames (~500ms).** There must always be SOMETHING breathing — a subtle scale drift, a slow rotation, a particle field, a pulsing glow, a drifting gradient. Static screens read as "cheap AI output." Real motion graphics are always alive.
- **Anticipation → Action → Settle** — every key element should wind up before moving, move sharply, then settle with a tiny overshoot. Linear in-out is the single biggest tell of AI animation.
- **Depth via parallax** — when animating 2D elements, give background, midground, and foreground layers different motion speeds. Background drifts slowly, foreground reacts fast. This is how you get "Veritasium Shorts" look for free.
- **Avoid generic title-card layouts.** A centered headline on a flat background is a dead animation. Headlines must be kinetic — stagger per character, pair with a morphing shape, or land with a camera push-in.

## Animation Principles

### Interpolation

Use `interpolate` to map the current frame number to a visual property over time.

```tsx
const opacity = interpolate(frame, [0, 30], [0, 1], {
  extrapolateLeft: 'clamp',
  extrapolateRight: 'clamp',
});

const scale = interpolate(frame, [0, 30], [0.8, 1], {
  extrapolateLeft: 'clamp',
  extrapolateRight: 'clamp',
});

return <h1 style={{ opacity, transform: `scale(${scale})` }}>Hello</h1>;
```

**CRITICAL**: ALWAYS use `, { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }` otherwise animations will break when frames exceed the input range.

### Spring Physics

For organic, bouncy entrances, use `spring`.

```tsx
const entranceScale = spring({
  fps,
  frame,
  config: { damping: 200 },
});

// Staggered spring (wait 15 frames)
const textScale = spring({
  fps,
  frame: frame - 15, 
  config: { damping: 200 },
});
```

### Sequencing & Progress

Use `Sequence` to easily delay components without tracking math.
```tsx
import { Sequence } from 'remotion';

export default function Scene() {
  return (
    <AbsoluteFill>
      <Sequence from={0} durationInFrames={60}>
        <Title /> // Frame 0 becomes frame 0 inside Title
      </Sequence>
      <Sequence from={30}>
        <Subtitle /> // Sequence starts halfway through
      </Sequence>
    </AbsoluteFill>
  );
}
```

### Kinetic Typography (preferred over static titles)

Stagger-reveal per word or per character. This is the single highest-leverage pattern for "premium" feel vs. AI output.

```tsx
// Per-word stagger with spring
const words = "Your brain is lying".split(" ");
return (
  <div style={{ display: "flex", gap: 18, justifyContent: "center" }}>
    {words.map((word, i) => {
      const enter = spring({ fps, frame: frame - i * 6, config: { damping: 14, mass: 0.6 } });
      const opacity = interpolate(enter, [0, 1], [0, 1]);
      const y = interpolate(enter, [0, 1], [40, 0]);
      const blur = interpolate(enter, [0, 1], [12, 0]);
      return (
        <span
          key={i}
          style={{
            opacity,
            transform: `translateY(${y}px)`,
            filter: `blur(${blur}px)`,
            fontSize: 92,
            fontWeight: 900,
            color: "#F5F5F5",
            letterSpacing: -2,
          }}
        >
          {word}
        </span>
      );
    })}
  </div>
);
```

Variations: swap `translateY` for `scale(0.6 → 1)`, add a single highlighted word in `#4FC3F7`, or chain a second stagger that exits before the third word arrives (overlapping reveal).

### Ambient Breathing Layers (the "alive" trick)

Every scene should have at least one passive ambient element that moves independently of the main animation. This is what separates "motion graphics" from "PowerPoint":

```tsx
// Drifting dot field — use random(seed) for determinism
const DOTS = 60;
const dots = Array.from({ length: DOTS }, (_, i) => ({
  x: random(`x-${i}`) * 1080,
  y0: random(`y-${i}`) * 1920,
  size: 2 + random(`s-${i}`) * 4,
  phase: random(`p-${i}`) * Math.PI * 2,
}));

return (
  <AbsoluteFill style={{ background: "radial-gradient(circle at 50% 40%, #1A1A2E, #0D0D0D)" }}>
    {dots.map((d, i) => {
      const y = d.y0 + Math.sin(frame / 30 + d.phase) * 20;
      const opacity = 0.2 + Math.sin(frame / 20 + d.phase) * 0.15;
      return (
        <div key={i} style={{
          position: "absolute", left: d.x, top: y,
          width: d.size, height: d.size, borderRadius: "50%",
          background: "#4FC3F7", opacity, filter: "blur(0.5px)",
        }} />
      );
    })}
    {/* main content on top */}
  </AbsoluteFill>
);
```

Other ambient options: slow-drifting radial gradient, SVG grid with subtle pulse, scan lines at low alpha, flicker layer.

### Cinematic Camera Moves (2D equivalents)

These replicate filmic techniques using pure CSS transforms on a container:

```tsx
// Slow push-in (Ken Burns) — applies to whole scene
const scale = interpolate(frame, [0, durationInFrames], [1.0, 1.08], {
  extrapolateLeft: "clamp", extrapolateRight: "clamp",
});
const offsetY = interpolate(frame, [0, durationInFrames], [0, -30], {
  extrapolateLeft: "clamp", extrapolateRight: "clamp",
});
<AbsoluteFill style={{ transform: `scale(${scale}) translateY(${offsetY}px)` }}>
  {/* scene */}
</AbsoluteFill>

// Rack-focus via blur (simulate focal shift between layers)
const fgBlur = interpolate(frame, [60, 90], [8, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
const bgBlur = interpolate(frame, [60, 90], [0, 8], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

// Whip-pan on the hook (fast, short — don't overuse)
const panX = interpolate(frame, [0, 8], [-400, 0], {
  easing: Easing.out(Easing.cubic),
  extrapolateLeft: "clamp", extrapolateRight: "clamp",
});
```

### Easing — prefer `Easing` over linear

```tsx
import { Easing } from 'remotion';

interpolate(frame, [0, 30], [0, 1], {
  easing: Easing.out(Easing.cubic),   // settle naturally
  extrapolateLeft: "clamp", extrapolateRight: "clamp",
});
// Preferred: Easing.out(Easing.cubic), Easing.inOut(Easing.cubic), Easing.out(Easing.back(1.5))
// AVOID: Easing.linear — looks synthetic. Use only for continuous rotation/drift.
```

### Motion Principles (from Disney's 12, adapted for data viz)

1. **Anticipation** — an element should recoil briefly before moving toward its target (e.g., scale to 0.95 before springing to 1.0).
2. **Overshoot** — springs should end with a small bounce past the target. Use `config: { damping: 10, mass: 1 }` for bouncy, `{ damping: 30 }` for crisp.
3. **Follow-through** — when a big element moves, smaller elements should react after it (cause-and-effect chain via staggered `frame - offset`).
4. **Staggering** — never animate N things simultaneously. Always stagger by 3-6 frames each.
5. **Arcs** — motion in a straight line looks computer-generated. Add slight curvature via two-axis interpolation (e.g., translateX + translateY with different bezier easings).

## Determinism Rule
Remotion NEVER allows `Math.random()`. If randomness is needed, use `random(seed)`.
```tsx
import { random } from 'remotion';

const rx = random('x-position') * width;
```

## 3D Rendering with Three.js

Use `@remotion/three` + `@react-three/fiber` for cinematic 3D scenes. This is ideal for molecular structures, orbiting objects, data geometry, abstract forms.

### Setup

```tsx
import { ThreeCanvas } from '@remotion/three';
import { useCurrentFrame, useVideoConfig } from 'remotion';

export default function Scene() {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  return (
    <AbsoluteFill style={{ backgroundColor: '#0D0D0D' }}>
      <ThreeCanvas width={width} height={height}>
        <ambientLight intensity={0.4} />
        <directionalLight position={[5, 5, 5]} intensity={0.8} />
        <pointLight position={[-5, -5, 5]} intensity={0.4} color="#4FC3F7" />
        {/* 3D meshes here */}
      </ThreeCanvas>
    </AbsoluteFill>
  );
}
```

### Rules

- **MUST** wrap all 3D content in `<ThreeCanvas width={width} height={height}>`.
- **NEVER** use `useFrame()` from `@react-three/fiber` — it does not fire during rendering.
- **ALL** animations must be driven by `useCurrentFrame()` mapped to mesh props.
- Any `<Sequence>` inside `<ThreeCanvas>` **MUST** have `layout="none"`.
- Always include lighting: at minimum `ambientLight` + `directionalLight`.

### Camera Animation (CRITICAL — read before writing any 3D scene)

The `camera` prop on `<ThreeCanvas>` is a **constructor config** — R3F uses it once on mount and ignores updates. **Passing dynamic frame-derived values to it causes jitter, glitching, or silent no-ops.**

**WRONG — causes camera jitter/glitch:**
```tsx
// NEVER do this — camera prop is not reactive
const camZ = interpolate(frame, [0, 60], [10, 6], { extrapolateRight: 'clamp' });
<ThreeCanvas width={width} height={height} camera={{ position: [0, 2, camZ], fov: 55 }}>
```

**CORRECT — use `PerspectiveCamera` from `@react-three/drei` inside the canvas:**
```tsx
import { PerspectiveCamera } from '@react-three/drei';

// Keep ThreeCanvas camera prop STATIC (fov/near/far only, no position)
<ThreeCanvas width={width} height={height} camera={{ fov: 55, near: 0.1, far: 200 }}>
  {/* Animate position here, inside the canvas tree */}
  <PerspectiveCamera makeDefault fov={55} near={0.1} far={200} position={[0, camY, camZ]} />
  <ambientLight intensity={0.4} />
  {/* rest of scene */}
</ThreeCanvas>
```

`makeDefault` registers it as the active camera. Its `position` prop re-renders declaratively with every `useCurrentFrame()` change — exactly what Remotion needs.

**Alternative (no extra package) — imperative `CameraController`:**
```tsx
import { useThree } from '@react-three/fiber';

function CameraController({ frame }: { frame: number }) {
  const { camera } = useThree();
  const camZ = interpolate(frame, [0, 60], [10, 6], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const camY = interpolate(frame, [0, 60], [4, 3], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  camera.position.set(0, camY, camZ);
  camera.lookAt(0, 0, 0);
  (camera as any).updateProjectionMatrix();
  return null;
}

// Inside ThreeCanvas — keep camera prop static:
<ThreeCanvas width={width} height={height} camera={{ fov: 55, near: 0.1, far: 200 }}>
  <CameraController frame={frame} />
  {/* scene objects */}
</ThreeCanvas>
```

**Prefer `PerspectiveCamera` from drei** — it is declarative and avoids type casting. Use `CameraController` only if drei is unavailable.

### Mesh Animation Pattern

```tsx
const frame = useCurrentFrame();
const rotationY = interpolate(frame, [0, durationInFrames], [0, Math.PI * 4], {
  extrapolateLeft: 'clamp',
  extrapolateRight: 'clamp',
});

<mesh rotation={[0.3, rotationY, 0]}>
  <icosahedronGeometry args={[1.5, 2]} />
  <meshStandardMaterial color="#4FC3F7" wireframe={false} metalness={0.6} roughness={0.2} />
</mesh>
```

### 3D + 2D Layering

Overlay HTML elements on top of `<ThreeCanvas>` using `AbsoluteFill` with `pointerEvents: 'none'`:

```tsx
<AbsoluteFill>
  <ThreeCanvas width={width} height={height}>
    {/* 3D content */}
  </ThreeCanvas>
  <AbsoluteFill style={{ pointerEvents: 'none' }}>
    <div style={{ position: 'absolute', bottom: 200, left: 60 }}>
      <h1 style={{ color: '#4FC3F7', fontSize: 64 }}>Label</h1>
    </div>
  </AbsoluteFill>
</AbsoluteFill>
```

### Material Palette (dark aesthetic)

- Electric blue: `#4FC3F7` — emissive accent, point lights
- Gold: `#FFD54F` — highlight meshes
- Coral: `#FF7043` — warning/heat
- Deep grey: `#1A1A2E` — background planes

### Lighting that Reads Cinematic

```tsx
<ambientLight intensity={0.25} />
<directionalLight position={[5, 5, 5]} intensity={0.7} color="#F5F5F5" />
<pointLight position={[-3, 2, 4]} intensity={0.8} color="#4FC3F7" />
<pointLight position={[4, -2, 2]} intensity={0.4} color="#FF7043" />
<fog attach="fog" args={["#0D0D0D", 8, 20]} />
```

Always add one "key" directional light (bright, white), one "rim" point light in accent color, and a subtle fog. Flat single-light scenes read as amateur.

### Post-processing (optional but huge lift)

```tsx
import { EffectComposer, Bloom, ChromaticAberration } from '@react-three/postprocessing';

<EffectComposer>
  <Bloom intensity={0.6} luminanceThreshold={0.6} luminanceSmoothing={0.2} />
  <ChromaticAberration offset={[0.0015, 0.0015]} />
</EffectComposer>
```

Bloom on bright meshes + subtle chromatic aberration is the "expensive" look. Don't go overboard — `intensity={0.6}` and offset under 0.002 or it looks like a vaporwave meme.

## Scene Composition Recipe (use one of these as a skeleton)

Every strong Remotion scene follows one of a handful of shapes. Pick one before writing code:

1. **Hero-object orbit** — single 3D mesh, camera orbits ~30° over the clip, labels fade in. Best for molecules, orbitals, concepts as "things."

2. **Reveal-by-decomposition** — start with the final composite, progressively peel it into components with staggered fade-in-from-sides. Best for equations, systems, anatomy.

3. **Parallax zoom** — 3 layered 2D scenes with different scale rates over time. Foreground grows fast, background grows slow. Best for scale/stakes reveals.

4. **Kinetic-typography reveal** — per-word stagger lands the line, then a visual element emerges behind/through the text. Best for one-sentence hooks.

5. **Data-vis morph** — chart A smoothly interpolates to chart B mid-clip. Best for "here's what happens when you change X."

6. **Particle assembly** — N dots scattered at t=0, converge into a shape by t=mid. Best for concepts that "click into place" (crystallization, neural pattern recognition).

## Critical Requirements
- Target Duration: {duration} seconds (converted dynamically via `durationInFrames`)
- Description: {description}
- **Generate ONLY the TypeScript React code.**
- The code must be self-contained in a single file default export.
- Do NOT include markdown blocks (` ```tsx `) in your final output, just raw code.
- Every scene MUST include at least one ambient-breathing layer (drifting particles, gradient pulse, etc.) even during "hold" beats.
- Every scene MUST use at least one easing function other than linear.
- Every scene MUST have staggered entrances — never fade in more than one major element at exactly the same frame.
