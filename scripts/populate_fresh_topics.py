#!/usr/bin/env python3
"""Populate SQS with a fresh batch of 100+ NEW unique STEM video topics.

Topics here intentionally do NOT overlap with populate_200_topics.py.
New categories: biology, geology, cryptography, neuroscience, quantum_info,
algorithms, cosmology, information_theory, materials_science, dynamical_systems.

Style notes: each prompt describes a single concrete concept that can be derived
or visualized in ~90 seconds with the iris-local pipeline (matplotlib /
manim / plotly / title_card). Avoid hooky "imagine if..." framings — open
with the concept itself.
"""

import boto3
import json
import uuid
import time

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/482625028438/iris-flow-topic-queue"
sqs = boto3.client("sqs", region_name="us-east-1")

TOPICS = [
    # ── BIOLOGY & EVOLUTION (12) ───────────────────────────────────────────────
    {"prompt": "Logistic growth and the carrying capacity K. Population grows as dN/dt = rN(1 - N/K). Plot N(t) for three different initial populations, all converging to K from different sides. Show why an S-curve is the inevitable shape when reproduction is locally exponential but resources are bounded.", "category": "biology"},
    {"prompt": "Lotka-Volterra predator-prey equations. dx/dt = ax - bxy, dy/dt = -cy + dxy. Plot the phase portrait — closed orbits around the fixed point (c/d, a/b). Then plot time series of hare and lynx population to show the inherent oscillation.", "category": "biology"},
    {"prompt": "Allometric scaling. Kleiber's law: metabolic rate scales as mass to the 3/4 power, not 2/3 as a simple surface-area argument would predict. Plot log metabolic rate vs log mass for mice through elephants. The 3/4 exponent emerges from branching transport networks (West-Brown-Enquist).", "category": "biology"},
    {"prompt": "Hardy-Weinberg equilibrium. Under random mating with no selection, allele frequencies p, q stay constant and genotype frequencies are p², 2pq, q². Animate generations passing with a virtual population and show why disturbing any assumption (selection, drift, mutation) breaks equilibrium.", "category": "biology"},
    {"prompt": "The molecular clock. Neutral mutations accumulate at a roughly constant rate, so two species' genetic divergence is proportional to time since their last common ancestor. Plot divergence vs known fossil-calibrated dates and show the linear regression that calibrates the clock.", "category": "biology"},
    {"prompt": "Action potential as a Hodgkin-Huxley spike. Plot membrane voltage during depolarization, repolarization, hyperpolarization, then refractory period. Overlay the Na+ and K+ channel conductances. Show why the all-or-nothing threshold is a consequence of positive feedback in the sodium current.", "category": "biology"},
    {"prompt": "Diffusion-limited aggregation. Particles random-walk until they touch a growing cluster, then stick. The resulting fractal has dimension ~1.71 in 2D. Animate 5000 particles aggregating and compute box-counting dimension live.", "category": "biology"},
    {"prompt": "Turing patterns in reaction-diffusion. Two chemicals with different diffusion rates can spontaneously form stripes and spots from a uniform initial state. Simulate the Gray-Scott model on a 2D grid and show patterns emerging as you vary the feed and kill rates.", "category": "biology"},
    {"prompt": "Phylogenetic distance and the UPGMA algorithm. Given a distance matrix between four species, build the tree by iteratively joining the closest pair. Animate the matrix collapsing and the tree growing edge by edge.", "category": "biology"},
    {"prompt": "The 'gene tree vs species tree' problem. Animate a species tree with three taxa, then show how a single gene can have a tree topology that disagrees with the species tree due to incomplete lineage sorting. The probability is computable from coalescent theory.", "category": "biology"},
    {"prompt": "Compartmental SIR epidemic model. dS/dt, dI/dt, dR/dt with reproductive number R₀ = β/γ. Plot the curves for R₀ = 0.9, 1.5, and 3. Show how vaccinating (1 - 1/R₀) of the population pushes the effective R below 1.", "category": "biology"},
    {"prompt": "Sequence alignment via dynamic programming. Walk through Needleman-Wunsch on two short DNA strings. Build the score matrix cell by cell, then trace back along the optimal path. Show why the algorithm runs in O(mn) time.", "category": "biology"},

    # ── GEOLOGY & EARTH SCIENCE (10) ───────────────────────────────────────────
    {"prompt": "Radiometric dating with the Pb-Pb isochron. Plot ²⁰⁶Pb/²⁰⁴Pb vs ²⁰⁷Pb/²⁰⁴Pb for several meteorite samples. The points lie on a line whose slope yields Earth's age: 4.55 Gyr. Show the derivation step by step.", "category": "geology"},
    {"prompt": "Plate tectonic velocities from GPS. Plot 20 GPS station velocities on a flat-Earth approximation of the Pacific Plate. Subtract the rigid-body rotation about the Euler pole. Residuals reveal strain accumulation along faults.", "category": "geology"},
    {"prompt": "Seismic body waves: P and S. P-waves are compressional and travel through liquid; S-waves are shear and don't. Animate both wave types propagating through a crust-mantle-core cross-section. The S-wave shadow zone tells us the outer core is liquid.", "category": "geology"},
    {"prompt": "Snell's law applied to seismic refraction. A P-wave hits a layer boundary at angle θ₁ and bends to θ₂ such that sin(θ₁)/v₁ = sin(θ₂)/v₂. Plot ray paths and the travel-time vs distance curve. The 'crossover distance' reveals layer depth.", "category": "geology"},
    {"prompt": "Mantle convection from Rayleigh number. Animate convection cells forming in a 2D fluid layer heated from below. As Ra crosses ~1700, the steady conduction state becomes unstable and overturning rolls appear. Show the streamlines.", "category": "geology"},
    {"prompt": "Geomagnetic reversals and the Vine-Matthews stripes. Animate the seafloor spreading away from a mid-ocean ridge while Earth's magnetic field flips at known dates. The frozen-in remanent magnetization produces stripes — and that stripe pattern proved continental drift.", "category": "geology"},
    {"prompt": "Isostasy: a mountain floats on the mantle like an iceberg. The depth of the crustal root is set by ρ_crust * (h + r) = ρ_mantle * r. Plot crustal thickness vs surface elevation for the Himalayas and the Andes.", "category": "geology"},
    {"prompt": "The Bouguer gravity correction. The measured gravity at the top of a mountain is less than at sea level, but you have to subtract the mass of the rock between you and sea level to find the underlying anomaly. Plot the corrections step by step on a Bouguer profile.", "category": "geology"},
    {"prompt": "Glacial isostatic rebound. After the ice sheets retreated 12,000 years ago, the depressed crust started rising. Plot a viscoelastic relaxation curve with timescale τ = 4πηρg/k² and show how Scandinavian uplift today is still 9 mm/yr.", "category": "geology"},
    {"prompt": "The Coriolis parameter and the Rossby number. f = 2Ω sin(latitude). Compute the Rossby number for the Gulf Stream, a hurricane, and a draining bathtub. Show why only the first two are geostrophically balanced.", "category": "geology"},

    # ── CRYPTOGRAPHY & INFO SECURITY (10) ──────────────────────────────────────
    {"prompt": "RSA encryption from first principles. Pick two small primes p=11, q=13. n = 143, φ(n) = 120. Choose e=7 (coprime to 120), find d=103 (such that ed ≡ 1 mod φ). Encrypt the number 5 step by step and decrypt it back. Show why Euler's theorem makes it work.", "category": "cryptography"},
    {"prompt": "Diffie-Hellman key exchange. Two parties agree publicly on g=5 and p=23. Alice picks a=6 (secret), sends A=g^a mod p=8. Bob picks b=15, sends B=g^b mod p=19. Both compute the shared secret 2 from A^b = B^a. Trace the arithmetic and explain why the eavesdropper can't compute it.", "category": "cryptography"},
    {"prompt": "Elliptic curve point addition. On the curve y² = x³ - 7x + 10, add the points (1, 2) and (3, 4) geometrically: draw the secant, find the third intersection, reflect across the x-axis. Then derive the algebraic formulas for the sum.", "category": "cryptography"},
    {"prompt": "Shor's algorithm period-finding. To factor N, find the period r of f(x) = a^x mod N. With period 6 and known a=2, plot the periodic function. The quantum Fourier transform extracts r in polynomial time — show why classical period-finding is exponential.", "category": "cryptography"},
    {"prompt": "Birthday attack on a hash function. With a 64-bit hash, you'd expect 2^32 ~ 4 billion samples to find a collision. Plot the birthday-problem probability curve and show why 'square root of the output space' beats the obvious 2^n estimate by 2^(n/2).", "category": "cryptography"},
    {"prompt": "Shamir's secret sharing with a polynomial. To split secret s into k-of-n shares, pick a random degree-(k-1) polynomial f with f(0) = s. Hand out f(1), f(2), ..., f(n). Any k recover s by Lagrange interpolation. Walk through with s=42, k=3, n=5.", "category": "cryptography"},
    {"prompt": "The AES S-box as a finite-field inversion. Each byte b is mapped to b^-1 in GF(2^8), then through an affine transformation. Animate the construction of one S-box entry and explain why the inversion provides strong non-linearity.", "category": "cryptography"},
    {"prompt": "One-time pad perfect secrecy. Show with a tiny example that ciphertext = plaintext XOR key, when the key is random and same-length and used once, reveals zero information about the plaintext. Plot conditional entropies before and after observation.", "category": "cryptography"},
    {"prompt": "Bloom filter false-positive rate. A Bloom filter with m bits, k hash functions, and n inserted elements has false-positive rate roughly (1 - e^(-kn/m))^k. Plot this surface and show the optimal k ≈ (m/n) ln 2.", "category": "cryptography"},
    {"prompt": "Merkle trees and inclusion proofs. To prove element X is in a tree of a million leaves, you only need log₂(10^6) ≈ 20 sibling hashes. Animate the proof verification: start with hash(X), combine with siblings, climb to the root, compare.", "category": "cryptography"},

    # ── NEUROSCIENCE (10) ──────────────────────────────────────────────────────
    {"prompt": "The Hopfield network as content-addressable memory. Store three patterns in a 100-neuron network via Hebbian weights. Corrupt a pattern and watch the energy function relax it back. Plot the energy landscape and the trajectory of states.", "category": "neuroscience"},
    {"prompt": "Spike-timing-dependent plasticity. The synaptic change Δw depends on the time between pre- and post-synaptic spikes. Plot the canonical STDP curve — potentiation when pre fires before post, depression when post fires before pre. Show the asymmetric exponentials.", "category": "neuroscience"},
    {"prompt": "Receptive fields and edge detection. Build a center-surround Gaussian-difference filter and convolve it with a step-edge image. Plot the response across the boundary. Show why the visual system uses lateral inhibition to enhance contrast.", "category": "neuroscience"},
    {"prompt": "Place cells and grid cells. Animate a virtual rat exploring a 2D arena while one place-cell fires only in its small patch, and one grid cell fires at the vertices of a triangular lattice. Plot the firing rate maps.", "category": "neuroscience"},
    {"prompt": "FitzHugh-Nagumo simplified neuron. Two coupled ODEs reproduce the qualitative shape of an action potential: a fast voltage variable and a slow recovery variable. Plot the phase portrait with its slow manifold and stable limit cycle.", "category": "neuroscience"},
    {"prompt": "Bayesian inference in perception. Given a noisy sensory signal and a prior over scenes, the posterior weighs them in proportion to their precisions. Show with a 1D Gaussian example why a small precise prior dominates a noisy measurement.", "category": "neuroscience"},
    {"prompt": "The Wilson-Cowan equations for cortical dynamics. Coupled rate equations for excitatory and inhibitory populations produce limit cycles, fixed points, and even chaos depending on coupling strength. Plot the phase portrait for three parameter regimes.", "category": "neuroscience"},
    {"prompt": "Drift-diffusion model of decision making. The decision variable accumulates noisy evidence until it hits a threshold. Plot 100 sample trajectories and the resulting reaction-time distribution. Show how raising the threshold trades speed for accuracy.", "category": "neuroscience"},
    {"prompt": "Independent Component Analysis (ICA) for EEG. Given a 64-channel EEG mixture, ICA separates the underlying neural sources by maximizing non-Gaussianity. Animate the source recovery on a synthetic mixture.", "category": "neuroscience"},
    {"prompt": "Functional connectivity from BOLD fMRI. Compute Pearson correlation between time series of every pair of brain regions to build the connectivity matrix. Visualize default-mode network nodes lighting up together while task-positive nodes anti-correlate.", "category": "neuroscience"},

    # ── QUANTUM INFORMATION (10) ───────────────────────────────────────────────
    {"prompt": "Bloch sphere geometry. A qubit state |ψ⟩ = cos(θ/2)|0⟩ + e^iφ sin(θ/2)|1⟩ maps to a point on the unit sphere. Plot the sphere, mark |0⟩, |1⟩, |+⟩, |i+⟩, and animate a Hadamard rotation moving |0⟩ to |+⟩.", "category": "quantum_information"},
    {"prompt": "The CHSH inequality. Local hidden variable theories satisfy |E(a,b) - E(a,b') + E(a',b) + E(a',b')| ≤ 2, but entangled qubits with the right measurement angles reach 2√2. Plot Bell correlations and the violation.", "category": "quantum_information"},
    {"prompt": "Quantum teleportation circuit. Two parties share an entangled pair; the sender performs Bell measurement on her unknown qubit plus her half; sends 2 classical bits; the receiver applies one of four Pauli corrections. Animate each step on a circuit diagram.", "category": "quantum_information"},
    {"prompt": "Grover's search amplitude amplification. Starting from a uniform superposition over N states with one marked, two operations (oracle + diffusion) rotate the amplitude vector by ~2/√N each iteration. Plot the marked-state probability vs iteration; find the optimum at ~π√N/4.", "category": "quantum_information"},
    {"prompt": "Decoherence and the density matrix. A pure superposition (|0⟩+|1⟩)/√2 has off-diagonal coherences |0⟩⟨1| and |1⟩⟨0|. Couple it to an environment and watch those off-diagonals decay exponentially. Plot the density-matrix Frobenius norm vs time.", "category": "quantum_information"},
    {"prompt": "Shor 9-qubit code. A single logical qubit is encoded in 9 physical qubits to protect against arbitrary single-qubit errors. Walk through the encoding circuit, the syndrome measurement that detects any X, Y, Z error, and the recovery.", "category": "quantum_information"},
    {"prompt": "Quantum phase estimation. Given a unitary U with eigenstate |u⟩ and eigenvalue e^(2πiφ), estimate φ to n bits using n+log(1/ε) extra qubits. Animate the inverse QFT pulling the phase out of the ancilla register.", "category": "quantum_information"},
    {"prompt": "The no-cloning theorem. Suppose a unitary U could clone arbitrary states: U|ψ⟩|0⟩ = |ψ⟩|ψ⟩. Linearity contradicts this for any two non-orthogonal states. Walk through the two-line proof.", "category": "quantum_information"},
    {"prompt": "Variational quantum eigensolver. Parametrize a quantum circuit, measure the expectation ⟨H⟩, and use classical gradient descent to minimize it. Plot the energy descending toward the ground state of a 2-qubit Heisenberg model.", "category": "quantum_information"},
    {"prompt": "Surface code minimum-weight perfect matching. Detect errors as defects on a 2D lattice of syndrome bits. Connect defects with the shortest paths to identify the underlying error chain. Animate one round of syndrome extraction and matching.", "category": "quantum_information"},

    # ── ALGORITHMS & COMPUTATION (10) ──────────────────────────────────────────
    {"prompt": "Strassen's matrix multiplication. Recursively split two n×n matrices into 2×2 blocks, then compute the product with 7 block multiplications instead of 8 via clever combinations. Plot the recursion T(n) = 7T(n/2) + O(n²) → O(n^log₂7) ≈ O(n^2.81).", "category": "algorithms"},
    {"prompt": "Dijkstra's shortest paths on a 5-node graph. Maintain a priority queue of tentative distances. At each step, extract the minimum and relax its neighbors. Animate the frontier expanding from the source until every node has its final distance.", "category": "algorithms"},
    {"prompt": "Quickselect and the median-of-medians pivot. Quickselect runs in O(n) expected time but O(n²) worst case. The median-of-medians pivot tames the worst case to O(n) by guaranteeing a constant fraction of elements lie on each side. Animate the recursion tree.", "category": "algorithms"},
    {"prompt": "Hashing with linear probing. Insert keys 23, 37, 49, 50 into a table of size 7 with hash h(k) = k mod 7. Visualize the cluster forming around bucket 2 and explain why load factor matters.", "category": "algorithms"},
    {"prompt": "Bellman-Ford detects negative cycles. Relax every edge n-1 times. If any edge still relaxes on iteration n, there's a negative cycle reachable from the source. Walk through a 4-node graph with a -2 cycle.", "category": "algorithms"},
    {"prompt": "Convex hull via Graham scan. Sort points by polar angle around the lowest one, then scan with a stack; pop whenever the next point makes a right turn. Animate the algorithm on 30 random points and prove the O(n log n) runtime.", "category": "algorithms"},
    {"prompt": "Union-Find with path compression and union by rank. Walk through a sequence of unions and finds; show the trees flattening as path compression hits. Argue the inverse-Ackermann amortized complexity.", "category": "algorithms"},
    {"prompt": "Fast Fourier Transform via decimation-in-time. Show how a size-8 DFT decomposes into two size-4 DFTs combined with twiddle factors. Animate the butterfly diagram and trace one full computation.", "category": "algorithms"},
    {"prompt": "Reservoir sampling for streams of unknown length. With a single pass and O(1) memory, pick k items uniformly at random from a stream of n items. Show the probability argument: item i replaces a reservoir slot with probability k/i.", "category": "algorithms"},
    {"prompt": "A* search with the Manhattan-distance heuristic. Show on a 10×10 grid with obstacles how A* expands far fewer nodes than Dijkstra. Animate both side by side. The heuristic must be admissible: never overestimate the true cost.", "category": "algorithms"},

    # ── COSMOLOGY (10) ─────────────────────────────────────────────────────────
    {"prompt": "Hubble's law: v = H₀d. Plot redshift vs distance for 50 nearby galaxies; the slope of the line gives H₀ ≈ 70 km/s/Mpc. Show the systematic deviation from linearity at high redshift due to dark-energy acceleration.", "category": "cosmology"},
    {"prompt": "Friedmann equation. H² = (8πG/3)ρ - kc²/a² + Λc²/3. Plot a(t) for matter-dominated, radiation-dominated, and Λ-dominated regimes. Show the transition redshifts between them.", "category": "cosmology"},
    {"prompt": "The cosmic microwave background acoustic peaks. The angular power spectrum has peaks at ℓ ≈ 220, 540, 800. Plot it, identify the first peak as the sound horizon at decoupling, and explain how the relative heights tell us Ω_baryon.", "category": "cosmology"},
    {"prompt": "BBN: primordial helium. Plot the predicted mass fraction of helium-4 vs the baryon-to-photon ratio η. The plateau near 24% matches observations of low-metallicity galaxies. Explain why deuterium is the most sensitive probe of η.", "category": "cosmology"},
    {"prompt": "Dark matter rotation curves. Plot the observed flat rotation curve of NGC 3198 alongside the curve predicted from visible matter alone (which falls off as 1/√r). The discrepancy at large r requires a halo of dark matter.", "category": "cosmology"},
    {"prompt": "Gravitational lensing by a point mass. The deflection angle is α = 4GM/(c²b). Plot the angular position of a background source vs the true position; for impact parameter inside the Einstein radius, two images and an Einstein ring appear.", "category": "cosmology"},
    {"prompt": "The Schwarzschild metric in 1D. ds² = -(1-r_s/r)dt² + (1-r_s/r)^-1 dr². Plot proper time vs coordinate time for an infalling observer and a distant observer. Show the coordinate-time divergence at the horizon.", "category": "cosmology"},
    {"prompt": "Recombination and the photon decoupling surface. Plot the ionization fraction X_e vs redshift z. Solve the Saha equation and watch the universe go from opaque to transparent at z ≈ 1100, releasing the CMB.", "category": "cosmology"},
    {"prompt": "Cepheid period-luminosity relation. Plot absolute magnitude vs log period for 20 Cepheid variables. The tight line — M = -2.78 log P - 1.35 — is the rung of the cosmic distance ladder that calibrated H₀.", "category": "cosmology"},
    {"prompt": "Inflation slow-roll parameters. Define ε = (M_Pl²/2)(V'/V)² and η = M_Pl² V''/V. Plot V(φ) for chaotic inflation V = ½m²φ². Show why slow roll requires ε, |η| ≪ 1 and how it ends.", "category": "cosmology"},

    # ── INFORMATION THEORY (8) ─────────────────────────────────────────────────
    {"prompt": "Shannon entropy of a coin flip. Plot H(p) = -p log p - (1-p) log(1-p) for p in [0,1]. The maximum at p=0.5 with H=1 bit is the most uncertain state. Use this to motivate the bits per symbol units.", "category": "information_theory"},
    {"prompt": "Kraft's inequality and prefix codes. A prefix-free code with codeword lengths ℓᵢ exists iff Σ 2^(-ℓᵢ) ≤ 1. Plot the constructive binary tree for a {1,2,3,3} length sequence and walk through why violations are unrealizable.", "category": "information_theory"},
    {"prompt": "Channel capacity of a binary symmetric channel. C = 1 - H(p) where p is the bit-flip probability. Plot C vs p. At p=0.5 the channel is useless (capacity 0); at p=0 it's perfect (1 bit per use). Explain Shannon's coding theorem.", "category": "information_theory"},
    {"prompt": "Mutual information between two Gaussian variables. I(X;Y) = -½ log(1-ρ²) where ρ is correlation. Plot I vs ρ. At ρ=±1, I diverges — perfect prediction. At ρ=0, I=0.", "category": "information_theory"},
    {"prompt": "Huffman coding builds the optimal prefix code. Given symbol probabilities (0.4, 0.3, 0.15, 0.1, 0.05), iteratively merge the two least-likely. Walk through the tree construction and compute expected codeword length vs entropy.", "category": "information_theory"},
    {"prompt": "Kullback-Leibler divergence. D(p||q) = Σ p(x) log(p(x)/q(x)). It's the average extra bits needed to encode P using a Q-tuned code. Plot D for two Gaussians as their means and variances diverge.", "category": "information_theory"},
    {"prompt": "Arithmetic coding squeezes into the entropy floor. Encode the string 'ABA' with letter probabilities (A: 0.6, B: 0.4) into a real number in [0, 1). Show how iterative interval subdivision yields a near-entropy-rate encoding.", "category": "information_theory"},
    {"prompt": "Rate-distortion bound for a Gaussian source. R(D) = ½ log(σ²/D) bits per sample. Plot R vs distortion D. This is the minimum rate to reconstruct a Gaussian source with mean-squared error ≤ D.", "category": "information_theory"},

    # ── DYNAMICAL SYSTEMS & CHAOS (8) ──────────────────────────────────────────
    {"prompt": "Logistic map period doubling. xₙ₊₁ = r xₙ(1 - xₙ). Plot the bifurcation diagram from r=2.4 to r=4. Identify the period-1, 2, 4, 8, 16 windows and the Feigenbaum constant δ ≈ 4.669 governing their spacing.", "category": "dynamical_systems"},
    {"prompt": "Lorenz attractor. dx/dt = σ(y-x), dy/dt = x(ρ-z) - y, dz/dt = xy - βz. With σ=10, β=8/3, ρ=28, plot the iconic two-lobe butterfly attractor and compute its fractal dimension by box counting.", "category": "dynamical_systems"},
    {"prompt": "Lyapunov exponent of the logistic map. Compute λ(r) numerically by averaging log|1 - 2x_n| along a trajectory. Plot λ vs r alongside the bifurcation diagram; chaos windows are where λ > 0.", "category": "dynamical_systems"},
    {"prompt": "Hopf bifurcation in 2D. The system dr/dt = μr - r³, dθ/dt = ω undergoes a Hopf bifurcation at μ=0: a stable fixed point becomes an unstable spiral and a stable limit cycle is born at radius √μ. Plot phase portraits at μ = -0.5, 0, +0.5.", "category": "dynamical_systems"},
    {"prompt": "Poincaré section of the driven pendulum. The 3D phase space (angle, angular velocity, time mod period) reduces to a 2D map by sampling each period. Plot the section for weak and strong forcing and show the route to chaos.", "category": "dynamical_systems"},
    {"prompt": "The Mandelbrot set escape-time iteration. For each c in the complex plane, iterate zₙ₊₁ = zₙ² + c starting from z₀ = 0. Color by escape time; the bounded set is the Mandelbrot. Animate zooming into the seahorse valley.", "category": "dynamical_systems"},
    {"prompt": "Coupled oscillators and the Kuramoto model. N phase oscillators with natural frequencies ωᵢ couple via sin(θⱼ - θᵢ). Plot the order parameter R vs coupling strength K; above a critical K, synchronization emerges.", "category": "dynamical_systems"},
    {"prompt": "Catastrophe theory cusp. The fold has potential V(x) = ⅓x³ + ax. The cusp adds V(x) = ¼x⁴ + ½bx² + ax. Plot equilibrium x*(a,b) as a surface in (a, b, x). The fold lines are where two equilibria collide; the cusp point is where three meet.", "category": "dynamical_systems"},

    # ── MATERIALS SCIENCE (7) ──────────────────────────────────────────────────
    {"prompt": "Stress-strain curve of mild steel. Plot the σ-ε curve from elastic regime through yield to ultimate stress to necking. Label Young's modulus, yield, UTS, fracture. Explain the difference between engineering and true stress.", "category": "materials_science"},
    {"prompt": "Pugh's relation for ductility. Plot the bulk modulus to shear modulus ratio K/G for 30 metals; values above ~1.75 are ductile, below are brittle. Position iron, tungsten, glass, diamond on the plot.", "category": "materials_science"},
    {"prompt": "Bragg's law for X-ray diffraction. nλ = 2d sin(θ). Animate a beam reflecting from parallel atomic planes; the diffraction peak appears only when the path difference is an integer wavelength. Plot intensity vs θ for a simple cubic lattice.", "category": "materials_science"},
    {"prompt": "Hall-Petch grain size strengthening. σ_y = σ₀ + k/√d. Plot yield stress vs inverse-square-root of grain size for steel. Smaller grains mean more grain boundaries blocking dislocations.", "category": "materials_science"},
    {"prompt": "Eutectic phase diagram. For Sn-Pb solder, plot the temperature-composition diagram with the eutectic point at 183 °C and 38% Pb. Animate a 60-40 alloy cooling through the liquidus, two-phase region, and solidus.", "category": "materials_science"},
    {"prompt": "Diffusion via Fick's second law. ∂c/∂t = D ∂²c/∂x². Solve the semi-infinite slab problem with a fixed surface concentration; plot the concentration profile at four times. Show the diffusion length scales as √(Dt).", "category": "materials_science"},
    {"prompt": "Band structure of silicon. Compute the parabolic-band approximation near the indirect band gap. Show how phonon-assisted absorption is required for photons below the direct gap of 3.4 eV. Plot the absorption coefficient α(ℏω) for crystalline silicon.", "category": "materials_science"},

    # ── STATISTICAL MECHANICS (5) ──────────────────────────────────────────────
    {"prompt": "Maxwell-Boltzmann speed distribution. P(v) = 4π (m/2πkT)^(3/2) v² e^(-mv²/2kT). Plot for three temperatures; mark the most probable, mean, and rms speeds.", "category": "statistical_mechanics"},
    {"prompt": "Ising model 2D phase transition. Simulate a Metropolis-Hastings update on a 100×100 lattice at three temperatures: well below Tc, at Tc, and above. Plot magnetization and energy vs T to show the order parameter going to zero continuously.", "category": "statistical_mechanics"},
    {"prompt": "Equipartition and heat capacity. Each quadratic degree of freedom gets (1/2)kT of energy on average. Derive C_v = (3/2)R for an ideal monatomic gas and C_v = (5/2)R for a diatomic gas with rotation. Plot Einstein's quantum correction at low T.", "category": "statistical_mechanics"},
    {"prompt": "Boltzmann factor and Arrhenius rates. The probability of being in a state with energy E above the ground state is proportional to e^(-E/kT). Plot reaction rate k = A e^(-Ea/RT) on an Arrhenius plot for three activation energies.", "category": "statistical_mechanics"},
    {"prompt": "Random walks and the diffusion constant. Compute the mean-squared displacement ⟨x²⟩ = 2Dt for 1000 random walkers in 1D. Plot ⟨x²⟩ vs t — a straight line. The diffusion constant emerges as the slope.", "category": "statistical_mechanics"},
]

