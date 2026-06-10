"""
PySim Service - Python scientific simulation generation.

Uses Claude to generate Python simulation scripts, then runs them to produce frames
and compiles to video. Ported from local pysim_service.
"""

import os
import uuid
import logging
import subprocess
import asyncio
from pathlib import Path

from src.services._llm import generate_text, strip_code_fences, build_narration_timeline, validate_script, prepare_retry_context

logger = logging.getLogger(__name__)

# Output directories
OUTPUT_DIR = Path("/app/output")
FRAMES_DIR = OUTPUT_DIR / "frames"
VIDEOS_DIR = OUTPUT_DIR / "videos"


PYSIM_PROMPT = """# Matplotlib Segment Generation

Generate a complete, self-contained Python script that produces exactly N = int(round(DURATION * 30)) frames
saved as frame_0000.png, frame_0001.png, etc. into OUTPUT_DIR (from environment variable).

## DEFAULT: 3D FIRST

**Always use mpl_toolkits.mplot3d when the topic has any spatial geometry.**
3D is the default. 2D is the exception (use only for 2D-native content like waveforms,
histograms, or 2D field maps where the third dimension adds nothing).

3D setup that MUST appear in every 3D script:
```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 — registers projection
import numpy as np
import os

BG = '#0D0D0D'; BLUE = '#4FC3F7'; GOLD = '#FFD54F'; CORAL = '#FF7043'
MINT = '#80CBC4'; LAVENDER = '#CE93D8'; WARM_WHITE = '#F5F5F5'; DIM = '#424242'

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/frames')
os.makedirs(OUTPUT_DIR, exist_ok=True)
DURATION = float(os.environ.get('DURATION', '8'))   # injected = the real voiceover length
FPS = 30
N_FRAMES = int(round(DURATION * FPS))

W, H = 1080, 1920

def ease(t):
    t = np.clip(t, 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * t)

def phase(t, start, end):
    if t <= start: return 0.0
    if t >= end: return 1.0
    return ease((t - start) / (end - start))

fig = plt.figure(figsize=(W/100, H/100), dpi=100, facecolor=BG)
ax = fig.add_subplot(111, projection='3d', facecolor=BG)
ax.set_axis_off()
ax.set_xlim(-2, 2); ax.set_ylim(-2, 2); ax.set_zlim(-2, 2)
ax.set_box_aspect((1, 1, 1.6))  # ALWAYS — keeps 3D box un-squashed in 9:16
```

Two rules that prevent the most common 3D failures:
1. `set_box_aspect((1, 1, 1.6))` — without this the 3D box looks crushed in portrait format
2. `ax.set_axis_off()` or set pane facecolors to `(0.05, 0.05, 0.05, 1)` — default grey panes look terrible on #0D0D0D

## COMPOSITION — FILL THE 9:16 FRAME (this is what makes it look impressive)

The single biggest "looks cheap" mistake is a tiny subject floating in a sea of black.
The subject must FILL most of the 1080x1920 canvas. Apply ALL of these:
- Remove figure padding so the axes use the whole canvas:
  `fig.subplots_adjust(left=0.0, right=1.0, bottom=0.0, top=1.0)`
- Set axis limits TIGHT around the actual data (the object should span ~80-90% of each
  axis range), not a generic [-2,2] if the object only reaches 1.4.
- Enlarge the 3D object in-frame. On matplotlib >= 3.6 use the zoom arg:
  `ax.set_box_aspect((1, 1, 1.6), zoom=1.35)` (zoom > 1 enlarges; this is the easiest big win).
  If unsure of the version, also pull the camera in with a lower `ax.dist` (e.g. `ax.dist = 7.5`,
  default is 10) — smaller = more zoomed.
- Use generous marker sizes and line widths (s=200-500 for focal bodies, lw=2.5-4) so the
  subject reads on a phone.
- Center the composition: the focal action should sit in the vertical middle of the frame,
  with the title near the top (y~0.93) — never leave the entire bottom third empty.
- **EXCEPTION for 3D MODELS (molecules, lattices, anything with spheres):** the 1.6
  z-stretch egg-shapes spheres. For ball-and-stick / lattice / sphere-based models use an
  EQUAL aspect instead — `ax.set_box_aspect((1, 1, 1), zoom=1.3)` — so spheres render round,
  and fill the vertical space with the title (top) and caption (bottom) rather than by
  stretching the geometry. Keep `(1, 1, 1.6)` only for scenes without spheres.

## FRAME COUNT IS NON-NEGOTIABLE

`DURATION` is injected via the environment and ALREADY equals this segment's length,
so `N_FRAMES = int(round(DURATION * FPS))` evaluates to exactly the required count.
Drive your frame loop with `for i in range(N_FRAMES):` and save one PNG per `i`.
NEVER hardcode a frame count, a different duration, or a fixed number of seconds —
if you do, the clip will be time-stretched to fit the audio and every motion (every
orbit, swing, and wave) will run at the wrong speed and look physically wrong.

# ==========================================================================
# PHYSICAL ACCURACY — READ THIS FIRST. The #1 complaint is "the physics looks off."
# ==========================================================================

The motion you draw must be the motion the equations actually produce. Wrong
integration is the usual culprit: naive (explicit/forward) Euler silently INJECTS
energy, so orbits spiral outward, pendulums swing wider every cycle, and springs
blow up. Use the right tool for each system:

PICK THE INTEGRATOR BY SYSTEM
- **Closed form when one exists — always prefer it.** It is exact, never drifts,
  and is the cheapest. Use it for:
    * Projectile / free fall:  x = x0 + vx*t ;  y = y0 + vy*t - 0.5*g*t**2
    * Simple harmonic motion:  x = A*cos(omega*t + phi),  omega = sqrt(k/m)
    * Small-angle pendulum:    theta = theta0*cos(sqrt(g/L)*t)
    * Uniform circular orbit:  ang = omega*t ; (r*cos(ang), r*sin(ang))
    * Constant-velocity / wave packets, Lissajous figures, etc.
- **Velocity Verlet** for orbits, oscillators, and any N-body / central-force
  problem where energy must be conserved so the path stays closed (no spiral):
    ```python
    a = accel(x)                       # acceleration from forces at current x
    for i in range(N_FRAMES):
        x = x + v*dt + 0.5*a*dt*dt     # position half-step uses old accel
        a_new = accel(x)
        v = v + 0.5*(a + a_new)*dt     # velocity uses average of old+new accel
        a = a_new
    ```
- **Semi-implicit (symplectic) Euler** — the robust default for damped/driven
  systems and constraints. Update velocity FIRST, then position with the NEW
  velocity (this is the only Euler that does not pump energy):
    ```python
    v = v + a*dt
    x = x + v*dt        # uses the just-updated v — NOT the old v
    ```
- **NEVER** use forward Euler (`x += v*dt; v += a*dt` in that order) for anything
  oscillatory or orbital. It is the classic "physics looks off" bug.

USE REAL CONSTANTS AND KEEP UNITS CONSISTENT
- g = 9.81 m/s^2 down. Coulomb/gravity go as 1/r^2. Springs: F = -k*x. Damping:
  F = -b*v. Pendulum period T = 2*pi*sqrt(L/g). Wave speed c relates lambda and f
  by c = lambda*f. You MAY rescale lengths/times for the camera, but the RATIOS
  and the functional form (1/r^2, cos, exp decay) must be physically correct.
- Conserve what should be conserved: in elastic collisions BOTH momentum and
  kinetic energy are conserved; for a 1-D elastic hit of equal masses the
  velocities simply swap. In inelastic collisions momentum is conserved, KE is not.
- Respect direction and sign: gravity pulls toward the mass, restoring forces
  oppose displacement, induced effects LAG the drive.

PHYSICAL-PLAUSIBILITY CHECKLIST (mentally verify before emitting code)
1. Does a bound orbit/oscillation return to where it started each period (closed,
   not spiraling)? If not, your integrator is leaking energy — switch to Verlet
   or closed form.
2. Is the speed believable — a dropped ball accelerates, a pendulum is fastest at
   the bottom and momentarily still at the extremes, a planet is fastest at
   perihelion?
3. Are amplitudes bounded (nothing flies off to infinity unless it physically
   should)? Clip only as a safety net, never to hide an unstable integrator.
4. Do timescales match the narration window — one full swing/orbit should take a
   sensible fraction of the segment, not blur past in 3 frames.

## The Artist Golden Rule

Build ALL artists ONCE before the frame loop. Update them inside the loop with set_* methods.
NEVER call ax.clear() inside the loop for non-surface content.

```python
# RIGHT — build once, update in loop
sc_electrons = ax.scatter(base[:, 0], base[:, 1], base[:, 2],
                          s=22, c=BLUE, alpha=0.80, depthshade=False)
for i in range(N_FRAMES):
    new_pos = base.copy(); new_pos[:, 2] += disp_z
    sc_electrons._offsets3d = (new_pos[:, 0], new_pos[:, 1], new_pos[:, 2])
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)

# WRONG — causes flicker
for i in range(N_FRAMES):
    ax.clear()         # NEVER
    ax.scatter(...)    # NEVER recreate inside loop
```

EXCEPTION: `plot_surface` cannot be updated in place — use `surf.remove(); surf = ax.plot_surface(...)`
for morphing surfaces. Keep surface morphs to <= 60 grid resolution to stay fast.

## Easing — Always (for CAMERA and reveals, not for physics)

Camera moves, fades, and non-physical reveals use the `ease()` / `phase()` helpers.
PHYSICAL motion is driven by the equations of motion above, NOT by `ease()` — a
falling ball follows -0.5*g*t**2, it is not eased.

```python
# Camera sweep (eased) — fine
azim = -55 + 90 * ease(t)
elev = 18 + 5 * np.sin(2*np.pi*t)
# Label fades in 5%->15%, etc.
label_alpha = phase(t, 0.05, 0.15)
```

## Iris-local 3D Physics Pattern Library

High-frequency, physically-correct patterns. Use them directly when applicable.

### Pattern 1: Projectile / free fall (CLOSED FORM — exact)
```python
g = 9.81; v0 = 7.0; angle = np.radians(60); dt = DURATION / N_FRAMES
vx, vy = v0*np.cos(angle), v0*np.sin(angle)
t_flight = 2*vy/g                      # time to land
xs_full = vx * np.linspace(0, t_flight, N_FRAMES)
ys_full = vy * np.linspace(0, t_flight, N_FRAMES) - 0.5*g*np.linspace(0,t_flight,N_FRAMES)**2
ball = ax.scatter([0],[0],[0], s=300, c=GOLD, edgecolors=WARM_WHITE, depthshade=False)
trail, = ax.plot([],[],[], color=BLUE, lw=2.4, alpha=0.8)
for i in range(N_FRAMES):
    ball._offsets3d = ([xs_full[i]], [0], [ys_full[i]])
    trail.set_data(xs_full[:i+1], np.zeros(i+1)); trail.set_3d_properties(ys_full[:i+1])
    ax.view_init(elev=12, azim=-70)
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
# Note: the ball is fast leaving, slow at the top, fast landing — that is correct.
```

### Pattern 2: Orbit / Kepler (VELOCITY VERLET — closed ellipse, conserves energy)
```python
GM = 1.0; dt = DURATION / N_FRAMES * 3.0     # scale sim-time for a full orbit
pos = np.array([1.4, 0.0, 0.0]); vel = np.array([0.0, 0.82, 0.0])  # elliptical
def accel(p):
    r = np.linalg.norm(p); return -GM * p / r**3
a = accel(pos); trailx, traily, trailz = [], [], []
star = ax.scatter([0],[0],[0], s=500, c=GOLD, depthshade=False)
planet = ax.scatter([0],[0],[0], s=120, c=BLUE, depthshade=False)
orbit, = ax.plot([],[],[], color=BLUE, lw=1.6, alpha=0.6)
for i in range(N_FRAMES):
    pos = pos + vel*dt + 0.5*a*dt*dt
    a_new = accel(pos); vel = vel + 0.5*(a + a_new)*dt; a = a_new
    trailx.append(pos[0]); traily.append(pos[1]); trailz.append(pos[2])
    planet._offsets3d = ([pos[0]],[pos[1]],[pos[2]])
    orbit.set_data(trailx, traily); orbit.set_3d_properties(trailz)
    ax.view_init(elev=28, azim=-60+30*ease(i/N_FRAMES))
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
# The planet visibly speeds up near the star (perihelion) — Kepler's 2nd law.
```

### Pattern 3: Pendulum (SEMI-IMPLICIT EULER — exact gravity, large-angle OK)
```python
g = 9.81; L = 1.6; theta = np.radians(75); omega = 0.0; dt = DURATION / N_FRAMES * 2.0
rod, = ax.plot([],[],[], color=DIM, lw=3); bob = ax.scatter([0],[0],[0], s=420, c=GOLD, depthshade=False)
pivot = np.array([0,0,1.6])
for i in range(N_FRAMES):
    omega += -(g/L)*np.sin(theta)*dt      # velocity first (symplectic)
    theta += omega*dt                     # then position with new velocity
    bx, bz = pivot[0]+L*np.sin(theta), pivot[2]-L*np.cos(theta)
    rod.set_data([pivot[0],bx],[0,0]); rod.set_3d_properties([pivot[2],bz])
    bob._offsets3d = ([bx],[0],[bz])
    ax.view_init(elev=8, azim=-90)
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
# Fastest at the bottom, momentarily still at the extremes — correct SHM behaviour.
```

### Pattern 4: Driven oscillator / resonance sweep (semi-implicit, drive sweeps through omega0)
```python
omega0 = 2.0*np.pi; gamma = 0.55; F0 = 5.5; dt = 1.0/FPS
z = 0.0; vz = 0.0; phase_acc = 0.0
ax.set_zlim(-3.6, 3.6); ax.set_box_aspect((1,1,1.6))
bead = ax.scatter([0],[0],[0], s=420, c=GOLD, edgecolors=WARM_WHITE, depthshade=False)
for i in range(N_FRAMES):
    gt = i/max(N_FRAMES-1,1)
    omega = omega0*(0.3 + 1.4*ease(gt))          # sweep drive 0.3->1.7 of resonance
    phase_acc += omega*dt
    F = F0*np.cos(phase_acc)
    a = -omega0**2*z - gamma*vz + F
    vz += a*dt; z += vz*dt                        # semi-implicit
    z = np.clip(z, -2.9, 2.9)
    bead._offsets3d = ([0],[0],[z])
    ax.view_init(elev=14, azim=25+75*ease(gt))
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
# Amplitude peaks as the drive passes omega0 — that is resonance.
```

### Pattern 5: Wave on a string / 2D field (explicit finite-difference wave eq)
```python
x = np.linspace(-3, 3, 220); c = 1.4; k = 2.0; w = c*k
line, = ax.plot([],[],[], color=BLUE, lw=2.6)
for i in range(N_FRAMES):
    t = i/FPS
    y = np.exp(-0.25*x**2) * np.cos(k*x - w*t)    # right-travelling wave packet
    line.set_data(x, np.zeros_like(x)); line.set_3d_properties(y)
    ax.view_init(elev=18, azim=-60)
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
```

### Pattern 6: Elastic collision (momentum + KE conserved)
```python
m1, m2 = 1.0, 2.0; x1, x2 = -2.0, 1.5; v1, v2 = 2.4, -1.0; r = 0.35; dt = DURATION/N_FRAMES
b1 = ax.scatter([x1],[0],[0], s=300, c=BLUE, depthshade=False)
b2 = ax.scatter([x2],[0],[0], s=520, c=CORAL, depthshade=False)
for i in range(N_FRAMES):
    x1 += v1*dt; x2 += v2*dt
    if x2 - x1 <= 2*r and v1 > v2:                 # 1-D elastic collision formulas
        u1 = ((m1-m2)*v1 + 2*m2*v2)/(m1+m2)
        u2 = ((m2-m1)*v2 + 2*m1*v1)/(m1+m2)
        v1, v2 = u1, u2
    b1._offsets3d=([x1],[0],[0]); b2._offsets3d=([x2],[0],[0])
    ax.view_init(elev=10, azim=-90)
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
```

### Pattern 7: Electron sea sloshing (LSP / nanoparticle — induced dipole)
```python
rng = np.random.default_rng(7); R = 0.95; Npart = 360
pts = []
while len(pts) < Npart:
    c = rng.uniform(-1,1,(Npart*2,3)); ok = c[np.linalg.norm(c,axis=1)<=1][:Npart-len(pts)]
    pts.extend(ok.tolist())
base = np.array(pts) * R
sc_ions = ax.scatter(base[:,0],base[:,1],base[:,2], s=18,c=GOLD,alpha=0.55,depthshade=False)
sc_e    = ax.scatter(base[:,0],base[:,1],base[:,2], s=22,c=BLUE,alpha=0.80,depthshade=False)
for i in range(N_FRAMES):
    t = i/max(N_FRAMES-1,1); e=ease(t)
    disp_z = -0.30*np.sin(2*np.pi*2.0*t)*(0.4+0.6*e)   # electrons LAG the field
    np_ = base.copy(); np_[:,2] += disp_z
    sc_e._offsets3d = (np_[:,0], np_[:,1], np_[:,2])
    ax.view_init(elev=18+5*np.sin(2*np.pi*t), azim=-55+90*e)
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
```

### Pattern 8: 3D vector field (dipole / solenoidal — build once, rotate camera)
```python
g = np.linspace(-1.5,1.5,8); Xg,Yg,Zg = np.meshgrid(g,g,g)
r2 = Xg**2+Yg**2+Zg**2+0.1
U = 3*Xg*Zg/r2**2.5; V = 3*Yg*Zg/r2**2.5; W = (3*Zg**2-r2)/r2**2.5
ax.quiver(Xg,Yg,Zg,U,V,W, length=0.25, normalize=True, color=BLUE, alpha=0.6)
for i in range(N_FRAMES):
    ax.view_init(elev=20+10*ease(i/(N_FRAMES-1)), azim=-60+120*ease(i/(N_FRAMES-1)))
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
```

### Pattern 9: Surface morph / dispersion landscape
```python
X,Y = np.meshgrid(np.linspace(-3,3,60), np.linspace(-3,3,60))
Za = np.sin(np.sqrt(X**2+Y**2)); Zb = X**2-Y**2
surf = ax.plot_surface(X,Y,Za, cmap='plasma', linewidth=0, antialiased=True)
for i in range(N_FRAMES):
    a = ease(i/(N_FRAMES-1)); Z = (1-a)*Za + a*Zb
    surf.remove(); surf = ax.plot_surface(X,Y,Z, cmap='plasma', linewidth=0, antialiased=True)
    ax.view_init(elev=20+20*a, azim=-40+120*ease(i/(N_FRAMES-1)))
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
```

### Pattern 10: Glow / Bloom (cheap visual lift for any 3D line — layer + fade)
```python
for lw, a in [(12, 0.06), (7, 0.14), (4, 0.28), (1.5, 1.0)]:
    ax.plot3D(xs, ys, zs, color=BLUE, lw=lw, alpha=a)
```

## 3D MODEL RECIPES — use these to put a real object on screen (audience holds longer on 3D)

Reach for one of these whenever the topic names a physical object. Build the model
ONCE, then rotate the camera (Pattern 3-style azim sweep) so it reads as a solid 3D thing.

### Ball-and-stick MOLECULE (atoms = colored spheres, bonds = grey sticks)
```python
def sphere(c, r, color, n=16):
    u=np.linspace(0,2*np.pi,n); v=np.linspace(0,np.pi,n//2)
    xs=c[0]+r*np.outer(np.cos(u),np.sin(v)); ys=c[1]+r*np.outer(np.sin(u),np.sin(v))
    zs=c[2]+r*np.outer(np.ones_like(u),np.cos(v))
    ax.plot_surface(xs,ys,zs, color=color, shade=True, linewidth=0, antialiased=True)
def bond(a, b):
    ax.plot([a[0],b[0]],[a[1],b[1]],[a[2],b[2]], color=DIM, lw=5, solid_capstyle='round')
# Water H2O: O at origin, two H at the 104.5-degree bond angle
O=np.array([0,0,0]); ang=np.radians(104.5/2); d=0.96
H1=np.array([ d*np.sin(ang), d*np.cos(ang),0]); H2=np.array([-d*np.sin(ang), d*np.cos(ang),0])
bond(O,H1); bond(O,H2); sphere(O,0.34,CORAL); sphere(H1,0.20,WARM_WHITE); sphere(H2,0.20,WARM_WHITE)
# Methane CH4 = tetrahedral: C at center, 4 H at tetra vertices (normalize the 4 corners of a cube).
```

### DNA double helix (two phosphate backbones + base-pair rungs)
```python
t = np.linspace(0, 4*np.pi, 240); rad = 0.7; rise = 0.18
x1, y1 = rad*np.cos(t), rad*np.sin(t)
x2, y2 = rad*np.cos(t+np.pi), rad*np.sin(t+np.pi); z = rise*t - rise*t.mean()
ax.plot3D(x1,y1,z, color=BLUE, lw=4); ax.plot3D(x2,y2,z, color=GOLD, lw=4)
for k in range(0, len(t), 10):
    ax.plot([x1[k],x2[k]],[y1[k],y2[k]],[z[k],z[k]], color=MINT, lw=2, alpha=0.8)
ax.set_zlim(z.min(), z.max())
```

### Crystal lattice (e.g. simple cubic / NaCl — two interpenetrating colored grids)
```python
n=3; idx=np.arange(n)
P=np.array([[i,j,k] for i in idx for j in idx for k in idx], float) - (n-1)/2
col=np.where((P.sum(1)%2)==0, 0, 1)
ax.scatter(P[col==0,0],P[col==0,1],P[col==0,2], s=260, c=GOLD, depthshade=True)
ax.scatter(P[col==1,0],P[col==1,1],P[col==1,2], s=160, c=BLUE, depthshade=True)
# thin bonds along nearest neighbours optional
```

### Atomic orbital (p-orbital lobes / s-shell) as an isosurface-style point cloud
```python
rng=np.random.default_rng(3); n=4000
pts=rng.normal(0,1,(n,3)); rr=np.linalg.norm(pts,axis=1)
w=(pts[:,2]**2)*np.exp(-rr)                 # p_z-like density weight
keep=rng.random(n) < w/ w.max()
P=pts[keep]; ax.scatter(P[:,0],P[:,1],P[:,2], s=6, c=LAVENDER, alpha=0.5, depthshade=False)
```

### Planetary system (central star + 2-3 planets on correct-speed circular orbits)
```python
star = ax.scatter([0],[0],[0], s=600, c=GOLD, depthshade=False)
radii=[0.9,1.5,2.1]; periods=[1.0,2.0,3.4]; cols=[BLUE,CORAL,MINT]; planets=[]
for rr,col in zip(radii,cols):
    planets.append(ax.scatter([rr],[0],[0], s=120, c=col, depthshade=False))
    th=np.linspace(0,2*np.pi,120); ax.plot3D(rr*np.cos(th),rr*np.sin(th),0*th, color=DIM, lw=1, alpha=0.5)
for i in range(N_FRAMES):
    t=i/FPS
    for p,rr,per in zip(planets,radii,periods):
        a=2*np.pi*t/per; p._offsets3d=([rr*np.cos(a)],[rr*np.sin(a)],[0])
    ax.view_init(elev=32, azim=-60+20*ease(i/N_FRAMES))
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
```

## 2D: Only When Geometry Is Truly 2D

Use standard 2D axes only for: waveforms vs time, spectra, 2D field maps (imshow),
histograms, 2D phase portraits. Setup:

```python
fig = plt.figure(figsize=(W/100, H/100), dpi=100, facecolor=BG)
ax = fig.add_subplot(111)
ax.set_facecolor(BG); ax.set_axis_off()
ax.set_xlim(-5,5); ax.set_ylim(-8.5,8.5)
# Build artists once, update in loop with set_data/set_ydata/set_offsets
```

For graphs/plots with VISIBLE axes (a key moment is reading a curve), keep axes on and style them:
```python
ax = fig.add_subplot(111, facecolor=BG)
for s in ax.spines.values(): s.set_color(DIM)
ax.tick_params(colors=DIM, labelsize=14)
ax.set_xlabel('t', color=WARM_WHITE, fontsize=18); ax.set_ylabel('x(t)', color=WARM_WHITE, fontsize=18)
ax.grid(True, color=DIM, alpha=0.25, lw=0.8)
# Draw the curve progressively so it tracks the narration:
line, = ax.plot([],[], color=BLUE, lw=3)
xs = np.linspace(0, 10, 400); ys = np.sin(xs)
for i in range(N_FRAMES):
    k = int((i+1)/N_FRAMES * len(xs)); line.set_data(xs[:k], ys[:k])
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
```

## Text overlays (both 2D and 3D)

```python
fig.text(0.5, 0.93, "Segment Title", ha='center', color=WARM_WHITE,
         fontsize=30, fontweight='bold', family='DejaVu Sans')
fig.text(0.5, 0.88, "subtitle or equation hint", ha='center',
         color=BLUE, fontsize=20, family='DejaVu Sans')
label = fig.text(0.10, 0.55, "label text", color=BLUE, fontsize=18,
                 family='DejaVu Sans', alpha=0.0)
# In loop:  label.set_alpha(phase(t, 0.05, 0.15))
```
{narration_block}
CRITICAL DYNAMIC REQUIREMENTS:
- Target Duration: {duration} seconds
- Exact frames required: {frames} (emit frame_0000.png ... frame_{last:04d}.png; N_FRAMES already equals this)
- Description: {description}

GENERATE ONLY PYTHON CODE. No markdown, no explanation. Use the patterns above directly,
and make the physics correct per the accuracy checklist.
"""


