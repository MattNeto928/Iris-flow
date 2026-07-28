#!/usr/bin/env python3
"""
Orb-web geometry solve for the video.

Builds the actual thread geometry of an Araneus diadematus orb web -- frame,
radii, hub spiral, temporary auxiliary spiral, sticky capture spiral -- in the
order a real spider lays them, and bakes it to web.json. The scene reads that
file and never invents a number: every length quoted on screen comes from here.

UNITS
  Internal: "u", the render world unit. 1 u = 10 mm exactly (MM_PER_UNIT).
  Chosen so a 30 cm web is 30 u across and a 15 mm spider is 1.5 u long, which
  keeps camera distances in the 10-120 range where the template's near plane
  (0.5), fog and aperture constants all behave. Physics-free geometry, so the
  scale is a free parameter picked for screen proportions; the millimetre
  figures are the meaningful ones and they are held to real published values.

MODELLING DECISIONS THAT ARE DELIBERATE, NOT SLOPPY
  * The capture and auxiliary spirals are polygons, not smooth curves. A real
    orb weaver walks radius to radius and lays a straight chord between each
    adjacent pair, so the spiral is a 30-gon that creeps inward. Drawing a
    smooth Archimedean spiral would be prettier and wrong.
  * Radii are laid into the largest remaining angular gap. Real spiders do not
    go strictly round-the-clock; they alternate sides to keep the unfinished
    web balanced, and greedy largest-gap filling reproduces that alternation
    without pretending to model the behaviour in detail.
  * Small out-of-plane jitter (< 1.5 mm) is added to every vertex. Real orb
    webs are near-planar but not perfectly planar, and a dead-flat web gives
    depth of field nothing to bite on.

SOURCES for the published values checked against at the bottom of this file:
  Foelix, "Biology of Spiders" 3rd ed. (2011)  -- web diameter, silk budget,
      build time, daily renewal, silk ingestion.
  Zschokke & Vollrath (1995), Eur. J. Entomol. 92:523-541 -- construction
      sequence and radius counts across orb weavers.
  Gosline et al. (1999), J. Exp. Biol. 202:3295-3303 -- silk mechanics (used by
      the caption text, not by this geometry).
"""

import json
import math
import os
import random

MM_PER_UNIT = 10.0

# ---------------------------------------------------------------- parameters
SEED = 20260727
N_RADII = 30              # on screen as "30 SPOKES" -- must match what is drawn
N_FRAME_SIDES = 6
R_NOMINAL = 15.0          # u -> 150 mm hub-to-frame, i.e. a 30 cm web
HUB_R0, HUB_R1, HUB_TURNS = 0.55, 2.30, 4        # dense central platform
FREE_ZONE_OUT = 3.10      # u -- capture spiral starts outside this
AUX_R0, AUX_R1, AUX_TURNS = 2.60, 13.60, 8       # temporary scaffold
CAP_R_OUT, CAP_R_IN, CAP_TURNS = 13.90, 3.35, 19  # sticky spiral, outside->in

rng = random.Random(SEED)


def jitter_z(scale=0.14):
    """Out-of-plane wobble. +/-1.4 mm; real webs are near-planar, not planar."""
    return rng.uniform(-scale, scale)


def polyline_length(pts):
    return sum(
        math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)
    )


# ---------------------------------------------------------------- frame polygon
# Irregular hexagon; real frames are set by whatever anchor points the spider
# found, so evenness would be the unrealistic choice.
frame_pts = []
for i in range(N_FRAME_SIDES):
    a = (i / N_FRAME_SIDES) * 2 * math.pi + rng.uniform(-0.20, 0.20) - 0.35
    r = R_NOMINAL * rng.uniform(1.02, 1.20)
    frame_pts.append((r * math.cos(a), r * math.sin(a), jitter_z(0.5)))


