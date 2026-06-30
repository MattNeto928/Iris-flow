#!/usr/bin/env python3
"""Populate the STEM SQS queue with a large fresh batch of NEW unique topics.

These intentionally do NOT overlap with populate_200_topics.py or
populate_fresh_topics.py. ~130 concrete, single-concept prompts that can be
derived/visualized in ~90s with the iris-flow pipeline (manim / matplotlib /
plotly / networkx / title_card). Open with the concept, no "imagine if..."
framing.

Usage:
    python scripts/populate_mega_topics.py            # push all
    python scripts/populate_mega_topics.py --dry-run  # print count only
    python scripts/populate_mega_topics.py --limit 50 # push first N
"""

import argparse
import boto3
import json
import time
import uuid

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/482625028438/iris-flow-topic-queue"
REGION = "us-east-1"

TOPICS = [
    # ── NUMBER THEORY & DISCRETE MATH (10) ──────────────────────────────────────
    {"prompt": "The Euclidean algorithm for gcd. Animate gcd(1071, 462) as repeated subtraction, then as the faster modulo version. Show the sequence of remainders shrinking to zero and explain why the last nonzero remainder is the gcd.", "category": "algorithms"},
    {"prompt": "Modular exponentiation by squaring. Compute 7^13 mod 11 by writing 13 in binary and squaring-and-multiplying. Animate the running value and show why this turns an O(n) loop into O(log n) — the trick behind RSA.", "category": "cryptography"},
    {"prompt": "The Sieve of Eratosthenes. Animate a 10x10 grid, crossing out multiples of 2, then 3, then 5, then 7. The survivors light up as primes. Show why you only need to sieve up to the square root of N.", "category": "algorithms"},
    {"prompt": "Continued fractions and the golden ratio. Show that phi = 1 + 1/(1 + 1/(1 + ...)). Animate the convergents 1, 2, 3/2, 5/3, 8/5 — ratios of consecutive Fibonacci numbers — spiraling in on phi.", "category": "mathematical_patterns"},
    {"prompt": "The Chinese Remainder Theorem. Solve x = 2 mod 3, x = 3 mod 5, x = 2 mod 7. Animate the three residue cycles aligning on a number line and converging to x = 23 (mod 105).", "category": "cryptography"},
    {"prompt": "Pascal's triangle modulo 2 is the Sierpinski triangle. Color each entry by parity and animate row after row appearing. The fractal emerges with no fractal rule in sight — just binomial coefficients.", "category": "mathematical_patterns"},
    {"prompt": "Benford's law. The leading digit of naturally occurring numbers follows P(d) = log10(1 + 1/d), so 1 appears ~30% of the time. Plot leading-digit frequencies for populations, physical constants, and powers of 2, all matching the curve.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Collatz conjecture. Animate trajectories of n -> n/2 (even) or 3n+1 (odd) for several starting values, all eventually crashing to 1. Plot total stopping time vs starting number to show the chaotic spikes.", "category": "mathematical_patterns"},
    {"prompt": "Fermat's little theorem as a primality hint. Show a^(p-1) = 1 mod p for prime p, and how a composite usually fails it. Animate the Fermat test and explain Carmichael numbers as the rare liars.", "category": "cryptography"},
    {"prompt": "The Stern-Brocot tree enumerates every positive rational exactly once. Animate the mediant construction (a/b and c/d give (a+c)/(b+d)) building the tree level by level, with the Farey sequence appearing along each row.", "category": "mathematical_patterns"},

    # ── GEOMETRY & TOPOLOGY (9) ─────────────────────────────────────────────────
    {"prompt": "The Euler characteristic V - E + F = 2 for any convex polyhedron. Animate a cube, tetrahedron, and dodecahedron, counting vertices, edges, faces each time and landing on 2. Then show a torus gives 0.", "category": "elegant_theorems"},
    {"prompt": "Gaussian curvature and the Theorema Egregium. A flat piece of paper has zero curvature, so it can't wrap a sphere without distortion — but it rolls into a cylinder freely. Animate bending a sheet and show why pizza folds keep their tip rigid.", "category": "elegant_theorems"},
    {"prompt": "The Mobius strip has one side and one edge. Animate tracing a path along the surface returning flipped, then cutting down the middle to get one longer two-sided loop. Cut again at one-third width for a surprise.", "category": "counterintuitive_phenomena"},
    {"prompt": "Stereographic projection maps the sphere minus a point onto the plane, preserving circles and angles. Animate a grid on the plane lifting onto a sphere and the north-pole light source casting the projection.", "category": "mathematical_patterns"},
    {"prompt": "The Pythagorean theorem by rearrangement. Animate four right triangles sliding inside a square two ways: once leaving a c-square hole, once leaving an a-square plus b-square hole. Equal areas prove a^2 + b^2 = c^2.", "category": "elegant_theorems"},
    {"prompt": "Voronoi diagrams and Delaunay triangulation. Scatter 20 points, grow their cells until they tile the plane, then connect points sharing an edge to get the dual triangulation. Show the empty-circumcircle property.", "category": "algorithms"},
    {"prompt": "The Brachistochrone. The fastest slide between two points is a cycloid, not a straight line. Animate beads racing down a line, a circular arc, and the cycloid — the cycloid bead wins every time.", "category": "physics_phenomena"},
    {"prompt": "Dehn's solution to Hilbert's third problem: not all equal-volume polyhedra are scissor-congruent. Animate cutting a cube into a different shape, then show why a regular tetrahedron can't be rearranged into a cube.", "category": "elegant_theorems"},
    {"prompt": "Inscribed angle theorem. An angle subtended by a chord from the center is twice any angle subtended from the circle. Animate a point sliding around the arc keeping its angle constant while the central angle stays fixed.", "category": "elegant_theorems"},

    # ── PROBABILITY & STATISTICS (10) ───────────────────────────────────────────
    {"prompt": "Buffon's needle estimates pi. Drop needles of length L on lines spaced L apart; the fraction crossing a line is 2/pi. Animate 2000 drops and watch the running estimate converge to pi.", "category": "counterintuitive_phenomena"},
    {"prompt": "The German tank problem. From serial numbers of captured tanks, estimate the total produced as max + (max/n) - 1. Animate sampling from a hidden N and the estimator homing in as samples grow.", "category": "counterintuitive_phenomena"},
    {"prompt": "Markov chains and the stationary distribution. Build a 3-state weather model, animate a token hopping between states, and show the long-run fraction of time in each state converging to the left eigenvector of the transition matrix.", "category": "dynamical_systems"},
    {"prompt": "The bootstrap. Estimate the sampling distribution of the median by resampling one dataset with replacement thousands of times. Animate the histogram of bootstrap medians building up and the confidence interval emerging.", "category": "counterintuitive_phenomena"},
    {"prompt": "Simpson's paradox. A treatment can help in every subgroup yet hurt overall when group sizes differ. Animate two scatter clusters with positive within-group slopes but a negative pooled regression line.", "category": "counterintuitive_phenomena"},
    {"prompt": "The coupon collector problem. To collect all n coupons takes about n*ln(n) draws on average. Animate filling a collection of 50, with the wait for the last few coupons dominating the total.", "category": "counterintuitive_phenomena"},
    {"prompt": "Random walks and the gambler's ruin. A fair walk between 0 and N is absorbed at the boundaries; starting at k, ruin probability is (N-k)/N. Animate many walkers and the survival curve.", "category": "dynamical_systems"},
    {"prompt": "The exponential distribution is memoryless. Animate waiting times for a Poisson process and show that the expected remaining wait is the same no matter how long you've already waited.", "category": "counterintuitive_phenomena"},
    {"prompt": "Maximum likelihood estimation. Given coin flips, plot the likelihood of the bias p across [0,1] and animate the peak sliding to the observed heads fraction as more data arrives, sharpening each time.", "category": "statistical_mechanics"},
    {"prompt": "The law of the iterated logarithm. A random walk's fluctuations are bounded almost surely by sqrt(2n log log n). Animate a long walk with the shrinking envelope it keeps touching but never escaping.", "category": "counterintuitive_phenomena"},

    # ── COMPUTER SCIENCE & ALGORITHMS (11) ──────────────────────────────────────
    {"prompt": "Quicksort with the Lomuto partition. Animate picking a pivot, partitioning the array, then recursing on each side. Show the average O(n log n) versus the O(n^2) worst case on an already-sorted array.", "category": "algorithms"},
    {"prompt": "Merge sort. Animate splitting an array down to singletons, then merging sorted halves bottom-up. Highlight why the merge step is linear and the depth is log n.", "category": "algorithms"},
    {"prompt": "Binary search on a sorted array. Animate the lo/hi/mid pointers halving the search space each step, finding a target in log2(n) comparisons. Show what goes wrong if the array isn't sorted.", "category": "algorithms"},
    {"prompt": "Hash tables and collision resolution. Animate inserting keys with a hash function into buckets, a collision occurring, then resolving by chaining versus open addressing. Show load factor versus lookup time.", "category": "algorithms"},
    {"prompt": "Dynamic programming for the 0/1 knapsack. Build the value table row by row for items and capacities, then trace back the chosen items. Show the pseudo-polynomial O(nW) complexity.", "category": "algorithms"},
    {"prompt": "The A* search algorithm. On a grid with obstacles, animate the frontier expanding guided by f = g + h, finding the shortest path far faster than uniform-cost search. Show how the heuristic shapes exploration.", "category": "algorithms"},
    {"prompt": "Huffman coding. Given letter frequencies, build the optimal prefix tree by repeatedly merging the two least-frequent nodes. Animate the tree forming and read off the variable-length codes that minimize total bits.", "category": "information_theory"},
    {"prompt": "The Fast Fourier Transform via divide and conquer. Animate splitting a signal into even and odd samples, recursing, then combining with twiddle factors. Show the O(n log n) butterfly diagram replacing O(n^2).", "category": "algorithms"},
    {"prompt": "Bloom filters. A bit array plus k hash functions tests set membership with no false negatives but tunable false positives. Animate insertions setting bits and a query checking all k positions.", "category": "information_theory"},
    {"prompt": "Dijkstra versus Bellman-Ford on a weighted graph. Animate Dijkstra's greedy frontier, then show Bellman-Ford relaxing all edges V-1 times and catching a negative cycle Dijkstra would miss.", "category": "algorithms"},
    {"prompt": "The P vs NP question via the traveling salesman. Animate the explosion of tour permutations as cities grow, contrast with verifying a given tour in linear time, and show a nearest-neighbor heuristic's gap from optimal.", "category": "algorithms"},

    # ── CLASSICAL MECHANICS (9) ─────────────────────────────────────────────────
    {"prompt": "The Coriolis effect. On a rotating disk, a ball thrown straight curves in the rotating frame. Animate the same throw in inertial and rotating views and connect it to cyclone rotation directions by hemisphere.", "category": "physics_phenomena"},
    {"prompt": "Conservation of angular momentum. A spinning skater pulls in their arms and speeds up because L = I*omega is fixed. Animate moment of inertia shrinking and angular velocity rising, with the energy bookkeeping shown.", "category": "physics_phenomena"},
    {"prompt": "Kepler's second law: equal areas in equal times. Animate a planet on an ellipse sweeping area, fast at perihelion and slow at aphelion, with the swept sectors shown equal. Tie it to angular momentum conservation.", "category": "physics_phenomena"},
    {"prompt": "The tennis racket theorem (Dzhanibekov effect). Rotation about the intermediate principal axis is unstable. Animate a T-handle tumbling and flipping periodically in free fall while the other two axes stay stable.", "category": "counterintuitive_phenomena"},
    {"prompt": "Resonance in a driven oscillator. Sweep the driving frequency through the natural frequency and animate the amplitude blowing up at resonance, with damping setting the peak height and width (the Q factor).", "category": "physics_phenomena"},
    {"prompt": "Normal modes of coupled pendulums. Two pendulums joined by a spring oscillate as a symmetric in-phase mode and an antisymmetric mode. Animate energy sloshing back and forth as a beat between the two.", "category": "physics_phenomena"},
    {"prompt": "Escape velocity and orbital energy. Animate launches at increasing speed: suborbital, circular orbit, elliptical, then escape at sqrt(2) times circular speed. Plot total energy crossing zero at escape.", "category": "physics_phenomena"},
    {"prompt": "The gyroscope and precession. A spinning top doesn't fall; gravity's torque makes its axis sweep a cone. Animate the angular-momentum vector chasing the torque and derive the precession rate.", "category": "physics_phenomena"},
    {"prompt": "Tidal forces as a gradient of gravity. Animate the differential pull across a body producing two tidal bulges, and explain why there are two high tides a day, not one.", "category": "physics_phenomena"},

    # ── ELECTROMAGNETISM & OPTICS (9) ───────────────────────────────────────────
    {"prompt": "Faraday's law of induction. A magnet moving through a coil induces an EMF proportional to the rate of flux change. Animate flux lines threading the coil and the induced current opposing the change (Lenz's law).", "category": "physics_phenomena"},
    {"prompt": "Total internal reflection and the critical angle. Animate light rays in glass hitting the surface at increasing angles until, past the critical angle, all light reflects. Connect it to fiber optics.", "category": "physics_phenomena"},
    {"prompt": "Double-slit interference. Animate two coherent wave sources producing an interference pattern, with bright fringes where path difference is a whole number of wavelengths. Plot the resulting intensity.", "category": "physics_phenomena"},
    {"prompt": "Polarization and Malus's law. Light through two polarizers transmits intensity I0*cos^2(theta). Animate rotating the second polarizer and the brightness fading to zero at 90 degrees.", "category": "physics_phenomena"},
    {"prompt": "The electromagnetic wave from Maxwell's equations. Animate oscillating E and B fields perpendicular to each other and to the direction of travel, with the speed c = 1/sqrt(mu0*epsilon0) emerging.", "category": "physics_phenomena"},
    {"prompt": "Diffraction gratings split white light. Animate parallel slits producing sharp spectral orders, with longer wavelengths bending more. Show why a CD's tracks act as a reflection grating.", "category": "physics_phenomena"},
    {"prompt": "The Doppler effect for waves. Animate a moving source compressing wavefronts ahead and stretching them behind, raising and lowering observed frequency. Extend to redshift of receding galaxies.", "category": "physics_phenomena"},
    {"prompt": "Lenses and ray tracing. Animate the three principal rays through a converging lens forming a real image, then move the object inside the focal length to get a virtual magnified image. Show the thin-lens equation.", "category": "physics_phenomena"},
    {"prompt": "Cherenkov radiation. A charged particle moving faster than light's phase speed in a medium emits a shockwave of light at a fixed cone angle. Animate the expanding wavefronts forming the cone and the blue glow.", "category": "physics_phenomena"},

    # ── THERMODYNAMICS & STATISTICAL MECHANICS (9) ──────────────────────────────
    {"prompt": "The Maxwell-Boltzmann speed distribution. Simulate a 2D gas of colliding disks and build the histogram of speeds, converging to the Maxwell-Boltzmann curve. Show how raising temperature shifts and widens it.", "category": "statistical_mechanics"},
    {"prompt": "The Carnot cycle. Animate the P-V diagram through isothermal and adiabatic strokes, with heat in at the hot reservoir and out at the cold. Derive the maximum efficiency 1 - Tc/Th.", "category": "statistical_mechanics"},
    {"prompt": "Entropy and the arrow of time. Animate gas molecules initially in one corner spreading to fill a box, and show the overwhelming number of mixed microstates versus ordered ones makes the reverse essentially impossible.", "category": "statistical_mechanics"},
    {"prompt": "The Ising model of ferromagnetism. Run Metropolis Monte Carlo on a 2D spin lattice and animate cooling through the critical temperature, where domains suddenly align into spontaneous magnetization.", "category": "statistical_mechanics"},
    {"prompt": "Brownian motion and Einstein's relation. Animate a pollen grain jittered by molecular impacts, with mean-squared displacement growing linearly in time. Show how this proved atoms are real.", "category": "statistical_mechanics"},
    {"prompt": "Heat diffusion. Solve the 1D heat equation on a rod with hot and cold ends; animate the temperature profile relaxing to a straight-line steady state. Show how Fourier modes decay fastest at high frequency.", "category": "dynamical_systems"},
    {"prompt": "The Boltzmann distribution. Animate particles populating energy levels with probability proportional to exp(-E/kT), and show the population ratio between two levels changing as temperature rises.", "category": "statistical_mechanics"},
    {"prompt": "Phase transitions and latent heat. Animate heating ice through melting and water through boiling, with temperature plateauing while energy goes into breaking bonds. Plot the staircase heating curve.", "category": "statistical_mechanics"},
    {"prompt": "Percolation on a lattice. Randomly occupy sites with probability p and animate clusters merging; at the critical p_c a spanning cluster suddenly appears, connecting top to bottom. Plot cluster size vs p.", "category": "statistical_mechanics"},

    # ── QUANTUM & MODERN PHYSICS (9) ────────────────────────────────────────────
    {"prompt": "The particle in a box. Solve the infinite square well and animate the standing-wave eigenstates and quantized energy levels E_n proportional to n^2. Show why confinement forces discrete energies.", "category": "quantum_information"},
    {"prompt": "Quantum tunneling. Animate a wave packet hitting a barrier taller than its energy, with part of it leaking through. Plot transmission probability falling exponentially with barrier width.", "category": "quantum_information"},
    {"prompt": "The Heisenberg uncertainty principle. Animate a narrowing position wave packet and its widening momentum spread, with the product staying above hbar/2. Tie it to Fourier conjugate variables.", "category": "quantum_information"},
    {"prompt": "Bloch sphere representation of a qubit. Animate a single qubit state as a point on the sphere, with X, Y, Z rotations moving it, and measurement collapsing it to a pole. Show superposition on the equator.", "category": "quantum_information"},
    {"prompt": "Quantum entanglement and Bell states. Animate creating a two-qubit Bell pair, then measuring one and instantly fixing the other's correlation. Show the CHSH inequality being violated beyond the classical bound.", "category": "quantum_information"},
    {"prompt": "The photoelectric effect. Animate photons ejecting electrons only above a threshold frequency, with kinetic energy = h*f - work function. Plot the linear KE-vs-frequency line whose slope is Planck's constant.", "category": "physics_phenomena"},
    {"prompt": "The hydrogen atom spectrum. Animate electron transitions between energy levels emitting photons, producing the Balmer series lines. Show the Rydberg formula predicting each wavelength.", "category": "physics_phenomena"},
    {"prompt": "Grover's quantum search. Animate amplitude amplification rotating the state toward the marked item, finding it in about sqrt(N) steps instead of N. Show the amplitudes after each iteration.", "category": "quantum_information"},
    {"prompt": "Blackbody radiation and the ultraviolet catastrophe. Plot the classical Rayleigh-Jeans curve diverging at high frequency, then Planck's quantized fix matching the data. Show how quantization tamed the infinity.", "category": "physics_phenomena"},

    # ── RELATIVITY & COSMOLOGY (8) ──────────────────────────────────────────────
    {"prompt": "Time dilation from the light clock. Animate a photon bouncing between mirrors on a moving ship; the longer diagonal path means the moving clock ticks slower by the Lorentz factor gamma.", "category": "physics_phenomena"},
    {"prompt": "Length contraction and the ladder paradox. Animate a moving ladder fitting inside a shorter barn in one frame but not another, and resolve it with the relativity of simultaneity using a spacetime diagram.", "category": "counterintuitive_phenomena"},
    {"prompt": "Spacetime diagrams and the light cone. Animate worldlines, simultaneity slices tilting under a Lorentz boost, and the invariant interval staying fixed while space and time mix.", "category": "physics_phenomena"},
    {"prompt": "Gravitational time dilation. Clocks run slower deeper in a gravity well. Animate two clocks at different altitudes drifting apart and connect it to the corrections GPS satellites must apply.", "category": "physics_phenomena"},
    {"prompt": "The expanding universe and Hubble's law. Animate galaxies on a stretching grid, recession velocity proportional to distance, with no center. Plot velocity vs distance to extract the Hubble constant.", "category": "cosmology"},
    {"prompt": "Escape from a black hole and the event horizon. Animate light cones tipping inward as you approach the Schwarzschild radius until even outward light falls in. Show the radius scaling with mass.", "category": "cosmology"},
    {"prompt": "The cosmic microwave background. Animate the universe cooling until photons decouple at recombination, leaving a 2.7 K glow. Show the tiny temperature anisotropies as seeds of structure.", "category": "cosmology"},
    {"prompt": "Gravitational waves from a binary inspiral. Animate two orbiting masses warping spacetime, the orbit shrinking as energy radiates, and the chirp waveform rising in frequency until merger.", "category": "cosmology"},

    # ── CHEMISTRY & MATERIALS (9) ───────────────────────────────────────────────
    {"prompt": "Le Chatelier's principle. Animate an equilibrium reaction shifting when you add reactant, remove product, or change temperature, with the concentrations re-balancing each time.", "category": "physics_phenomena"},
    {"prompt": "Reaction rate and the Arrhenius equation. Plot rate constant vs temperature as k = A*exp(-Ea/RT), and animate the fraction of molecules above the activation-energy barrier growing as temperature rises.", "category": "physics_phenomena"},
    {"prompt": "VSEPR molecular geometry. Animate electron pairs around a central atom repelling into linear, trigonal, tetrahedral, and octahedral shapes. Show why water bends to 104.5 degrees.", "category": "physics_phenomena"},
    {"prompt": "Crystal lattices and packing efficiency. Animate FCC, BCC, and HCP arrangements of spheres and compute their packing fractions, with FCC and HCP tying at 74% (Kepler conjecture).", "category": "materials_science"},
    {"prompt": "Band theory: why metals, insulators, and semiconductors differ. Animate atomic energy levels broadening into bands as atoms come together, and show the band gap deciding conductivity.", "category": "materials_science"},
    {"prompt": "Diffusion and Fick's laws. Animate a concentration gradient smoothing out over time, with flux proportional to the gradient. Plot the spreading Gaussian profile of an initially sharp spike.", "category": "materials_science"},
    {"prompt": "The pH scale and buffer action. Animate adding acid to pure water versus a buffered solution, with the buffer resisting pH change until its capacity is exhausted. Plot the titration curve.", "category": "physics_phenomena"},
    {"prompt": "Shape-memory alloys and martensitic transformation. Animate the crystal switching between austenite and martensite phases as temperature changes, recovering a bent wire's original shape.", "category": "materials_science"},
    {"prompt": "Glass transition versus crystallization. Animate fast cooling trapping a disordered liquid into a glass versus slow cooling forming an ordered crystal. Plot volume vs temperature showing the kink at Tg.", "category": "materials_science"},

    # ── FLUIDS, WAVES & NONLINEAR DYNAMICS (10) ─────────────────────────────────
    {"prompt": "The Reynolds number and the laminar-to-turbulent transition. Animate dye in a pipe staying in a thread at low Re, then breaking into eddies past the critical Re. Show the dimensionless ratio of inertia to viscosity.", "category": "dynamical_systems"},
    {"prompt": "Bernoulli's principle. Animate fluid speeding up through a constriction with pressure dropping, and connect it to lift over an airfoil and the curve of a spinning ball (Magnus effect).", "category": "physics_phenomena"},
    {"prompt": "Karman vortex street. Animate flow past a cylinder shedding alternating vortices, the pattern responsible for singing wires and the Tacoma Narrows oscillation. Plot the shedding frequency vs flow speed.", "category": "dynamical_systems"},
    {"prompt": "The logistic map and the route to chaos. Animate the bifurcation diagram of x -> r*x*(1-x) as r increases, period-doubling into chaos, with the Feigenbaum constant governing the spacing.", "category": "dynamical_systems"},
    {"prompt": "The Lorenz attractor. Integrate the three Lorenz equations and animate the trajectory tracing the butterfly, never repeating yet bounded. Show sensitive dependence by splitting two nearby starts.", "category": "dynamical_systems"},
    {"prompt": "Solitons in shallow water. Animate a single stable wave packet propagating without spreading because dispersion balances nonlinearity, and show two solitons passing through each other unchanged.", "category": "dynamical_systems"},
    {"prompt": "Standing waves on a string. Animate the harmonics of a fixed-fixed string, with nodes and antinodes, and show how the allowed wavelengths set a musical instrument's overtone series.", "category": "physics_phenomena"},
    {"prompt": "Shock waves and the sonic boom. Animate an object accelerating through the sound barrier, wavefronts piling into a Mach cone, with the cone angle set by the Mach number.", "category": "physics_phenomena"},
    {"prompt": "Rayleigh-Benard convection. Animate a fluid heated from below organizing into rolling convection cells once the temperature gradient passes a threshold. Show the hexagonal pattern from above.", "category": "dynamical_systems"},
    {"prompt": "Phase locking and synchronization (Kuramoto model). Animate a population of coupled oscillators with random frequencies suddenly locking into a common rhythm as coupling strength crosses a threshold.", "category": "dynamical_systems"},

    # ── INFORMATION, CONTROL & SIGNALS (9) ──────────────────────────────────────
    {"prompt": "Shannon entropy as a measure of surprise. Animate the entropy of a biased coin peaking at 1 bit for a fair coin and dropping to zero as it becomes predictable. Connect it to optimal code length.", "category": "information_theory"},
    {"prompt": "Error-correcting Hamming codes. Animate encoding 4 data bits into 7 with parity, flipping one bit in transmission, and the syndrome pointing exactly to the corrupted position to fix it.", "category": "information_theory"},
    {"prompt": "The Nyquist-Shannon sampling theorem. Animate sampling a sine wave above and below twice its frequency, and show aliasing creating a phantom low-frequency wave when undersampled.", "category": "information_theory"},
    {"prompt": "Convolution as a sliding weighted sum. Animate a kernel sweeping across a signal, multiplying and summing, to blur or detect edges. Show the same operation underlying image filters.", "category": "information_theory"},
    {"prompt": "The PID controller. Animate a system overshooting and settling under proportional, integral, and derivative control, tuning each term to kill steady-state error and oscillation.", "category": "dynamical_systems"},
    {"prompt": "The Kalman filter. Animate a noisy position sensor and a prediction model fused into an estimate with shrinking uncertainty ellipse, tracking a moving target better than either source alone.", "category": "algorithms"},
    {"prompt": "Lossy compression via the discrete cosine transform. Animate an 8x8 image block transformed into frequency coefficients, the high-frequency ones quantized away, and the reconstruction — the heart of JPEG.", "category": "information_theory"},
    {"prompt": "Public-key exchange with Diffie-Hellman. Animate two parties mixing public and private exponents over a modulus to reach the same shared secret an eavesdropper can't compute. Use the paint-mixing analogy.", "category": "cryptography"},
    {"prompt": "Reservoir sampling. Pick k items uniformly from a stream of unknown length in one pass. Animate each new element replacing a slot with the right probability, keeping the sample unbiased.", "category": "algorithms"},

    # ── ECONOMICS, GAME THEORY & NETWORKS (9) ───────────────────────────────────
    {"prompt": "The Nash equilibrium in the prisoner's dilemma. Animate the payoff matrix and show why mutual defection is stable even though mutual cooperation pays more. Then show cooperation emerging in the iterated game.", "category": "counterintuitive_phenomena"},
    {"prompt": "Braess's paradox. Adding a road to a network can make everyone's commute longer. Animate traffic redistributing after a shortcut opens, raising the equilibrium travel time for all.", "category": "counterintuitive_phenomena"},
    {"prompt": "PageRank as a random surfer. Animate a walker clicking random links on a small web graph, with the long-run visit frequency ranking pages. Show the damping factor handling dead ends.", "category": "algorithms"},
    {"prompt": "Small-world networks. Animate a ring lattice gaining a few random long-range links and watch the average path length collapse while clustering stays high — six degrees of separation.", "category": "counterintuitive_phenomena"},
    {"prompt": "Preferential attachment and scale-free networks. Animate a growing network where new nodes link to popular hubs, producing a power-law degree distribution. Plot the heavy-tailed histogram.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Gini coefficient and the Lorenz curve. Animate plotting cumulative income share against population share, with the gap from equality measuring inequality. Compare two example distributions.", "category": "counterintuitive_phenomena"},
    {"prompt": "Evolutionarily stable strategies: hawks versus doves. Animate a population mixing aggressive and passive strategies converging to a stable ratio set by the cost of conflict versus the reward.", "category": "counterintuitive_phenomena"},
    {"prompt": "Compound interest and the rule of 72. Animate balances doubling at rates of 6%, 9%, and 12%, with doubling time approximated by 72/rate. Contrast exponential growth with linear intuition.", "category": "counterintuitive_phenomena"},
    {"prompt": "The stable marriage problem and Gale-Shapley. Animate proposers and reviewers pairing up through rounds of proposals and tentative acceptances, converging to a stable matching with no blocking pair.", "category": "algorithms"},

    # ── NEUROSCIENCE & COMPLEX SYSTEMS (8) ──────────────────────────────────────
    {"prompt": "The perceptron and a linear decision boundary. Animate weights rotating a separating line as labeled points are presented, converging when the data is linearly separable. Show XOR defeating a single perceptron.", "category": "algorithms"},
    {"prompt": "Gradient descent on a loss surface. Animate a ball rolling downhill on a 2D loss landscape, with learning rate too large overshooting and too small crawling. Show momentum escaping a shallow trap.", "category": "algorithms"},
    {"prompt": "Hebbian learning: neurons that fire together wire together. Animate synaptic weights strengthening between co-active units, forming an associative memory that completes partial patterns.", "category": "neuroscience"},
    {"prompt": "The Hopfield network as content-addressable memory. Animate a noisy pattern relaxing downhill in energy to the nearest stored memory. Show capacity limits when too many patterns are crammed in.", "category": "neuroscience"},
    {"prompt": "Integrate-and-fire neuron dynamics. Animate membrane voltage charging toward threshold, spiking, and resetting, with input current setting the firing rate. Plot the f-I curve.", "category": "neuroscience"},
    {"prompt": "Cellular automata: Rule 110 is Turing complete. Animate the 1D rule generating complex structured patterns from a single seed, with gliders colliding — computation from a trivial local rule.", "category": "dynamical_systems"},
    {"prompt": "Flocking with Boids. Animate agents following three local rules — separation, alignment, cohesion — producing emergent coordinated flocks with no leader. Show how tweaking weights changes the swarm.", "category": "dynamical_systems"},
    {"prompt": "Self-organized criticality: the sandpile model. Animate grains dropping and toppling avalanches whose sizes follow a power law, with the system poised at a critical state without tuning.", "category": "dynamical_systems"},

    # ── ASTRONOMY (4) ───────────────────────────────────────────────────────────
    {"prompt": "The HR diagram and stellar evolution. Plot luminosity versus temperature, animate the main sequence, and trace a Sun-like star evolving off it into a red giant then a white dwarf.", "category": "cosmology"},
    {"prompt": "Lagrange points in the three-body problem. Animate the five points where a small body co-orbits stably, with L4 and L5 trapping Trojan asteroids in their gravitational valleys.", "category": "cosmology"},
    {"prompt": "Detecting exoplanets by transit. Animate a planet crossing its star, dipping the brightness, and plot the periodic light curve. Show how depth gives planet size and period gives orbit.", "category": "cosmology"},
    {"prompt": "Parallax and the cosmic distance ladder. Animate a nearby star shifting against the background as Earth orbits, measuring distance by triangle geometry, the first rung of measuring the universe.", "category": "cosmology"},
]


def push(limit=None, dry_run=False):
    topics = TOPICS[:limit] if limit else TOPICS
    print(f"Prepared {len(topics)} topics (of {len(TOPICS)} total).")
    if dry_run:
        return
    sqs = boto3.client("sqs", region_name=REGION)
    sent = failed = 0
    for i in range(0, len(topics), 10):
        batch = topics[i:i + 10]
        entries = [
            {
                "Id": f"msg{i + j}",
                "MessageBody": json.dumps({
                    "topic_id": str(uuid.uuid4())[:8],
                    "prompt": t["prompt"],
                    "category": t["category"],
                }),
            }
            for j, t in enumerate(batch)
        ]
        resp = sqs.send_message_batch(QueueUrl=QUEUE_URL, Entries=entries)
        ok = len(resp.get("Successful", []))
        bad = len(resp.get("Failed", []))
        sent += ok
        failed += bad
        print(f"  batch {i // 10 + 1}: {ok}/{len(batch)} ok"
              + (f", {bad} FAILED" if bad else ""))
        time.sleep(0.2)
    print(f"Done: {sent} sent, {failed} failed.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    push(limit=args.limit, dry_run=args.dry_run)