class PysimService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        description: str,
        duration: float,
        previous_error: str = None,
        voiceover_text: str = None,
    ) -> str:
        """
        Generate a PySim video from description.

        1. Generate Python script with Claude
        2. Run script to generate frames
        3. Compile frames to video

        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(round(duration * fps))

        logger.info(f"[PySim] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[PySim] Retrying with error context: {previous_error}")

        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error, voiceover_text)
        logger.info(f"[PySim] Script generated ({len(script)} chars)")

        # Step 2: Run simulation
        frames_path = FRAMES_DIR / video_id
        frames_path.mkdir(exist_ok=True)

        await self._run_simulation(script, str(frames_path), duration)

        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"pysim_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)

        return str(video_path)

    async def _generate_script(
        self,
        description: str,
        duration: float,
        frames: int,
        previous_error: str = None,
        voiceover_text: str = None,
    ) -> str:
        """Generate simulation script using Claude (streaming + adaptive thinking)."""


        narration_block = build_narration_timeline(voiceover_text, duration)
        description, narration_block, error_context = prepare_retry_context(
            description, narration_block, previous_error)

        final_prompt = (
            PYSIM_PROMPT
            .replace("{narration_block}", narration_block)
            .replace("{description}", description)
            .replace("{duration}", str(duration))
            .replace("{frames}", str(frames))
            .replace("{last:04d}", f"{max(frames - 1, 0):04d}")
            + error_context
        )

        self._last_prompt = final_prompt
        self._last_model = "claude-fable-5"

        response_text, stop_reason = generate_text(final_prompt, max_tokens=32000)
        if stop_reason == "max_tokens":
            raise RuntimeError("Code generation was truncated (hit max_tokens). The description may be too complex for a single segment.")

        return validate_script(strip_code_fences(response_text), "savefig", stop_reason, "matplotlib")

    async def _run_simulation(self, script: str, output_dir: str, duration: float):
        """Run the simulation script."""
        script_path = Path(output_dir) / "simulation.py"

        with open(script_path, "w") as f:
            f.write(script)

        logger.info(f"[PySim] Running simulation ({duration:.2f}s target)...")

        env = os.environ.copy()
        env["OUTPUT_DIR"] = output_dir
        # CRITICAL: inject the REAL segment duration so the script's
        # N_FRAMES = int(round(DURATION*FPS)) matches the voiceover length.
        # Previously DURATION was never set and defaulted to 8s, so many sims
        # rendered exactly 240 frames regardless of narration length and were
        # then time-stretched — the root cause of "the physics looks too slow".
        env["DURATION"] = str(float(duration))

        process = await asyncio.create_subprocess_exec(
            "python", str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Simulation failed: {error_msg}")

        logger.info(f"[PySim] Simulation complete")

    async def _compile_video(self, frames_dir: str, output_path: str, fps: int = 30):
        """Compile frames to video using FFmpeg."""
        from pathlib import Path
        frames_path = Path(frames_dir)
        frame_files = sorted(frames_path.glob("frame_*.png"))

        if not frame_files:
            raise RuntimeError(f"No frames found in {frames_dir}")

        logger.info(f"[PySim] Compiling {len(frame_files)} frames to video")

        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", f"{frames_dir}/frame_%04d.png",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",  # Ensure even dimensions for libx264
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "23",
            output_path
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            stderr_text = stderr.decode() if stderr else "Unknown error"
            logger.error(f"[PySim] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")

        logger.info(f"[PySim] Video compiled: {output_path}")
