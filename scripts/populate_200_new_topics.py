#!/usr/bin/env python3
"""Populate the STEM SQS queue with 200 NEW unique topics.

These do NOT overlap with scripts/populate_200_topics.py — they follow the same
house style (Title — concept + twist + a concrete "Animate/Show ..." visual
direction) and the same 7 categories, but cover entirely different subjects.

Usage:
  python scripts/populate_200_new_topics.py             # enqueue all
  python scripts/populate_200_new_topics.py --dry-run   # print + count only
  python scripts/populate_200_new_topics.py --limit 50
"""

import os
import json
import uuid
import argparse
import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
QUEUE_NAME = "iris-flow-topic-queue"

TOPICS = [
    # ── PARADOXES (20) ───────────────────────────────────────────────────────
    {"prompt": "The Two-Envelope Paradox — you're handed one of two envelopes; one holds twice the other. Switching seems to always raise your expected value by 25%, so you'd swap forever. Animate the expectation calculation and reveal the hidden flaw in how the unknown amount is modeled.", "category": "paradoxes"},
    {"prompt": "The Bootstrap Paradox — a time traveler hands Beethoven a symphony from the future, who copies it down; so who actually composed it? Animate the causal loop where information exists with no origin, an object that is its own cause.", "category": "paradoxes"},
    {"prompt": "Zeno's Achilles and the Tortoise — Achilles can never overtake a tortoise because he must first reach where it was, by which time it has moved. Animate the shrinking gaps as an infinite geometric series that sums to a finite distance and a finite time.", "category": "paradoxes"},
    {"prompt": "Bertrand's Probability Paradox — what's the chance a random chord of a circle is longer than the triangle's side? Three reasonable methods give 1/2, 1/3, and 1/4. Animate all three constructions side by side to show why 'random' must be defined before it means anything.", "category": "paradoxes"},
    {"prompt": "The Berry Paradox — 'the smallest number not describable in under twelve words' just got described in eleven. Animate the self-referential trap and connect it to the limits of definability and Gödel-style incompleteness.", "category": "paradoxes"},
    {"prompt": "The Allais Paradox — people flip their preference between two gambles when a shared outcome is added, violating expected-utility theory. Animate the four lotteries and the certainty effect that makes humans predictably 'irrational'.", "category": "paradoxes"},
    {"prompt": "The Ellsberg Paradox — given an urn with unknown color proportions, people pay to avoid ambiguity even when it costs expected value. Animate the urn draws and show how ambiguity aversion breaks classical probability.", "category": "paradoxes"},
    {"prompt": "Buridan's Ass — a perfectly rational donkey placed exactly between two identical hay bales starves, unable to choose. Animate the symmetric decision and show how real systems break ties with noise, and why that matters for electronics and biology.", "category": "paradoxes"},
    {"prompt": "Hilbert's Grand Hotel — a fully booked hotel with infinitely many rooms still accommodates infinitely many new guests. Animate guests shuffling rooms to make space, illustrating that infinity plus infinity can still be infinity.", "category": "paradoxes"},
    {"prompt": "Thomson's Lamp — a lamp toggled at 1, 1/2, 1/4 seconds... is it on or off after two seconds? Animate the accelerating supertask and explore why the question may have no defined answer.", "category": "paradoxes"},
    {"prompt": "Curry's Paradox — a single self-referential sentence can 'prove' anything, like 'if this sentence is true, then dragons exist.' Animate the logical derivation step by step and show where naive truth assumptions collapse.", "category": "paradoxes"},
    {"prompt": "Russell's Paradox — does the set of all sets that don't contain themselves contain itself? Either answer contradicts. Animate the barber who shaves everyone who doesn't shave themselves, and how this broke naive set theory.", "category": "paradoxes"},
    {"prompt": "The Twin Paradox — one twin rockets away near light speed and returns younger, but motion is relative, so who really aged? Animate both worldlines on a spacetime diagram and show how acceleration breaks the symmetry.", "category": "paradoxes"},
    {"prompt": "The Condorcet Voting Paradox — majority preferences can cycle: A beats B, B beats C, and C beats A. Animate three voters ranking three options and the rock-paper-scissors loop that dooms simple majority rule.", "category": "paradoxes"},
    {"prompt": "Simpson's Paradox — a trend that appears in every subgroup can reverse when the groups are combined. Animate two scatter clouds whose within-group slopes point up while the merged slope points down, using a real medical example.", "category": "paradoxes"},
    {"prompt": "The Gibbs Paradox — mixing two identical gases seems to create entropy from nothing. Animate the partition removal and resolve it with the indistinguishability of identical particles, a hint of quantum statistics in classical thermodynamics.", "category": "paradoxes"},
    {"prompt": "The Will Rogers Phenomenon — moving one patient between two groups can raise the average survival of BOTH groups at once. Animate the reclassification and show how 'stage migration' fakes medical progress.", "category": "paradoxes"},
    {"prompt": "Bell's Spaceship Paradox — two ships connected by a taut string accelerate identically, yet the string snaps. Animate the length contraction in the launch frame and resolve why the distance and the string disagree.", "category": "paradoxes"},
    {"prompt": "Moravec's Paradox — it's easy to make computers play grandmaster chess but nearly impossible to give them a toddler's motor skills. Animate the inverted difficulty curve and what it reveals about a billion years of sensorimotor evolution.", "category": "paradoxes"},
    {"prompt": "The Paradox of the Court — Protagoras teaches a student who promises to pay after winning his first case; the student never takes a case, so the teacher sues. Animate the self-defeating contract where any verdict contradicts itself.", "category": "paradoxes"},

    # ── COUNTERINTUITIVE PHENOMENA (28) ──────────────────────────────────────
    {"prompt": "The Brazil Nut Effect — shake a can of mixed nuts and the largest rise to the top, defying density intuition. Animate the granular convection currents and void-filling that push big particles upward.", "category": "counterintuitive_phenomena"},
    {"prompt": "Einstein's Tea Leaf Paradox — stir a cup and the leaves gather in the center, not flung to the rim. Animate the secondary flow: friction at the bottom drives an inward spiral that herds the leaves.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Falling Slinky — release a hanging Slinky and its bottom hovers in midair until the collapsing top reaches it. Animate the tension wave traveling down while the center of mass falls normally.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Mpemba Effect — under the right conditions, hot water can freeze faster than cold. Animate competing explanations: evaporation, convection, dissolved gases, and supercooling, and why the effect is still debated.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Cheerio Effect — floating cereal clumps together and clings to the bowl's edge. Animate the menisci bending the water surface and the capillary forces that pull the pieces into each other.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Leidenfrost Effect — a water droplet skates across a screaming-hot pan, lasting far longer than on a warm one. Animate the insulating vapor cushion that levitates the drop above the surface.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Backwards Brain Bicycle — reverse the steering and a lifelong cyclist can't ride at all. Animate the entrenched motor program fighting the new rule, illustrating procedural memory and neuroplasticity.", "category": "counterintuitive_phenomena"},
    {"prompt": "Feather and Hammer on the Moon — dropped together in vacuum, they hit the ground at the same instant. Animate the absence of air resistance and the equivalence of gravitational and inertial mass.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Spinning Skater — pull your arms in and you spin faster, with no extra push. Animate conservation of angular momentum: shrinking the moment of inertia must speed the rotation.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Rubber Band Heat Engine — a stretched rubber band warms when pulled and cools when relaxed, and a heated band CONTRACTS. Animate the entropic elasticity of tangling polymer chains.", "category": "counterintuitive_phenomena"},
    {"prompt": "Supercooling and Instant Freezing — perfectly still water can drop below 0°C and stay liquid until a tap triggers an avalanche of ice. Animate nucleation spreading through the metastable liquid.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Chain Fountain (Mould Effect) — a chain poured from a beaker leaps up above the lip before falling. Animate the momentum kick from links being flung as they're picked up by the moving chain.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Falling Cat Problem — a cat dropped upside-down rights itself with zero initial angular momentum. Animate the counter-rotating front and back halves that turn the body without breaking conservation laws.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Iodine Clock Reaction — two clear liquids mixed stay clear, then snap to inky blue all at once. Animate the hidden reaction racing in the background until a threshold concentration triggers the color.", "category": "counterintuitive_phenomena"},
    {"prompt": "Apparent Weight in an Elevator — your bathroom scale reads heavier on the way up and lighter on the way down. Animate the normal force changing with acceleration while gravity stays the same.", "category": "counterintuitive_phenomena"},
    {"prompt": "Acoustic Beats — two slightly different tones combine into a pulsing throb. Animate the wave envelopes adding and canceling, and how piano tuners use the beat rate to hit pitch.", "category": "counterintuitive_phenomena"},
    {"prompt": "Liquid Rope Coiling — pour honey and the thin stream buckles into a neat spinning coil. Animate the viscous thread's compression instability and how the coiling frequency depends on height.", "category": "counterintuitive_phenomena"},
    {"prompt": "Why a Boomerang Returns — a spinning airfoil curves back to the thrower. Animate the asymmetric lift between the advancing and retreating arms and the gyroscopic precession that bends the path into a loop.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Stroop Effect — naming the ink color of a mismatched color word is shockingly hard. Animate the competing reading and color pathways and the cognitive interference that slows you down.", "category": "counterintuitive_phenomena"},
    {"prompt": "The McGurk Effect — what you see can override what you hear, changing the syllable you perceive. Animate the mismatched lip and audio cues fusing into a third sound your brain invents.", "category": "counterintuitive_phenomena"},
    {"prompt": "Huygens' Coupled Pendulums — clocks on a shared beam mysteriously synchronize, swinging in perfect anti-phase. Animate the tiny vibrations transferred through the support that lock the rhythms together.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Belousov-Zhabotinsky Reaction — a chemical mixture oscillates between colors and spawns spreading spiral waves, seemingly violating intuition about reactions settling down. Animate the feedback loops driving the chemical clock.", "category": "counterintuitive_phenomena"},
    {"prompt": "Soap-Powered Boats — a notch of soap at the stern propels a paper boat across water. Animate the Marangoni effect: lowering surface tension behind the boat lets the front pull it forward.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Gambler's Fallacy vs the Law of Large Numbers — past coin flips don't owe you anything, yet averages still converge. Animate why streaks are expected while the long-run ratio settles toward one half.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Hot Hand Reconsidered — once dismissed as illusion, basketball streak-shooting shows a real but tiny effect once selection bias is corrected. Animate the subtle statistical mistake that hid it for decades.", "category": "counterintuitive_phenomena"},
    {"prompt": "Diamagnetic Levitation — a live frog floats in a strong magnetic field because water is weakly repelled by magnets. Animate the induced opposing fields in every molecule that add up to lift.", "category": "counterintuitive_phenomena"},
    {"prompt": "Why the Sky Polarizes — scattered sunlight is polarized in a pattern across the sky that bees and Vikings could read for navigation. Animate the scattering geometry and the band of maximum polarization 90° from the sun.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Placebo Effect, Quantified — an inert pill can measurably reduce pain, and the effect scales with ritual, color, and price. Animate the expectation-driven release of endorphins and the dopamine reward loop.", "category": "counterintuitive_phenomena"},

    # ── ELEGANT THEOREMS (28) ────────────────────────────────────────────────
    {"prompt": "The Four Color Theorem — every map can be colored with just four colors so no neighbors match. Animate the coloring of a tricky map and tell the story of the first major proof done by computer.", "category": "elegant_theorems"},
    {"prompt": "Fermat's Little Theorem — for a prime p, a^p and a leave the same remainder mod p. Animate the necklace-counting proof and show how it powers modern primality testing.", "category": "elegant_theorems"},
    {"prompt": "Wilson's Theorem — a number p is prime exactly when (p-1)! + 1 is divisible by p. Animate the pairing of inverses in modular arithmetic that leaves only 1 and p-1 unmatched.", "category": "elegant_theorems"},
    {"prompt": "The Chinese Remainder Theorem — knowing a number's remainders by coprime moduli pins it down uniquely. Animate gears of different sizes aligning to a single position and its use in cryptography.", "category": "elegant_theorems"},
    {"prompt": "Cantor's Diagonal Argument — the real numbers are uncountable, a bigger infinity than the integers. Animate building a number that differs from every row of a supposed complete list, defeating it by construction.", "category": "elegant_theorems"},
    {"prompt": "The Borsuk-Ulam Theorem — at any moment, two antipodal points on Earth share the same temperature and pressure. Animate the continuous map from a sphere to a plane and why a collision is unavoidable.", "category": "elegant_theorems"},
    {"prompt": "The Fundamental Theorem of Algebra — every non-constant polynomial has a root in the complex numbers. Animate how the image of a large circle winds around the origin, forcing a zero inside.", "category": "elegant_theorems"},
    {"prompt": "The Fundamental Theorem of Calculus — differentiation and integration are inverse operations. Animate the area under a curve growing and how its rate of change reconstructs the original function.", "category": "elegant_theorems"},
    {"prompt": "Noether's Theorem — every continuous symmetry of a physical system yields a conservation law. Animate time-symmetry giving energy, space-symmetry giving momentum, rotation giving angular momentum.", "category": "elegant_theorems"},
    {"prompt": "The Cauchy-Schwarz Inequality — the dot product can never exceed the product of lengths. Animate the projection of one vector onto another and the geometric meaning of equality.", "category": "elegant_theorems"},
    {"prompt": "The AM-GM Inequality — the arithmetic mean of positive numbers is always at least their geometric mean. Animate the visual proof with rectangles and a square, and where equality is forced.", "category": "elegant_theorems"},
    {"prompt": "Green's Theorem — a loop integral around a region equals a double integral over its interior. Animate tiny circulating cells inside a boundary canceling internally and summing to the edge flow.", "category": "elegant_theorems"},
    {"prompt": "Stokes' Theorem — the grand unifier where flux through a surface equals circulation around its edge. Animate curl arrows over a curved cap reducing to a single loop integral on the rim.", "category": "elegant_theorems"},
    {"prompt": "The Residue Theorem — a contour integral in the complex plane is just 2πi times the sum of enclosed residues. Animate poles as tiny whirlpools and the loop tightening around each one.", "category": "elegant_theorems"},
    {"prompt": "The Prime Number Theorem — the density of primes near n thins out like 1/ln(n). Animate the staircase of prime counts hugging the smooth logarithmic-integral curve.", "category": "elegant_theorems"},
    {"prompt": "The Max-Flow Min-Cut Theorem — the most you can push through a network equals the cheapest set of pipes to sever it. Animate flow saturating a graph and the bottleneck cut emerging.", "category": "elegant_theorems"},
    {"prompt": "Hall's Marriage Theorem — a perfect matching exists exactly when no group of applicants collectively wants too few jobs. Animate the bipartite graph and the deficient set that blocks a match.", "category": "elegant_theorems"},
    {"prompt": "The Cayley-Hamilton Theorem — every square matrix satisfies its own characteristic polynomial. Animate a transformation 'undoing' itself and how this shortcuts computing inverses and powers.", "category": "elegant_theorems"},
    {"prompt": "The Perron-Frobenius Theorem — a positive matrix has a dominant real eigenvalue with a positive eigenvector. Animate repeated multiplication pulling any vector toward that steady state, the math behind PageRank and population models.", "category": "elegant_theorems"},
    {"prompt": "The Spectral Theorem — every symmetric matrix has an orthogonal basis of real eigenvectors. Animate an ellipsoid's principal axes appearing as the natural coordinate frame of the transformation.", "category": "elegant_theorems"},
    {"prompt": "The Cantor-Schröder-Bernstein Theorem — if two sets inject into each other, they have the same size. Animate the back-and-forth chains that stitch together an exact bijection.", "category": "elegant_theorems"},
    {"prompt": "The Sylvester-Gallai Theorem — any finite set of points, not all on one line, has a line through exactly two of them. Animate the clever 'closest point to a line' argument that forces it.", "category": "elegant_theorems"},
    {"prompt": "Euler's Identity Derived — e^(iπ) + 1 = 0 ties together five fundamental constants. Animate a point spiraling around the unit circle as the exponential rotates it to land exactly at -1.", "category": "elegant_theorems"},
    {"prompt": "Liouville's Theorem — a bounded function that's differentiable everywhere in the complex plane must be constant. Animate why complex 'niceness' is so rigid it forbids interesting bounded behavior.", "category": "elegant_theorems"},
    {"prompt": "Dirichlet's Theorem on Primes — every arithmetic progression with coprime start and step contains infinitely many primes. Animate primes peppered along the sequence 1, 5, 9, 13... never running out.", "category": "elegant_theorems"},
    {"prompt": "Helly's Theorem — if every three of your convex sets share a point, they all share one. Animate overlapping disks in the plane and the surprising jump from local to global intersection.", "category": "elegant_theorems"},
    {"prompt": "The Erdős-Ko-Rado Theorem — the largest family of pairwise-intersecting k-subsets is just all sets containing a fixed element. Animate the sunflower of subsets sharing one common petal.", "category": "elegant_theorems"},
    {"prompt": "Sperner's Lemma — any proper coloring of a triangulated triangle forces a fully tri-colored small triangle, a combinatorial cousin of Brouwer's fixed point. Animate the parity-counting walk that finds it.", "category": "elegant_theorems"},

    # ── MATHEMATICAL PATTERNS (28) ───────────────────────────────────────────
    {"prompt": "Pascal's Triangle Mod 2 — color the odd entries and the Sierpinski triangle emerges from pure arithmetic. Animate the rows building up and the fractal self-similarity revealing itself.", "category": "mathematical_patterns"},
    {"prompt": "The Collatz Conjecture — pick any number, halve it if even or triple-plus-one if odd, and you always crash to 1. Animate the hailstone trajectories soaring and plunging, an unsolved problem hiding in grade-school arithmetic.", "category": "mathematical_patterns"},
    {"prompt": "The Thue-Morse Sequence — 0110100110010110... the fairest way to share turns, used in tournament seeding. Animate its self-similar generation and its appearance in chess and coin-fair division.", "category": "mathematical_patterns"},
    {"prompt": "The Recamán Sequence — jump back if you can, else jump forward, and a haunting arc pattern emerges. Animate the leaping number line and the nested semicircles it traces.", "category": "mathematical_patterns"},
    {"prompt": "The Chaos Game — plot points by repeatedly jumping halfway to a random triangle vertex, and the Sierpinski triangle materializes from randomness. Animate the dots accumulating into perfect structure.", "category": "mathematical_patterns"},
    {"prompt": "The Barnsley Fern — four simple affine maps applied at random draw a photorealistic fern. Animate the iterated function system filling in frond by frond.", "category": "mathematical_patterns"},
    {"prompt": "L-Systems and Plant Growth — a few rewriting rules grow trees, weeds, and snowflakes from a single symbol. Animate the string rewriting and the turtle that draws it into a branching plant.", "category": "mathematical_patterns"},
    {"prompt": "The Weierstrass Function — a curve that's continuous everywhere yet has a sharp corner at every single point. Animate zooming in forever and never finding a smooth piece.", "category": "mathematical_patterns"},
    {"prompt": "The Cantor Set — remove the middle third forever and you're left with uncountably many points of zero total length. Animate the gaps opening up and the dust that remains.", "category": "mathematical_patterns"},
    {"prompt": "Times-Table Cardioids — draw chords on a circle from n to 2n mod N and a glowing cardioid blooms; change the multiplier for nested petals. Animate the multiplication table becoming art.", "category": "mathematical_patterns"},
    {"prompt": "The Kolakoski Sequence — a sequence of 1s and 2s that describes its own run lengths. Animate it generating itself and the eerie self-reference with no known formula.", "category": "mathematical_patterns"},
    {"prompt": "Perfect Numbers and Mersenne Primes — 6, 28, 496 equal the sum of their divisors, each tied to a Mersenne prime. Animate the divisor blocks tiling back into the number and the still-open question of odd perfects.", "category": "mathematical_patterns"},
    {"prompt": "Figurate Numbers — triangular, square, and pentagonal numbers as literal arrangements of dots, with identities you can see. Animate triangular numbers stacking into squares and Gauss's instant summation trick.", "category": "mathematical_patterns"},
    {"prompt": "The Euler Spiral (Clothoid) — the curve whose curvature grows linearly, used to design highway ramps and roller coasters so you don't jerk. Animate the steering wheel turning at constant rate as the road bends.", "category": "mathematical_patterns"},
    {"prompt": "Truchet Tiles — square tiles with simple arcs, laid randomly, weave sprawling mazes and loops. Animate the tiles flipping and the emergent labyrinth of connected curves.", "category": "mathematical_patterns"},
    {"prompt": "Pythagorean Triples Tree — every primitive right-triangle triple descends from (3,4,5) via three matrix moves. Animate the infinite ternary tree branching out to generate them all.", "category": "mathematical_patterns"},
    {"prompt": "The Logarithmic Spiral in Nature — nautilus shells, hurricanes, and galaxies all trace the self-similar spiral that grows without changing shape. Animate the constant-angle growth and why it recurs everywhere.", "category": "mathematical_patterns"},
    {"prompt": "Magic Squares — grids where every row, column, and diagonal sum alike, from Lo Shu to Dürer. Animate the construction rules and the hidden algebra of their symmetries.", "category": "mathematical_patterns"},
    {"prompt": "The Plastic Number and Padovan Sequence — the 3D cousin of the golden ratio, governing a spiral of equilateral triangles. Animate the triangles winding outward and the ratio they converge to.", "category": "mathematical_patterns"},
    {"prompt": "Continued Fractions and the Most Irrational Number — why the golden ratio is the hardest number to approximate by fractions. Animate its all-ones continued fraction and the worst-case rational approximations.", "category": "mathematical_patterns"},
    {"prompt": "The Gosper Flowsnake — a space-filling fractal curve that tiles the plane with hexagonal islands. Animate each iteration replacing segments and the curve folding to fill space.", "category": "mathematical_patterns"},
    {"prompt": "Aliquot Sequences and Amicable Numbers — 220 and 284 each sum to the other's divisors; iterate divisor-sums and watch numbers spiral, loop, or vanish. Animate the trajectories and their unsolved fate.", "category": "mathematical_patterns"},
    {"prompt": "The Dragon Curve's Hidden Order — fold a strip of paper repeatedly and unfold to reveal a self-tiling fractal. Animate the fold sequence as binary and the curve assembling without ever crossing.", "category": "mathematical_patterns"},
    {"prompt": "Newton's Fractal — color each point by which root Newton's method lands on, and stunning basins appear. Animate the iteration flowing across the plane and the fractal boundaries between basins.", "category": "mathematical_patterns"},
    {"prompt": "The Rule 90 and Pascal Connection — a one-dimensional cellular automaton draws Sierpinski from a single seed. Animate each generation as an XOR of neighbors building the triangle downward.", "category": "mathematical_patterns"},
    {"prompt": "Lehmer's Pentagonal Number Pattern — Euler's pentagonal number theorem makes most terms in a key infinite product cancel. Animate the sparse surviving terms and their link to counting partitions.", "category": "mathematical_patterns"},
    {"prompt": "The Vicsek Fractal — a plus-shaped self-replicating pattern with fractal dimension between 1 and 2. Animate the cross subdividing into five smaller crosses, forever.", "category": "mathematical_patterns"},
    {"prompt": "Sum of Cubes Equals Square of Sums — 1³+2³+...+n³ = (1+2+...+n)². Animate nested L-shaped shells tiling a perfect square to prove Nicomachus's identity without algebra.", "category": "mathematical_patterns"},

    # ── PHYSICS PHENOMENA (38) ───────────────────────────────────────────────
    {"prompt": "Superfluid Helium and the Fountain Effect — cooled below 2 kelvin, helium climbs walls and squirts in a fountain with zero viscosity. Animate the frictionless film creeping up and over the container rim.", "category": "physics_phenomena"},
    {"prompt": "The Aharonov-Bohm Effect — an electron's phase shifts from a magnetic field it never touches. Animate the two-path interference and how the vector potential, not the field, does the work.", "category": "physics_phenomena"},
    {"prompt": "The Quantum Zeno Effect — watching a quantum system constantly can freeze it from changing. Animate repeated measurements collapsing the wavefunction back and stalling decay.", "category": "physics_phenomena"},
    {"prompt": "The Sagnac Effect — light sent both ways around a rotating loop returns out of step, the basis of laser gyroscopes. Animate the counter-propagating beams and the rotation-induced phase shift.", "category": "physics_phenomena"},
    {"prompt": "Hawking Radiation — black holes slowly evaporate as quantum pairs split at the horizon. Animate virtual particles separating, one falling in with negative energy, the other escaping as glow.", "category": "physics_phenomena"},
    {"prompt": "The Stern-Gerlach Experiment — silver atoms through a magnetic field split into two discrete beams, proving spin is quantized. Animate the atoms deflecting up or down with nothing in between.", "category": "physics_phenomena"},
    {"prompt": "The Compton Effect — X-rays bounce off electrons and come back redder, proving light carries momentum like a particle. Animate the photon-electron collision and the wavelength shift with angle.", "category": "physics_phenomena"},
    {"prompt": "The Zeeman Effect — a magnetic field splits a single spectral line into several. Animate the energy levels fanning out and how astronomers use it to measure starspot magnetism.", "category": "physics_phenomena"},
    {"prompt": "Total Internal Reflection and Evanescent Waves — light trapped in glass still leaks a fading field across the boundary. Animate the bouncing ray and the ghostly evanescent wave that enables fiber sensors.", "category": "physics_phenomena"},
    {"prompt": "Bragg Diffraction — X-rays scatter off crystal planes and constructively interfere only at special angles, revealing atomic structure. Animate the wavefronts reflecting and the bright spots that map the lattice.", "category": "physics_phenomena"},
    {"prompt": "The Talbot Carpet — light through a grating re-images itself at regular distances, weaving a fractal 'carpet' of intensity. Animate the self-imaging planes and the nested interference pattern.", "category": "physics_phenomena"},
    {"prompt": "Cooper Pairs and Superconductivity — below a critical temperature, electrons team up and flow without resistance. Animate lattice vibrations gluing electrons into pairs that glide past impurities.", "category": "physics_phenomena"},
    {"prompt": "Josephson Junctions and SQUIDs — quantum current tunnels between two superconductors with no voltage, enabling the most sensitive magnetometers. Animate the phase difference driving the supercurrent.", "category": "physics_phenomena"},
    {"prompt": "The Seebeck and Peltier Effects — a temperature difference makes voltage, and a voltage makes a temperature difference. Animate charge carriers diffusing from hot to cold and the solid-state heat pump it builds.", "category": "physics_phenomena"},
    {"prompt": "Plasmon Resonance and Stained Glass — gold nanoparticles scatter light by collective electron oscillation, coloring medieval windows ruby red. Animate the electron cloud sloshing at the resonant frequency.", "category": "physics_phenomena"},
    {"prompt": "The Gravitational Slingshot — a spacecraft steals a sliver of a planet's orbital speed to fling itself outward. Animate the velocity vectors adding in the Sun's frame while energy is conserved overall.", "category": "physics_phenomena"},
    {"prompt": "Tidal Locking — why the Moon shows Earth only one face forever. Animate the tidal bulge dragging until the spin and orbit periods match and the rotation freezes.", "category": "physics_phenomena"},
    {"prompt": "The Roche Limit — get too close to a planet and tides shred a moon into rings. Animate the differential gravity stretching a body until it can't hold itself together.", "category": "physics_phenomena"},
    {"prompt": "Lagrange Points and Halo Orbits — five gravitational sweet spots where a spacecraft can hover, home to the James Webb telescope. Animate the combined gravity-plus-rotation potential and its saddle points.", "category": "physics_phenomena"},
    {"prompt": "Magnetic Reconnection — tangled field lines snap and reconnect, hurling solar plasma into space. Animate the X-point where field lines break and dump magnetic energy into particle kinetic energy.", "category": "physics_phenomena"},
    {"prompt": "Neutrino Oscillation — neutrinos shape-shift between three flavors as they fly, proving they have mass. Animate the quantum mixing and the disappearing solar neutrinos that revealed it.", "category": "physics_phenomena"},
    {"prompt": "The Pound-Rebka Experiment — light climbing out of Earth's gravity loses energy, redshifting just as relativity predicts. Animate photons crawling up a tower and the tiny frequency drop measured.", "category": "physics_phenomena"},
    {"prompt": "Faraday Rotation — a magnetic field twists the polarization of light passing through a medium. Animate the rotating polarization vector and its use to map cosmic magnetic fields.", "category": "physics_phenomena"},
    {"prompt": "The Barkhausen Effect — magnetize iron slowly and it clicks in discrete jumps as domains flip. Animate the magnetic domains snapping into alignment in audible avalanches.", "category": "physics_phenomena"},
    {"prompt": "Spin Ice and Emergent Monopoles — in certain crystals, magnetic excitations behave like isolated north and south poles. Animate the frustrated spins and the monopole-like defects wandering free.", "category": "physics_phenomena"},
    {"prompt": "The Fractional Quantum Hall Effect — electrons in a strong field act like particles with fractional charge. Animate the quantized plateaus and the strange collective excitations.", "category": "physics_phenomena"},
    {"prompt": "Larmor Precession and MRI — atomic spins wobble around a magnetic field at a precise frequency that medical scanners listen for. Animate the precessing magnetization and the resonant radio pulse.", "category": "physics_phenomena"},
    {"prompt": "Pair Production — a high-energy photon near a nucleus vanishes and becomes an electron-positron pair. Animate energy turning into matter and the conservation laws that govern it.", "category": "physics_phenomena"},
    {"prompt": "Bremsstrahlung — a charged particle braking near a nucleus radiates a continuous X-ray spectrum. Animate the decelerating electron shedding photons, the glow behind every X-ray tube.", "category": "physics_phenomena"},
    {"prompt": "The Casimir-Polder Force — two neutral plates in vacuum get pushed together by quantum fluctuations. Animate the suppressed vacuum modes between the plates creating a net inward pressure.", "category": "physics_phenomena"},
    {"prompt": "Diamagnetic Pyrolytic Graphite — a thin flake floats permanently above magnets at room temperature. Animate the induced repulsive currents and stable levitation without superconductivity.", "category": "physics_phenomena"},
    {"prompt": "The Kapitza Pendulum — vibrate a pendulum's pivot fast enough and it balances upside-down, stable. Animate the rapid drive averaging into an effective restoring force at the inverted point.", "category": "physics_phenomena"},
    {"prompt": "Whistler Waves — lightning launches radio waves that spiral along Earth's field lines and arrive as descending whistles. Animate the dispersion stretching the pulse into a falling tone.", "category": "physics_phenomena"},
    {"prompt": "The Penrose Process — energy can be extracted from a spinning black hole's ergosphere. Animate an object splitting so one piece falls in with negative energy and the other escapes enriched.", "category": "physics_phenomena"},
    {"prompt": "Superradiance — a black hole or rotating cylinder can amplify waves that scatter off it, stealing rotational energy. Animate the incoming wave leaving stronger than it arrived.", "category": "physics_phenomena"},
    {"prompt": "Cherenkov-Free Vavilov Glow vs Scintillation — how particle detectors turn invisible radiation into light by two different mechanisms. Animate ionization trails sparking flashes a camera can count.", "category": "physics_phenomena"},
    {"prompt": "The Magnetocaloric Effect — magnetize a special alloy and it heats; remove the field and it cools, enabling magnet-driven refrigeration. Animate spins aligning and the entropy dumping as heat.", "category": "physics_phenomena"},
    {"prompt": "Critical Opalescence — near a liquid-gas critical point, a clear fluid turns milky as density fluctuations grow to the size of light's wavelength. Animate the swelling fluctuations scattering every color.", "category": "physics_phenomena"},

    # ── REAL-WORLD APPLICATIONS (38) ─────────────────────────────────────────
    {"prompt": "How Capacitive Touchscreens Sense Your Finger — a grid of electrodes detects the tiny charge your skin steals. Animate the changing capacitance at the touch point and how multitouch is triangulated.", "category": "real_world_applications"},
    {"prompt": "How Transformers Predict the Next Word — self-attention lets a model weigh every word against every other. Animate the attention matrix lighting up the relevant context that shapes the prediction.", "category": "real_world_applications"},
    {"prompt": "How Huffman Coding Compresses Files — frequent symbols get short codes, rare ones get long codes. Animate the binary tree building bottom-up from symbol frequencies and the bitstream shrinking.", "category": "real_world_applications"},
    {"prompt": "How A* Finds the Shortest Path — Dijkstra plus a heuristic that aims toward the goal. Animate the search frontier expanding efficiently toward the target instead of in all directions.", "category": "real_world_applications"},
    {"prompt": "How PageRank Ranked the Early Web — a page is important if important pages link to it, solved as an eigenvector. Animate the random surfer's probability flowing across links to a steady state.", "category": "real_world_applications"},
    {"prompt": "How HDR Photography Merges Exposures — combine dark and bright shots to capture a scene's full range. Animate aligning frames and tone-mapping the merged radiance back to a viewable image.", "category": "real_world_applications"},
    {"prompt": "How Anti-Lock Brakes Work — sensors detect a locking wheel and pulse the brakes dozens of times a second. Animate the slip ratio and the feedback loop keeping tires in their grippiest zone.", "category": "real_world_applications"},
    {"prompt": "How Drones Stay Level — fusing gyroscope and accelerometer data with a complementary or Kalman filter. Animate the noisy sensors combining into a clean attitude estimate that the motors correct to.", "category": "real_world_applications"},
    {"prompt": "How Bluetooth Survives Interference — frequency hopping spread spectrum jumps channels 1,600 times a second. Animate the synchronized hop pattern dodging a crowded 2.4 GHz band.", "category": "real_world_applications"},
    {"prompt": "How 5G Packs Data with OFDM — thousands of orthogonal subcarriers carry data in parallel without interfering. Animate the overlapping sinc spectra whose peaks land on each other's nulls.", "category": "real_world_applications"},
    {"prompt": "How Video Codecs Predict Motion — H.264 stores only the differences between frames using motion vectors. Animate blocks being matched and shifted from the previous frame, leaving tiny residuals.", "category": "real_world_applications"},
    {"prompt": "How Ray Tracing Renders Light — cast rays from the eye and bounce them through a scene to compute color. Animate rays reflecting, refracting, and finding light sources for photorealistic shadows.", "category": "real_world_applications"},
    {"prompt": "How Robot Arms Reach a Target — inverse kinematics solves the joint angles for a desired hand position. Animate the arm's configuration space and the solver converging onto a pose.", "category": "real_world_applications"},
    {"prompt": "How SLAM Maps an Unknown Room — a robot builds a map and locates itself within it at the same time. Animate landmarks accumulating and the loop-closure correction snapping the map straight.", "category": "real_world_applications"},
    {"prompt": "How Bloom Filters Check Membership — a compact bit array answers 'definitely not' or 'probably yes' with no false negatives. Animate hashing an item to several bits and the space savings versus error tradeoff.", "category": "real_world_applications"},
    {"prompt": "How Consistent Hashing Balances Servers — place servers and keys on a ring so adding a node moves minimal data. Animate keys reassigning to the next node clockwise as the cluster grows.", "category": "real_world_applications"},
    {"prompt": "How TCP Avoids Congestion — senders ramp up until loss, then back off, sharing bandwidth fairly. Animate the sawtooth congestion window probing for the network's capacity.", "category": "real_world_applications"},
    {"prompt": "How Elliptic Curve Cryptography Shrinks Keys — point addition on a curve creates a one-way trapdoor stronger per bit than RSA. Animate the chord-and-tangent group law and scalar multiplication.", "category": "real_world_applications"},
    {"prompt": "How Shor's Algorithm Threatens RSA — a quantum computer factors huge numbers by finding a period with the Fourier transform. Animate the interference that amplifies the right period and cracks the key.", "category": "real_world_applications"},
    {"prompt": "How Quantum Key Distribution Stays Unbreakable — any eavesdropper disturbs the photons and gets caught. Animate the polarized qubits and the basis-comparison that reveals tampering.", "category": "real_world_applications"},
    {"prompt": "How MP3 Throws Away Sound You Can't Hear — psychoacoustic masking drops frequencies hidden by louder ones. Animate the masking curve and the bits saved by deleting the inaudible.", "category": "real_world_applications"},
    {"prompt": "How Maglev Trains Float and Fly — magnets levitate the train and a moving field pulls it forward. Animate the repulsion lifting the car and the linear motor's traveling wave of force.", "category": "real_world_applications"},
    {"prompt": "How Wireless Charging Couples Coils — a changing magnetic field induces current across an air gap. Animate the resonant coils exchanging energy and why alignment and frequency matter.", "category": "real_world_applications"},
    {"prompt": "How Heat Pumps Beat 100% Efficiency — they move heat instead of making it, delivering more energy than they consume. Animate the refrigeration cycle pumping warmth from cold outdoor air into your home.", "category": "real_world_applications"},
    {"prompt": "How Reverse Osmosis Desalinates Seawater — pressure forces water through a membrane that blocks salt. Animate the molecules squeezing through while ions are turned away.", "category": "real_world_applications"},
    {"prompt": "How a Nuclear Reactor Controls Fission — control rods soak up neutrons to hold the chain reaction at exactly critical. Animate neutrons multiplying and the rods tuning the population to steady output.", "category": "real_world_applications"},
    {"prompt": "How Ultrasound Builds an Image — pulses of sound echo off tissue and timing reveals depth. Animate the beam sweeping and the echoes assembling into a live grayscale picture.", "category": "real_world_applications"},
    {"prompt": "How Pulse Oximeters Read Blood Oxygen — two light colors reveal how saturated your hemoglobin is. Animate the absorption difference between oxygenated and deoxygenated blood across the pulse.", "category": "real_world_applications"},
    {"prompt": "How Weather Models Assimilate Data — billions of observations are blended into a simulation to forecast the future. Animate the grid updating as new measurements nudge the model state.", "category": "real_world_applications"},
    {"prompt": "How Adaptive Optics Unblur Telescopes — a deformable mirror flexes thousands of times a second to cancel atmospheric turbulence. Animate the warped wavefront being flattened and the star snapping into focus.", "category": "real_world_applications"},
    {"prompt": "How Seismographs Locate an Earthquake — the gap between fast P-waves and slow S-waves gives distance from each station. Animate three circles intersecting to pinpoint the epicenter.", "category": "real_world_applications"},
    {"prompt": "How Rolling Shutter Distorts Fast Motion — a camera reads pixels row by row, bending spinning propellers and skewing speeding cars. Animate the scan line sweeping while the subject moves.", "category": "real_world_applications"},
    {"prompt": "How GPS Receivers Solve for Position — trilateration from four satellites' timing signals locates you and your clock error. Animate the spheres of constant distance intersecting at your spot.", "category": "real_world_applications"},
    {"prompt": "How the Raft Algorithm Keeps Databases Consistent — servers elect a leader and replicate a log to agree despite failures. Animate the election, heartbeat, and log replication reaching consensus.", "category": "real_world_applications"},
    {"prompt": "How FLAC Compresses Audio Losslessly — predict each sample from the previous ones and store only the small error. Animate the linear predictor tracking the waveform and the tiny residuals being packed.", "category": "real_world_applications"},
    {"prompt": "How Lossy JPEG Decides What to Cut — the discrete cosine transform sorts an image block into frequencies, then drops the high ones your eye ignores. Animate the block transforming and quantizing.", "category": "real_world_applications"},
    {"prompt": "How Self-Driving Cars Fuse Sensors — camera, radar, and lidar are combined into one confident world model. Animate each sensor's strengths covering the others' blind spots in a Kalman update.", "category": "real_world_applications"},
    {"prompt": "How Hash-Based Proof of Work Secures Blockchains — miners grind nonces to find a hash below a target, making history expensive to rewrite. Animate the difficulty target and the random search for a winning hash.", "category": "real_world_applications"},

    # ── GENERAL (20) ─────────────────────────────────────────────────────────
    {"prompt": "The Coupon Collector's Problem — how many random cereal boxes to complete a set of n toys? It grows like n·ln(n). Animate the slowing pace of finding the last few missing coupons.", "category": "general"},
    {"prompt": "The Josephus Problem — people in a circle eliminate every k-th person; where do you stand to survive? Animate the counting-out loop and the surprising closed-form for the safe seat.", "category": "general"},
    {"prompt": "The Dining Philosophers — five thinkers, five forks, and the deadlock when everyone grabs left first. Animate the circular wait and the clever resource ordering that prevents it.", "category": "general"},
    {"prompt": "The Byzantine Generals Problem — how to reach agreement when some messengers lie. Animate the conflicting messages and the threshold of honest nodes needed for consensus.", "category": "general"},
    {"prompt": "Schelling's Segregation Model — mild individual preferences for similar neighbors cascade into sharply divided cities. Animate agents relocating on a grid until stark patterns emerge from gentle bias.", "category": "general"},
    {"prompt": "The El Farol Bar Problem — everyone wants to go only if it won't be crowded, but they all reason the same way. Animate the oscillating attendance and how diverse strategies self-organize attendance near capacity.", "category": "general"},
    {"prompt": "Preferential Attachment — the rich get richer, producing scale-free networks with a few giant hubs. Animate new nodes preferentially linking to popular ones and the power-law degree distribution forming.", "category": "general"},
    {"prompt": "Percolation Thresholds — randomly fill a grid and at a critical density a path suddenly spans it, like a forest fire jumping. Animate clusters merging and the abrupt onset of global connectivity.", "category": "general"},
    {"prompt": "Why the Other Line Moves Faster — queueing theory shows that with parallel lines you're usually in a slower one by chance. Animate the M/M/1 versus M/M/c queues and the wait-time math.", "category": "general"},
    {"prompt": "Little's Law — the average number in any stable system equals arrival rate times time spent. Animate customers flowing through a shop and the elegant invariant linking the three quantities.", "category": "general"},
    {"prompt": "The Pirate Game — five rational pirates split gold by voting, and backward induction gives a shockingly greedy stable outcome. Animate the recursion from the last pirate up to the first proposer.", "category": "general"},
    {"prompt": "The Ultimatum Game — one player splits money, the other can reject and burn it all; fairness beats pure self-interest. Animate the offers and rejections that reveal humans punish unfairness.", "category": "general"},
    {"prompt": "Maxwell's Demon and the Cost of Information — a gate-keeping demon seems to break the second law until you account for the bits it stores. Animate sorting fast and slow molecules and the entropy of erasing memory.", "category": "general"},
    {"prompt": "Landauer's Principle — erasing a single bit must dissipate a tiny minimum of heat, linking information to thermodynamics. Animate the bit being reset and the unavoidable energy cost.", "category": "general"},
    {"prompt": "The Drake Equation — chaining factors to estimate how many civilizations might be broadcasting in our galaxy. Animate the multiplying terms and the staggering range of the result.", "category": "general"},
    {"prompt": "The Lindy Effect — for non-perishable things, the longer something has survived, the longer it's expected to last. Animate the survival curve and why old technologies and ideas keep outliving predictions.", "category": "general"},
    {"prompt": "Metcalfe's Law — a network's value grows roughly with the square of its users. Animate the connections exploding combinatorially as nodes join and why platforms tip to winners.", "category": "general"},
    {"prompt": "Nash Equilibrium and the Price of Anarchy — selfish routing can be far worse than a coordinated plan. Animate traffic choosing the 'best' road and the efficiency lost versus the social optimum.", "category": "general"},
    {"prompt": "The Newsvendor Problem — how many newspapers to stock when demand is uncertain and leftovers are worthless. Animate the cost of overstock versus stockout and the optimal order quantity.", "category": "general"},
    {"prompt": "Benford's Law from First Principles — why leading digits favor 1 far more than 9 across natural data. Animate numbers spanning orders of magnitude and the logarithmic spacing that creates the bias.", "category": "general"},
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--queue-url", default=os.environ.get("TOPIC_QUEUE_URL"))
    args = ap.parse_args()

    topics = TOPICS[: args.limit] if args.limit else TOPICS

    from collections import Counter
    cats = Counter(t["category"] for t in topics)
    print(f"{'DRY-RUN: ' if args.dry_run else ''}{len(topics)} new STEM topics")
    for k, v in cats.most_common():
        print(f"  {k}: {v}")

    if args.dry_run:
        return

    queue_url = args.queue_url
    sqs = boto3.client("sqs", region_name=REGION)
    if not queue_url:
        queue_url = sqs.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]

    sent = 0
    for t in topics:
        body = {"topic_id": str(uuid.uuid4())[:8], "prompt": t["prompt"], "category": t["category"]}
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))
        sent += 1
    print(f"Enqueued {sent} topics to {queue_url}")


if __name__ == "__main__":
    main()
