#!/usr/bin/env python3
"""
100 natural-phenomenon topics for the iris-motion pipeline.

These are shaped for a DIFFERENT renderer than the STEM topics in
populate_mega_topics.py. That pipeline draws charts, graphs and manim figures;
this one builds a real 3D scene in Three.js with motion blur, depth of field,
particle fields and a moving camera. So the selection rule here is:

  1. A MECHANISM, not a fact. "Why X happens" beats "X is Y metres tall".
     The pieces that worked (aurora, spider web, bee pollination, lightning)
     all follow one causal chain from beginning to end.
  2. A COUNTERINTUITIVE HOOK. The best one so far was "lightning doesn't fall,
     it climbs" — the reversal IS the video. A topic with no surprise in it
     produces a competent, forgettable piece.
  3. NUMBERS THAT CAN GO ON SCREEN and be defended. 22 degrees, 62 nanoseconds,
     1/3 the speed of light. A topic with no numbers gives the captions nothing
     to carry.
  4. GEOMETRY, MOTION, FIELDS OR SCALE. Something to build in 3D and fly a
     camera through. Anything whose natural form is a 2D plot belongs in the
     other queue.

Deliberately excluded because they are already made: the aurora, the orb-weaver
web, bee pollination, why the sky is blue, the CMB, and lightning.

    python3 scripts/populate_motion_phenomena.py            # enqueue all 100
    python3 scripts/populate_motion_phenomena.py --dry-run  # print, send nothing
    python3 scripts/populate_motion_phenomena.py --limit 10
"""

import argparse
import json
import sys

import boto3

QUEUE_NAME = "iris-flow-topic-queue"