print(f"Loaded {len(TOPICS)} fresh topics across "
      f"{len(set(t['category'] for t in TOPICS))} categories")


def push_topics():
    """Push topics to SQS in batches of 10."""
    sent = 0
    failed = 0
    for i in range(0, len(TOPICS), 10):
        batch = TOPICS[i:i+10]
        entries = []
        for j, topic in enumerate(batch):
            entries.append({
                "Id": f"msg{i+j}",
                "MessageBody": json.dumps({
                    "topic_id": str(uuid.uuid4()),
                    "prompt": topic["prompt"],
                    "category": topic["category"],
                }),
            })
        resp = sqs.send_message_batch(QueueUrl=QUEUE_URL, Entries=entries)
        sent += len(resp.get("Successful", []))
        failed += len(resp.get("Failed", []))
        if resp.get("Failed"):
            for f in resp["Failed"]:
                print(f"  FAILED {f.get('Id')}: {f.get('Message')}")
        print(f"  pushed batch {i//10 + 1}/{(len(TOPICS)+9)//10}: "
              f"{len(resp.get('Successful', []))}/{len(batch)} OK")
        time.sleep(0.2)  # tiny pause between batches
    print(f"\nTotal: {sent} sent, {failed} failed")


if __name__ == "__main__":
    push_topics()