def ray_hit_frame(theta):
    """Where a radius at angle theta meets the frame polygon."""
    dx, dy = math.cos(theta), math.sin(theta)
    best = None
    n = len(frame_pts)
    for i in range(n):
        ax, ay, az = frame_pts[i]
        bx, by, bz = frame_pts[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if abs(den) < 1e-9:
            continue
        t = (ax * ey - ay * ex) / den          # distance along the ray
        s = (ax * dy - ay * dx) / den          # position along the edge
        if t > 0 and -1e-6 <= s <= 1 + 1e-6:
            if best is None or t < best[0]:
                best = (t, (ax + ex * s, ay + ey * s, az + (bz - az) * s))
    return best[1]


# ---------------------------------------------------------------- radii
# Angles: even, then perturbed. Measured Araneus webs have visibly uneven
# sectors, and a perfect 12.0 deg pitch reads as a graphic, not an animal.
angles = sorted(
    (i / N_RADII) * 2 * math.pi + rng.uniform(-0.055, 0.055)
    for i in range(N_RADII)
)

# Lay order: greedy largest-angular-gap. Seeded with a three-spoke star, NOT a
# Y: Zschokke & Vollrath 1995 p.526 state the proto-hub "consisted of several
# radii - never a simple Y-structure as described by Peters (1937b)", so the
# textbook Y is an eighty-year-old error and is deliberately not modelled here.
# The greedy fill is an approximation of the real rule (Zschokke & Vollrath:
# a new radius is inserted immediately below an existing one, never leaving a
# gap for later) that reproduces the side-alternation without the behaviour.
placed = [0, N_RADII // 3, (2 * N_RADII) // 3]
order = list(placed)
remaining = [i for i in range(N_RADII) if i not in placed]
while remaining:
    def gap_for(i):
        left = max((a for a in order if angles[a] < angles[i]),
                   key=lambda a: angles[a], default=None)
        right = min((a for a in order if angles[a] > angles[i]),
                    key=lambda a: angles[a], default=None)
        lo = angles[left] if left is not None else angles[max(order, key=lambda a: angles[a])] - 2 * math.pi
        hi = angles[right] if right is not None else angles[min(order, key=lambda a: angles[a])] + 2 * math.pi
        return hi - lo
    pick = max(remaining, key=gap_for)
    order.append(pick)
    remaining.remove(pick)

rim = [ray_hit_frame(a) for a in angles]
hub_end = [
    (HUB_R0 * 0.35 * math.cos(a), HUB_R0 * 0.35 * math.sin(a), jitter_z(0.05))
    for a in angles
]
radii = [[hub_end[i], rim[i]] for i in range(N_RADII)]


# ---------------------------------------------------------------- spirals
def spiral(r_start, r_end, turns, start_idx=0, direction=+1):
    """
    Vertices only where the spiral crosses a radius -- the chord-per-sector
    polygon a real spider actually lays. Returns points in lay order.
    """
    steps = int(round(turns * N_RADII))
    pts = []
    for k in range(steps + 1):
        t = k / steps
        idx = (start_idx + direction * k) % N_RADII
        a = angles[idx] + direction * 2 * math.pi * ((start_idx + direction * k) // N_RADII)
        # radius interpolated geometrically: constant *proportional* pitch,
        # which is what a spider stepping by a fixed leg span produces
        r = r_start * (r_end / r_start) ** t
        th = angles[idx]
        pts.append((r * math.cos(th), r * math.sin(th), jitter_z(0.10)))
    return pts


hub_spiral = spiral(HUB_R0, HUB_R1, HUB_TURNS, start_idx=0, direction=+1)
aux_spiral = spiral(AUX_R0, AUX_R1, AUX_TURNS, start_idx=0, direction=+1)
# Capture spiral runs the other way round the hub -- documented for orb weavers,
# and it is why the two spirals cross rather than nest.
cap_spiral = spiral(CAP_R_OUT, CAP_R_IN, CAP_TURNS, start_idx=7, direction=-1)

# ---------------------------------------------------------------- bridge + anchors
# The bridge line is the first thread: floated across on a breeze and anchored
# at two high points. Frame vertices 1 and 2 are the anchors here.
bridge = [frame_pts[1], frame_pts[2]]

# Guy/anchor lines running off the frame to the outside world (twigs, stems).
anchors = []
for i, (x, y, z) in enumerate(frame_pts):
    r = math.hypot(x, y)
    ux, uy = x / r, y / r
    L = rng.uniform(7.0, 13.0)
    anchors.append([(x, y, z), (x + ux * L, y + uy * L + rng.uniform(-2, 2), z + jitter_z(1.2))])

# ---------------------------------------------------------------- lengths
u2m = MM_PER_UNIT / 1000.0
L_frame = sum(math.dist(frame_pts[i], frame_pts[(i + 1) % N_FRAME_SIDES])
              for i in range(N_FRAME_SIDES)) * u2m
L_radii = sum(math.dist(a, b) for a, b in radii) * u2m
L_hub = polyline_length(hub_spiral) * u2m
L_aux = polyline_length(aux_spiral) * u2m
L_cap = polyline_length(cap_spiral) * u2m
L_anchor = sum(math.dist(a, b) for a, b in anchors) * u2m
L_permanent = L_frame + L_radii + L_hub + L_cap + L_anchor
L_spun_total = L_permanent + L_aux     # aux is spun then removed

web_diam_mm = 2 * (sum(math.hypot(p[0], p[1]) for p in frame_pts) / len(frame_pts)) * MM_PER_UNIT
cap_spacing_mm = ((CAP_R_OUT - CAP_R_IN) / CAP_TURNS) * MM_PER_UNIT
aux_spacing_mm = ((AUX_R1 - AUX_R0) / AUX_TURNS) * MM_PER_UNIT

# ---------------------------------------------------------------- silk mechanics
# Not computed here -- these are published values, carried in the JSON so the
# captions interpolate from one place. Gosline et al. 1999, J Exp Biol 202,
# Table 1 (Araneus MA silk vs high-tensile steel vs Kevlar 49).
SILK = {
    "sigma_GPa": 1.1,          # ultimate tensile strength, Araneus MA silk
    "toughness_MJm3": 160.0,   # energy to break per unit volume
    "density_gcm3": 1.3,
    "steel_sigma_GPa": 1.5,    # high-tensile steel
    "steel_toughness_MJm3": 6.0,
    "steel_density_gcm3": 7.8,
    "kevlar_sigma_GPa": 3.6,
    "kevlar_toughness_MJm3": 50.0,
    "fibre_um": 3.5,           # dragline diameter, Araneus
    "hair_um": 70.0,           # mean human head hair
}
spec_silk = SILK["sigma_GPa"] / SILK["density_gcm3"]
spec_steel = SILK["steel_sigma_GPa"] / SILK["steel_density_gcm3"]
SILK["specific_ratio_vs_steel"] = spec_silk / spec_steel
SILK["toughness_ratio_vs_kevlar"] = SILK["toughness_MJm3"] / SILK["kevlar_toughness_MJm3"]
SILK["hair_to_fibre_ratio"] = SILK["hair_um"] / SILK["fibre_um"]

# Mass of the finished web: derived, not quoted. L * pi*(d/2)^2 * rho.
web_mass_mg = (L_permanent * math.pi * (SILK["fibre_um"] * 1e-6 / 2) ** 2
               * SILK["density_gcm3"] * 1000.0) * 1e6

out = {
    "mm_per_unit": MM_PER_UNIT,
    "web_mass_mg": web_mass_mg,
    "n_radii": N_RADII,
    "cap_turns": CAP_TURNS,
    "aux_turns": AUX_TURNS,
    "angles": angles,
    "framePts": frame_pts,
    "anchors": anchors,
    "bridge": bridge,
    "radii": radii,
    "radiiOrder": order,
    "hubSpiral": hub_spiral,
    "auxSpiral": aux_spiral,
    "capSpiral": cap_spiral,
    "stats": {
        "web_diameter_mm": web_diam_mm,
        "cap_spacing_mm": cap_spacing_mm,
        "aux_spacing_mm": aux_spacing_mm,
        "L_frame_m": L_frame, "L_radii_m": L_radii, "L_hub_m": L_hub,
        "L_aux_m": L_aux, "L_cap_m": L_cap, "L_anchor_m": L_anchor,
        "L_permanent_m": L_permanent, "L_spun_total_m": L_spun_total,
    },
    "silk": SILK,
}

here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "web.json"), "w") as f:
    json.dump(out, f)

# ---------------------------------------------------------------- validation
# Every derived quantity checked against a published range, printed, so a bad
# solve is visible here rather than on screen.
def check(name, value, lo, hi, unit, source):
    ok = "OK " if lo <= value <= hi else "!! "
    print(f"{ok}{name:26s} {value:8.2f} {unit:6s}  published {lo}-{hi}  [{source}]")


print(f"web.json written: {len(cap_spiral)} capture verts, "
      f"{len(aux_spiral)} aux verts, {N_RADII} radii\n")
print("derived vs published --------------------------------------------------")
check("web diameter", web_diam_mm, 200, 400, "mm", "Foelix 2011: Araneus orb 20-40 cm")
check("radii count", N_RADII, 25, 30, "", "Foelix via ADW: adult A. diadematus 25-30")
check("capture spiral spacing", cap_spacing_mm, 4.0, 7.0, "mm", "Herberstein & Heiling 1998 T1: mesh height 5.6 mm")
check("aux spiral spacing", aux_spacing_mm, 8.0, 25.0, "mm", "~ one leg span, wider than capture")
check("permanent silk", L_permanent, 15.0, 28.0, "m", "commonly cited ~20 m per orb")
print(f"   breakdown  frame {L_frame:.2f}  radii {L_radii:.2f}  hub {L_hub:.2f} "
      f" capture {L_cap:.2f}  anchors {L_anchor:.2f}   (+ aux {L_aux:.2f} spun then eaten)")
print()
print("silk mechanics (Gosline et al. 1999, J Exp Biol 202:3295, Table 1) ------")
print(f"   dragline {SILK['sigma_GPa']} GPa at {SILK['density_gcm3']} g/cm3 "
      f"-> specific strength {spec_silk:.3f} GPa/(g/cm3)")
print(f"   HT steel {SILK['steel_sigma_GPa']} GPa at {SILK['steel_density_gcm3']} g/cm3 "
      f"-> {spec_steel:.3f}   ratio = {SILK['specific_ratio_vs_steel']:.2f}x")
print(f"   toughness {SILK['toughness_MJm3']} vs Kevlar {SILK['kevlar_toughness_MJm3']} MJ/m3 "
      f"= {SILK['toughness_ratio_vs_kevlar']:.1f}x")
print(f"   fibre {SILK['fibre_um']} um vs hair {SILK['hair_um']} um "
      f"= {SILK['hair_to_fibre_ratio']:.0f}x thinner")
print()
print(f"   finished web mass = {L_permanent:.1f} m x pi(({SILK['fibre_um']}um)/2)^2 x "
      f"{SILK['density_gcm3']} g/cm3 = {web_mass_mg:.2f} mg")
print()
print("CAPTION-READY  ->  "
      f"{L_permanent:.0f} m of silk | {web_diam_mm/10:.0f} cm across | "
      f"{N_RADII} spokes | {CAP_TURNS} turns | {web_mass_mg:.1f} mg")