TOPICS = [
    # ---------------------------------------------------- atmospheric optics
    {"prompt": "Why a rainbow is always a 42-degree circle. Follow one ray into a spherical raindrop: refract, reflect once off the back, refract out. The exit angle has a maximum near 42 degrees, so rays pile up there — that caustic IS the bow. Show why you can never reach it and why the sky inside is brighter than outside.", "category": "atmospheric_optics"},
    {"prompt": "The 22-degree halo around the Moon. Hexagonal ice crystals at cirrus altitude act as 60-degree prisms; the minimum deviation for ice is 21.8 degrees, so light banks up at that radius no matter how the crystals tumble. Build the crystal, trace the ray, then pull back to the ring.", "category": "atmospheric_optics"},
    {"prompt": "Sun dogs. Plate-shaped ice crystals fall with their flat faces horizontal, so they refract sunlight sideways into two bright spots 22 degrees left and right of the Sun, at the Sun's own altitude. Show the crystals settling into alignment like falling leaves, and why the dogs move outward as the Sun climbs.", "category": "atmospheric_optics"},
    {"prompt": "The green flash at sunset. The atmosphere is a weak prism: it lifts the green image of the Sun about 10 arcseconds higher than the red one. For a second or two the red disc has set and the green has not. Show the two discs separating, and why you need a sharp horizon and still air.", "category": "atmospheric_optics"},
    {"prompt": "Why a road mirage looks like water. Air within a few millimetres of hot asphalt is less dense, so light bends upward and you see the sky reflected off nothing. Trace a ray curving through the gradient and show the inverted image forming.", "category": "atmospheric_optics"},
    {"prompt": "A glory and the Brocken spectre. Your shadow on a cloud, ringed with colour. The ring comes from backscattering off droplets a few microns across — a surface-wave effect no simple ray optics predicts. Show the droplet, the returning light, and why the rings are smaller when the droplets are bigger.", "category": "atmospheric_optics"},
    {"prompt": "Why clouds are white but storm clouds are grey. Same water, same droplets — the difference is optical depth. Show photons random-walking through a thin cloud and escaping, then through a kilometre-thick one where most are absorbed before they get out.", "category": "atmospheric_optics"},
    {"prompt": "Noctilucent clouds. The highest clouds on Earth, at 82 kilometres, made of ice on meteor dust in air a millionth as dense as sea level. They glow after sunset because at that altitude they are still in sunlight while the ground is in shadow. Show the terminator sweeping under them.", "category": "atmospheric_optics"},
    {"prompt": "The twilight wedge and the Belt of Venus. The pink band opposite the setting Sun is backscattered sunlight above Earth's own shadow, which is rising in the east at roughly 15 degrees per hour. Show the shadow as a real geometric cone extending into space.", "category": "atmospheric_optics"},
    {"prompt": "Crepuscular rays are parallel. They appear to fan out only because of perspective, the same reason railway tracks converge. Show them as genuinely parallel shafts in 3D, then cut to the ground view where they seem to radiate from a point.", "category": "atmospheric_optics"},

    # ---------------------------------------------------------- water and ice
    {"prompt": "Why ice floats. Liquid water molecules pack randomly and closely; on freezing, hydrogen bonds force a hexagonal lattice with holes in it, and the solid ends up about 9 percent less dense. Build both arrangements and show the volume expanding — and why lakes therefore freeze from the top down.", "category": "water_and_ice"},
    {"prompt": "How a snowflake gets six arms and no two are alike. Water's hexagonal lattice sets the six-fold symmetry; the branching comes from diffusion-limited growth, where a tip that pokes ahead finds more vapour and runs away. All six arms share one history through the cloud, which is why they match each other but not anyone else's.", "category": "water_and_ice"},
    {"prompt": "Supercooling. Pure water can sit liquid at minus 40 Celsius because freezing needs a nucleation site, not just cold. Show the energy barrier a critical nucleus has to clear, then a single speck triggering a freeze front that crosses the bottle in a second.", "category": "water_and_ice"},
    {"prompt": "How water climbs a hundred-metre tree with no pump. Evaporation from a leaf pore pulls on a continuous water column held together by hydrogen bonds, under tension of about 2 megapascals — the water is literally being stretched. Follow one molecule from root to stoma.", "category": "water_and_ice"},
    {"prompt": "Why a water strider does not sink. Surface tension of 72 millinewtons per metre against a body weighing a fraction of a millinewton. Show the meniscus dimpling under each hydrophobic leg and the force balance, then what happens when you add a drop of soap.", "category": "water_and_ice"},
    {"prompt": "Why waves break at the shore. In deep water the orbit of a water particle is a closed circle; as depth shrinks the orbits flatten into ellipses, the crest outruns the trough, and the wave topples. Animate the particle orbits changing shape as the bottom rises.", "category": "water_and_ice"},
    {"prompt": "Why there are two tides a day, not one. The Moon pulls the near ocean more than Earth's centre and Earth's centre more than the far ocean, so the water bulges at BOTH ends. Show the differential field as arrows relative to the centre, then spin the Earth through both bulges.", "category": "water_and_ice"},
    {"prompt": "Rogue waves. Hundreds of small waves with random phases occasionally line up; linear superposition alone makes a 30-metre wave rare but not impossible, and nonlinear focusing makes it likelier still. Show many wave trains summing, and one moment of constructive alignment.", "category": "water_and_ice"},
    {"prompt": "The pistol shrimp's cavitation bubble. It snaps a claw fast enough to drop the local pressure below water's vapour pressure; the bubble collapses in microseconds, briefly reaching thousands of kelvin and emitting a flash of light. Show the pressure field, the bubble, and the collapse.", "category": "water_and_ice"},
    {"prompt": "Thermohaline circulation. Cold salty water sinking in the North Atlantic drives a global conveyor that takes roughly a thousand years to complete a circuit. Build it as a single 3D ribbon wrapping the planet, coloured by temperature.", "category": "water_and_ice"},

    # ------------------------------------------------------------- geology
    {"prompt": "Why columnar basalt is hexagonal. Cooling lava contracts and cracks; cracks meet at 120 degrees because that geometry relieves the most stress per unit of new surface, and 120-degree joints tile the plane as hexagons. Show the crack front propagating down from the cooling surface.", "category": "geology"},
    {"prompt": "What makes a geyser periodic. Water deep in the conduit is under pressure and superheats past 100 Celsius; when the column finally boils, the eruption drops the pressure, which triggers the rest to flash to steam. Show the pressure-depth curve and the recharge cycle.", "category": "geology"},
    {"prompt": "How a stalactite grows one hundredth of a millimetre a year. A drop saturated with calcium bicarbonate loses carbon dioxide at the tip, calcite comes out of solution in a ring, and the ring becomes the next millimetre of straw. Time-lapse ten thousand years.", "category": "geology"},
    {"prompt": "How a sand dune walks. Grains saltate up the shallow windward face, avalanche down the steep slip face at the 34-degree angle of repose, and the whole dune migrates downwind while every individual grain moves upwind of where it started. Follow one grain.", "category": "geology"},
    {"prompt": "Why rivers meander and then cut themselves off. Flow is faster on the outside of a bend, so it erodes there and deposits on the inside; the bend amplifies until the neck pinches through and leaves an oxbow lake. Show the secondary helical flow that does the actual work.", "category": "geology"},
    {"prompt": "P waves and S waves, and how one earthquake locates itself. P waves are compressional and travel about 6 kilometres per second; S waves are shear and manage about 3.5. The gap between arrivals gives the distance, and three stations give the epicentre. Animate both wavefronts.", "category": "geology"},
    {"prompt": "Why the seafloor is striped. Basalt records Earth's magnetic field as it cools, and the field has reversed hundreds of times, so spreading ridges print a symmetric barcode on both sides. Show the ridge extruding new crust and the stripes marching outward.", "category": "geology"},
    {"prompt": "Glaciers flow because ice is a fluid. Under its own weight ice deforms by dislocation creep in the crystal lattice; the surface moves faster than the bed, which is why crevasses open at the top and not the bottom. Show the velocity profile through the depth.", "category": "geology"},
    {"prompt": "Volcanic lightning. Ash particles charge by collision in the eruption column exactly as ice does in a thunderstorm, and the plume becomes a self-contained storm. Show charge separating by particle size and the discharge path.", "category": "geology"},
    {"prompt": "Subduction. Ocean crust cools, thickens and grows denser than the mantle beneath it, until it founders and pulls the rest of the plate after it — slab pull, not push, is what drives plate motion. Build the cross section and show the earthquakes deepening along the slab.", "category": "geology"},

    # ------------------------------------------------------- life and motion
    {"prompt": "A murmuration has no leader. Each starling tracks its seven nearest neighbours with three rules — avoid, align, approach — and the flock's shape is emergent. Show one bird's seven links, then ten thousand birds, then a hawk's attack propagating as a wave.", "category": "emergence"},
    {"prompt": "How fireflies synchronise. Each one nudges its own oscillator toward the flashes it sees; above a coupling threshold the whole field locks in a few minutes. Animate the phase of every insect as an arrow on a circle, and watch the arrows collapse together.", "category": "emergence"},
    {"prompt": "Why periodical cicadas emerge on primes — 13 and 17 years. A prime cycle shares a common multiple with a predator's cycle as rarely as possible, so no predator can lock on. Show the two cycles beating against each other over centuries.", "category": "emergence"},
    {"prompt": "How a maple seed flies. The samara autorotates, and the leading-edge vortex it sheds doubles its lift — the same trick a hovering insect uses. Show the vortex forming and the descent rate halving.", "category": "life_mechanics"},
    {"prompt": "How a gecko sticks to glass. Not glue and not suction: half a million setae per foot, each splitting into hundreds of spatulae, bring enough surface into van der Waals range that the total is many times the animal's weight. Zoom five orders of magnitude from foot to spatula.", "category": "life_mechanics"},
    {"prompt": "Why a hummingbird can hover and a sparrow cannot. Its wing generates lift on BOTH strokes by inverting through a figure-eight, at around 50 beats a second. Show the wing path in 3D and the lift vector on each half-stroke.", "category": "life_mechanics"},
    {"prompt": "How a slime mould solves a maze. It floods every path, then retracts the tubes carrying less flow and thickens the ones carrying more, leaving the shortest route. Show the network pruning itself over hours.", "category": "emergence"},
    {"prompt": "How ants find the shortest path with no map. Pheromone evaporates, so a shorter route gets reinforced more often per unit time and wins by positive feedback. Show two routes competing and the trail concentrating on one.", "category": "emergence"},
    {"prompt": "Bioluminescence. Luciferin plus oxygen, catalysed by luciferase, drops an electron from an excited state and emits a photon — near 100 percent efficient, with almost no waste heat, against roughly 10 percent for an incandescent bulb. Show the reaction and the emission.", "category": "life_mechanics"},
    {"prompt": "How a monarch butterfly navigates 4,000 kilometres. A time-compensated sun compass: it reads the Sun's azimuth and corrects with a circadian clock in its antennae, so the same heading holds all day. Show the Sun moving and the correction tracking it.", "category": "life_mechanics"},

    # ------------------------------------------------------------- astronomy
    {"prompt": "Why the Moon shows one face. Earth raises a tidal bulge on the Moon; the bulge lags, and the torque bled off the Moon's spin until rotation matched orbit. Show the bulge, the lag angle, and the spin slowing to lock.", "category": "astronomy"},
    {"prompt": "The eclipse coincidence. The Sun is about 400 times wider than the Moon and about 400 times further away, so they subtend nearly the same half-degree — and it is temporary, since the Moon recedes 3.8 centimetres a year. Show the cones and the shrinking future.", "category": "astronomy"},
    {"prompt": "Why Saturn's rings are only tens of metres thick. Any particle with a vertical wobble collides with the crowd and damps out, so the disc flattens to the plane in a few orbits. Show the collisional damping, then the true aspect ratio at real scale.", "category": "astronomy"},
    {"prompt": "Lagrange points. Where the combined pull of two bodies matches the centripetal requirement of the orbit, a third body can just sit. Build the effective potential as a surface and drop a marble into L4.", "category": "astronomy"},
    {"prompt": "Why a comet has two tails pointing different ways. Dust lags along the orbit and curves; ions are swept straight back by the solar wind at 400 kilometres a second. Both point away from the Sun, not away from the direction of travel. Show both forming.", "category": "astronomy"},
    {"prompt": "Kepler's second law. A planet sweeps equal areas in equal times, which is angular momentum conservation and nothing more. Animate the swept wedges around an eccentric orbit and show them matching.", "category": "astronomy"},
    {"prompt": "Why Mars appears to move backwards. Retrograde motion is a parallax illusion as Earth overtakes on the inside track. Show both orbits, then the line of sight tracing a loop against the fixed stars.", "category": "astronomy"},
    {"prompt": "The photon sphere. At 1.5 Schwarzschild radii light can orbit a black hole; look sideways there and you see the back of your own head. Trace a photon around the circle and show the shadow it casts.", "category": "astronomy"},
    {"prompt": "A teaspoon of neutron star. Degenerate neutrons at nuclear density, about 400 million tonnes in five millilitres, held up by the Pauli exclusion principle rather than any force between particles. Build the comparison honestly at scale.", "category": "astronomy"},
    {"prompt": "How a meteor makes light. It is not friction: the object compresses the air in front of it so violently that the shock heats to thousands of kelvin, ablating the surface and ionising a trail 100 kilometres up. Show the shock standoff and the glowing column.", "category": "astronomy"},

    # ------------------------------------------------------- waves and sound
    {"prompt": "Why thunder rumbles instead of cracking. The channel is kilometres long, so sound from the far end arrives seconds after sound from the near end — and light beats sound by roughly 3 seconds per kilometre. Show the arrival times spreading along the bolt.", "category": "waves"},
    {"prompt": "The sonic boom is a cone, not a bang at the moment of breaking. Every pressure pulse expands at the speed of sound while the aircraft outruns them, so the envelope is a Mach cone that drags across the ground continuously. Build the cone from the individual wavefronts.", "category": "waves"},
    {"prompt": "The Doppler effect in three dimensions. Wavefronts bunch ahead and stretch behind a moving source; the pitch does not slide down as it approaches, it changes abruptly as it passes. Show the fronts and the observed frequency against time.", "category": "waves"},
    {"prompt": "Chladni patterns. Sand on a vibrating plate migrates to the nodal lines where the amplitude is zero, so the sand draws the standing-wave mode. Animate the plate deforming and the grains settling into the nulls.", "category": "waves"},
    {"prompt": "Why a guitar string only plays certain notes. Fixed ends force whole numbers of half-wavelengths, so the allowed frequencies are integer multiples of the fundamental. Show the first five modes and how their sum makes the actual timbre.", "category": "waves"},
    {"prompt": "Beats. Two nearby frequencies sum to an amplitude that pulses at exactly their difference, which is how a piano is tuned by ear. Show the two waves and the envelope.", "category": "waves"},
    {"prompt": "Total internal reflection and how fibre optics work. Past the critical angle — about 41 degrees for glass to air — refraction stops entirely and the light is trapped. Trace a ray bouncing down a kilometre of fibre.", "category": "waves"},
    {"prompt": "How polarised sunglasses kill glare. Light reflecting off water is partly polarised horizontally, strongly so near Brewster's angle of about 53 degrees, and a vertical filter removes it. Show the reflection, the polarisation, and the filter.", "category": "waves"},
    {"prompt": "Why a whispering gallery works. Sound skims the curved wall at grazing incidence and stays bound to it, so a whisper crosses 40 metres of dome and arrives at one specific spot. Trace the ray hugging the curve.", "category": "waves"},
    {"prompt": "Resonance, and why soldiers break step on a bridge. Driving a system at its natural frequency puts energy in every cycle and amplitude grows until something gives. Show the response curve and the amplitude climbing.", "category": "waves"},

    # ----------------------------------------------------- matter and fields
    {"prompt": "Why glass is transparent but the sand it came from is not. Visible photons carry too little energy to bridge the band gap, so there is no state to absorb into and they pass straight through; scattering at grain boundaries is what makes powder opaque. Show the band gap and the two paths.", "category": "matter"},
    {"prompt": "Why metals are shiny. The free-electron sea re-radiates incoming light below the plasma frequency, so almost everything reflects — and gold looks gold because relativistic effects on its electrons move the absorption edge into the blue. Show the electron response.", "category": "matter"},
    {"prompt": "Ferrofluid spikes. Magnetic energy wants tall peaks, gravity and surface tension want a flat surface, and above a critical field the Rosensweig instability picks a hexagonal lattice of spikes. Show the three energies competing and the wavelength that wins.", "category": "matter"},
    {"prompt": "Why a soap film always finds the smallest surface. Surface tension makes area cost energy, so the film relaxes to a minimal surface with zero mean curvature everywhere. Build it on a cube frame and show the inner square that appears.", "category": "matter"},
    {"prompt": "The colours in a soap bubble. Light reflecting off the front and back of a film a few hundred nanometres thick interferes with itself; the film thins under gravity, the colours march, and it goes black just before it pops. Show the path difference and the thinning.", "category": "matter"},
    {"prompt": "Why a superconductor floats. Below its critical temperature it expels magnetic flux entirely — the Meissner effect — and flux pinning locks it in place, so it hovers rather than merely balancing. Show the field lines being pushed out.", "category": "matter"},
    {"prompt": "Non-Newtonian fluids. Cornstarch in water is a suspension whose particles jam under shear, so it is liquid when poured and solid when struck. Show the particle packing under slow and fast strain.", "category": "matter"},
    {"prompt": "Tears of wine. Alcohol evaporates faster from the thin film on the glass, raising the surface tension there and pulling liquid up — the Marangoni effect — until drops run back down. Show the gradient and the flow.", "category": "matter"},
    {"prompt": "How a crack runs through glass. Stress concentrates at the tip by a factor that grows with the square root of the crack length, so past a critical size it accelerates to a fraction of the speed of sound and cannot be stopped. Show the stress field at the tip.", "category": "matter"},
    {"prompt": "How a magnetic field is actually shaped. Field lines are a bookkeeping device for a vector field with no sources — they never begin, never end, and never cross. Build a dipole in 3D and show iron filings picking out the same geometry.", "category": "matter"},

    # ------------------------------------------------- emergence and scaling
    {"prompt": "The coastline paradox. Measure Britain with a 200-kilometre ruler and a 50-kilometre ruler and you get different answers, because the length grows without limit as the ruler shrinks. Show the measurement and the log-log slope that defines its fractal dimension.", "category": "emergence"},
    {"prompt": "Why sunflower seeds spiral in Fibonacci numbers. Each new primordium appears at the golden angle, 137.5 degrees, which is the least well approximated by any fraction and so packs without leaving radial gaps. Show what 137.5 gives versus 137 and 138.", "category": "emergence"},
    {"prompt": "Turing patterns. A slow activator and a fast inhibitor, both just diffusing and reacting, spontaneously produce spots and stripes — and the same equations put stripes on a tail but never spots on a striped animal's tail. Run the reaction-diffusion field.", "category": "emergence"},
    {"prompt": "Rayleigh-Benard convection. Heat a fluid from below and past a critical temperature difference the conduction solution goes unstable, organising into hexagonal cells of a size set by the layer depth. Show the rolls forming and the cell size.", "category": "emergence"},
    {"prompt": "The von Karman vortex street. Flow past a cylinder sheds alternating vortices at a Strouhal number near 0.2, which is why power lines hum and why cloud streets trail downwind of islands. Show the shedding and the frequency.", "category": "emergence"},
    {"prompt": "Where laminar flow becomes turbulent. Below a Reynolds number of about 2000 a pipe flow is orderly; above about 4000 it is chaotic, and the transition is abrupt rather than gradual. Show dye in both regimes and the number that separates them.", "category": "emergence"},
    {"prompt": "Brownian motion, and how it proved atoms exist. A pollen grain is kicked by molecules from every side; the imbalance is random, mean displacement is zero, but mean SQUARED displacement grows linearly with time. Show one trajectory and the statistics of a thousand.", "category": "emergence"},
    {"prompt": "The percolation threshold. Fill a lattice at random and nothing spans it until you cross a critical fraction, then a connected cluster appears abruptly — the same mathematics as a forest fire and a phase transition. Show the cluster appearing at the threshold.", "category": "emergence"},
    {"prompt": "Self-organised criticality in a sandpile. Add grains one at a time and the pile drives itself to a critical slope where avalanche sizes follow a power law — no tuning required. Show the pile and the size distribution.", "category": "emergence"},
    {"prompt": "Why crystals need a seed. Homogeneous nucleation must pay a surface energy cost before it earns a volume energy benefit, so tiny clusters dissolve and only clusters past the critical radius grow. Show the energy barrier and the runaway.", "category": "emergence"},

    # -------------------------------------------------------- second hundred
    {"prompt": "How a falling cat rights itself with zero angular momentum. It cannot rotate as a rigid body, so it counter-rotates front and back halves while tucking and extending, changing its moment of inertia. Net rotation without net angular momentum. Show the two halves and the inertia change.", "category": "life_mechanics"},
    {"prompt": "How a bat sees with sound. It emits chirps sweeping 100 down to 40 kilohertz and reads the echo delay for range and the Doppler shift for speed, resolving a target a millimetre across. Show the chirp, the echo, and the delay-to-distance conversion.", "category": "life_mechanics"},
    {"prompt": "How a root knows which way is down. Starch grains called statoliths sink inside specialised cells, the cell reads where they land, and auxin redistributes to bend the root toward gravity. Show the grains settling after the seed is rotated.", "category": "life_mechanics"},
    {"prompt": "The electric eel stacks 6,000 cells in series. Each electrocyte contributes about 0.15 volts, exactly as a nerve cell does, but wired end to end they sum to 600 volts. Show one cell's ion flux, then the series stack discharging together.", "category": "life_mechanics"},
    {"prompt": "The light reaction of photosynthesis. A photon hits chlorophyll, an electron is lifted and handed down a chain of carriers, and the energy released pumps protons across a membrane to spin ATP synthase like a turbine. Follow one electron and one proton.", "category": "life_mechanics"},
    {"prompt": "Why a hurricane spins, and why it spins the other way south of the equator. The Coriolis effect deflects inflowing air right in the north and left in the south; it vanishes at the equator, which is why no hurricane forms within 5 degrees of it. Show inflow curving on a rotating sphere.", "category": "atmospheric_optics"},
    {"prompt": "Lenticular clouds stand still in a moving wind. Air forced over a mountain oscillates downstream as a standing gravity wave; cloud condenses at every crest and evaporates in every trough, so the cloud holds position while the air rushes through it. Show the streamlines and the fixed condensation zone.", "category": "atmospheric_optics"},
    {"prompt": "Frost flowers grow from vapour, not from liquid. Water molecules deposit straight from gas to solid on a freezing surface, and the delicate curls follow the crystal lattice with no liquid stage at all. Show deposition building a ribbon.", "category": "water_and_ice"},
    {"prompt": "The Mpemba effect, and why it is still argued about. Hot water sometimes freezes before cold, with candidate explanations from evaporative mass loss to dissolved gas to supercooling statistics — and replication is genuinely inconsistent. Show the competing mechanisms and say plainly which is unsettled.", "category": "water_and_ice"},
    {"prompt": "Gravitational lensing. Mass curves spacetime, light follows the curve, and a galaxy behind a cluster can appear as an arc or a full Einstein ring. Show the deflection geometry and the ring forming as the alignment closes.", "category": "astronomy"},
    {"prompt": "How stellar parallax measures distance. Earth moves 2 astronomical units across its orbit in six months; a nearby star shifts against the background by under one arcsecond, which is the definition of the parsec. Show the baseline and the tiny angle at true proportion.", "category": "astronomy"},
    {"prompt": "How we know Earth has a liquid core. S waves are shear waves and cannot cross a liquid, so they leave a shadow zone beyond 103 degrees from any quake, while P waves refract through and reappear. Show both raypaths and the shadow.", "category": "geology"},
    {"prompt": "How a cave forms. Rain picks up carbon dioxide, becomes weak carbonic acid, and dissolves limestone along joints; flow concentrates in whichever crack widens fastest, so one passage wins and the rest stay hairline. Show the positive feedback selecting a single conduit.", "category": "geology"},
    {"prompt": "Snell's law, and why a spoon looks bent in water. Light changes speed at the boundary and the wavefront pivots; the ratio of sines equals the ratio of indices, 1.00 to 1.33 for air to water. Show the wavefront turning at the interface.", "category": "waves"},
    {"prompt": "A Lichtenberg figure is diffusion-limited aggregation. Charge random-walks until it touches the growing structure and sticks; tips shield the interior, so branches never fill in. The same rule draws a lightning path, a frost fern and a copper dendrite. Run the growth.", "category": "emergence"},
    {"prompt": "Osmosis is statistics, not attraction. Water crosses a semipermeable membrane in both directions, but more often from the dilute side because more of it is there; the height the column climbs measures the osmotic pressure. Show molecules crossing both ways and the imbalance.", "category": "emergence"},
    {"prompt": "Why foam bubbles meet at 120 degrees. Plateau: three films meet along an edge at exactly 120 degrees and four edges meet at a vertex at 109.47 degrees, because any other angle has more surface area to shed. Show a foam relaxing into those angles.", "category": "emergence"},
    {"prompt": "Shape memory alloys. Nitinol deforms by shearing between two crystal structures rather than by breaking bonds; heat it past the transition and every unit cell snaps back to the austenite arrangement, taking the whole shape with it. Show the lattice on both sides.", "category": "matter"},
    {"prompt": "Piezoelectricity. Squeeze a quartz crystal and its lattice loses its charge symmetry, producing volts across the faces; drive it with volts and it deforms, which is how a watch keeps 32,768 ticks a second. Show the unit cell distorting both ways.", "category": "matter"},
    {"prompt": "Why a river carves a canyon upstream. A knickpoint — a step in the riverbed — erodes fastest at its lip and migrates headward, so the canyon lengthens backwards while the mouth stays put. Show the knickpoint retreating over a hundred thousand years.", "category": "geology"},
]

CATEGORIES_NOTE = """
Every topic above is a MECHANISM with a visual and at least one defensible
number. None is a list of facts, and none is naturally a bar chart -- those
belong in the STEM queue, which a different renderer serves.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print, send nothing")
    ap.add_argument("--limit", type=int, default=0, help="enqueue only the first N")
    ap.add_argument("--queue", default=QUEUE_NAME)
    args = ap.parse_args()

    topics = TOPICS[: args.limit] if args.limit else TOPICS

    seen = {}
    for t in topics:
        seen.setdefault(t["prompt"][:60], 0)
        seen[t["prompt"][:60]] += 1
    dupes = [k for k, v in seen.items() if v > 1]
    if dupes:
        sys.exit(f"duplicate prompts: {dupes}")

    cats = {}
    for t in topics:
        cats[t["category"]] = cats.get(t["category"], 0) + 1
    print(f"{len(topics)} topics across {len(cats)} categories:")
    for c, n in sorted(cats.items(), key=lambda kv: -kv[1]):
        print(f"  {c:24s} {n}")

    if args.dry_run:
        print("\n--dry-run: nothing sent")
        for t in topics[:3]:
            print(f"\n[{t['category']}] {t['prompt'][:150]}...")
        return 0

    sqs = boto3.client("sqs")
    url = sqs.get_queue_url(QueueName=args.queue)["QueueUrl"]

    # send_message_batch takes 10 at a time; one bad entry fails only its own
    # entry, so the failures are collected rather than assumed away.
    sent, failed = 0, []
    for i in range(0, len(topics), 10):
        chunk = topics[i: i + 10]
        resp = sqs.send_message_batch(
            QueueUrl=url,
            Entries=[{"Id": str(i + j), "MessageBody": json.dumps(t)}
                     for j, t in enumerate(chunk)],
        )
        sent += len(resp.get("Successful", []))
        failed += resp.get("Failed", [])

    print(f"\nsent {sent}/{len(topics)} to {args.queue}")
    if failed:
        print(f"FAILED {len(failed)}: {failed[:3]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
