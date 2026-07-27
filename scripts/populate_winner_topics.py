#!/usr/bin/env python3
"""Populate SQS with ~100 topics in the MEASURED top-performing categories.

Data (Jul 2026 Metricool x manifest join) ranked category performance:
  counterintuitive_phenomena / elegant_theorems / cryptography /
  quantum_information / paradoxes  >>  physics_phenomena / algorithms /
  information_theory.

Every topic here has a TWIST — a one-sentence claim that sounds wrong but is
true — because measured watch-through is driven by "a surprise the viewer has to
see resolved," not by textbook demonstrations of known laws. Each is renderable
in 60-75s with the matplotlib / manim / plotly pipeline.
"""

import boto3
import json
import uuid
import time

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/482625028438/iris-flow-topic-queue"
sqs = boto3.client("sqs", region_name="us-east-1")

TOPICS = [
    # ── COUNTERINTUITIVE PHENOMENA (24) — the #1 category ──────────────────────
    {"prompt": "The Monty Hall problem, resolved by simulation. You pick 1 of 3 doors, the host opens a losing door, and switching wins 2/3 of the time. Run 10,000 games live, tally switch-wins vs stay-wins, and show the count converge to 2/3 vs 1/3. Then show the 100-door version where switching is obviously right.", "category": "counterintuitive_phenomena"},
    {"prompt": "Simpson's paradox. A treatment can have a higher success rate than a rival in every subgroup yet a lower rate overall. Animate two hospitals' recovery data splitting into mild vs severe cases, and show the aggregate reversing the per-group winner because of how cases are distributed.", "category": "counterintuitive_phenomena"},
    {"prompt": "Braess's paradox. Adding a new road to a network can make everyone's commute longer. Animate cars routing through a 4-node network, add a zero-cost shortcut edge, and show the Nash-equilibrium travel time rise for every driver.", "category": "counterintuitive_phenomena"},
    {"prompt": "The birthday paradox. In a room of just 23 people, it's more likely than not that two share a birthday. Plot the collision probability climbing to 50% at 23 and 99.9% at 70, and animate a room filling up with matches lighting.", "category": "counterintuitive_phenomena"},
    {"prompt": "Benford's law. In real-world data, the leading digit is '1' about 30% of the time, not 11%. Plot leading-digit frequencies for river lengths, stock prices, and populations, all matching the log(1+1/d) curve. Show why scale-invariance forces it.", "category": "counterintuitive_phenomena"},
    {"prompt": "The tennis racket / Dzhanibekov effect. Spin an object about its intermediate axis and it flips over periodically, even in zero gravity with no torque. Simulate the rigid-body Euler equations and animate the tumbling handle-flip.", "category": "counterintuitive_phenomena"},
    {"prompt": "A magnet dropped through a copper pipe falls in slow motion. There's no iron, copper isn't magnetic, yet eddy currents induced by the falling magnet oppose its motion. Simulate the induced currents and plot velocity leveling off to terminal speed.", "category": "counterintuitive_phenomena"},
    {"prompt": "The brachistochrone. The fastest ramp between two points isn't the straight line, it's an upside-down cycloid. Race three beads down a line, a circular arc, and the cycloid; the cycloid wins every time. Show why with the calculus of variations.", "category": "counterintuitive_phenomena"},
    {"prompt": "Gabriel's horn. Rotate y=1/x about the x-axis: the solid has finite volume but infinite surface area. You could fill it with paint but never paint it. Animate the horn forming and plot the two integrals, one converging, one diverging.", "category": "counterintuitive_phenomena"},
    {"prompt": "The 100 prisoners problem. 100 prisoners each find their number among 100 boxes with 50 tries; random guessing gives them ~0 chance, but a loop-following strategy gives 31%. Animate the cycle-chasing strategy and simulate the survival rate.", "category": "counterintuitive_phenomena"},
    {"prompt": "Buffon's needle estimates pi. Drop needles on a lined floor; the fraction that cross a line is 2/pi times (needle length / line spacing). Simulate 5000 drops and watch the running estimate of pi converge.", "category": "counterintuitive_phenomena"},
    {"prompt": "The coastline paradox. Britain's coastline has no single length; the shorter your ruler, the longer the measurement, growing without bound. Measure a fractal coast at four ruler scales and plot log-length vs log-ruler to extract the fractal dimension.", "category": "counterintuitive_phenomena"},
    {"prompt": "Newcomb's-style two-envelope reasoning aside, the real St. Petersburg paradox: a coin-flip game with infinite expected payout, yet nobody will pay $20 to play. Plot the expected value diverging while the median winnings stay tiny, and explain via utility.", "category": "counterintuitive_phenomena"},
    {"prompt": "Bertrand's chord paradox. Ask 'what's the probability a random chord is longer than the triangle's side' and get 1/2, 1/3, or 1/4 depending on how you pick 'random'. Animate all three sampling methods on the same circle and show the different answers.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Banach-Tarski flavor without the horror: show that the set of all integers has the 'same size' as the even integers via a bijection, and Hilbert's Hotel absorbing infinitely many new guests. Animate the room-shuffling.", "category": "counterintuitive_phenomena"},
    {"prompt": "A chain fountain (the Mould effect). Pull a chain out of a beaker and it leaps up above the rim before falling. Simulate the bead-rod chain with an anomalous upward reaction force from the pickup point and animate the arc.", "category": "counterintuitive_phenomena"},
    {"prompt": "Faster-than-you-think mixing: two dice, sum distribution. Rolling 2 dice, 7 is six times likelier than 2. Animate the 36-outcome grid collapsing onto the triangular sum distribution and show why the extremes are rare.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Ehrenfest urn and why gas doesn't spontaneously un-mix. Two boxes, N balls, each step moves a random ball. Simulate N=100 and show the count relaxing to 50/50 and essentially never returning to all-in-one, though it's not forbidden.", "category": "counterintuitive_phenomena"},
    {"prompt": "Parrondo's paradox. Two losing gambling games, alternated, become a winning game. Simulate both games' capital declining alone, then interleave them and watch the combined capital climb. Show the ratchet mechanism.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Leidenfrost effect. A water droplet on a 300C plate lasts far longer than on a 150C plate, because a vapor cushion insulates it. Plot droplet lifetime vs plate temperature and animate the levitating drop skating on its own steam.", "category": "counterintuitive_phenomena"},
    {"prompt": "Why a slinky's bottom hangs in mid-air when you drop it. Release a hanging slinky and the bottom doesn't move until the collapsing tension wave reaches it. Simulate the coupled masses and plot the top and bottom trajectories.", "category": "counterintuitive_phenomena"},
    {"prompt": "The friendship paradox. On average, your friends have more friends than you do. Build a random social graph, plot each node's degree vs the average degree of its neighbors, and show why the inequality is almost universal.", "category": "counterintuitive_phenomena"},
    {"prompt": "Aliasing: a wagon wheel spinning forward appears to spin backward on video. Sample a rotating spoke at a frame rate below Nyquist and animate the apparent reversal, then plot the true vs perceived angular velocity.", "category": "counterintuitive_phenomena"},
    {"prompt": "The Galton board makes a bell curve from pure chance. Drop 2000 balls through a peg triangle; each bounces left or right at random, yet they pile into a Gaussian. Animate the fall and overlay the binomial-to-normal limit.", "category": "counterintuitive_phenomena"},

    # ── ELEGANT THEOREMS (18) ──────────────────────────────────────────────────
    {"prompt": "The Pythagorean theorem by rearrangement. Show a² + b² = c² with a water-tank or tangram proof: the same four right triangles rearranged leave a² + b² in one framing and c² in another. Animate the pieces sliding.", "category": "elegant_theorems"},
    {"prompt": "Euler's identity, e^(i*pi) + 1 = 0, built from the spinning complex exponential. Animate a point tracing the unit circle as e^(i*theta), reaching -1 at theta = pi. Show the Taylor series of e, sin, cos interleaving to make it true.", "category": "elegant_theorems"},
    {"prompt": "The sum 1 + 2 + 4 + 8 ... doubling, versus 1/2 + 1/4 + 1/8 ... = 1. Animate a unit square being filled by halves forever, converging to full, and contrast with the divergent doubling series. Geometric series made visual.", "category": "elegant_theorems"},
    {"prompt": "Pick's theorem. The area of any lattice polygon is (interior points) + (boundary points)/2 - 1. Draw a jagged lattice polygon, count dots, and verify against the shoelace area. Animate deforming it while the formula holds.", "category": "elegant_theorems"},
    {"prompt": "The five-color-to-four-color idea: Euler's formula V - E + F = 2 for any planar graph. Animate building a polyhedron's graph and show the alternating sum staying 2 no matter how you triangulate.", "category": "elegant_theorems"},
    {"prompt": "Cantor's diagonal argument. The reals are uncountable: list any infinite table of decimals, build a new number differing on the diagonal, and it's not in the list. Animate the diagonal digit-flip constructing the missing number.", "category": "elegant_theorems"},
    {"prompt": "The infinitude of primes, Euclid's proof. Assume finitely many primes, multiply them all and add 1; the result is divisible by none of them. Animate the contradiction with a concrete small example.", "category": "elegant_theorems"},
    {"prompt": "Viviani's theorem. From any point inside an equilateral triangle, the three perpendicular distances to the sides always sum to the triangle's height. Animate the point wandering while the three segments rearrange into a constant total.", "category": "elegant_theorems"},
    {"prompt": "The area under one arch of a cycloid is exactly 3 times the area of the rolling circle. Animate a wheel rolling and tracing the cycloid, then tile the arch with three circle-areas.", "category": "elegant_theorems"},
    {"prompt": "Sum of first n odd numbers equals n². Animate square numbers being built by adding L-shaped gnomons of 1, 3, 5, 7 dots. The picture is the proof.", "category": "elegant_theorems"},
    {"prompt": "The handshake lemma. In any graph, the number of odd-degree vertices is always even. Animate summing degrees as counting edge-endpoints, so the total is always twice the edge count.", "category": "elegant_theorems"},
    {"prompt": "Ceva's theorem for concurrent cevians in a triangle, stated as a product of three ratios equal to 1. Animate dragging the point where the cevians meet and show the ratio product staying pinned at 1.", "category": "elegant_theorems"},
    {"prompt": "The basel problem: 1 + 1/4 + 1/9 + 1/16 ... = pi²/6. Plot the partial sums crawling toward 1.6449 and reveal Euler's shocking connection between the integers and pi.", "category": "elegant_theorems"},
    {"prompt": "Fermat's little theorem. For prime p, a^p ≡ a mod p. Animate the necklace-counting proof: color p beads with a colors, and the rotations partition all non-monochrome necklaces into groups of size p.", "category": "elegant_theorems"},
    {"prompt": "The intermediate value theorem, applied: at any moment there are two antipodal points on Earth's equator with the same temperature. Plot a continuous temperature difference function crossing zero and explain the guarantee.", "category": "elegant_theorems"},
    {"prompt": "Napoleon's theorem. Build equilateral triangles on the sides of ANY triangle; their centers always form an equilateral triangle. Animate deforming the base triangle while the central triangle stays perfectly equilateral.", "category": "elegant_theorems"},
    {"prompt": "The AM-GM inequality, geometrically. The arithmetic mean of two numbers is at least their geometric mean, shown by a semicircle where the radius beats the half-chord. Animate the two numbers changing and the gap closing only when they're equal.", "category": "elegant_theorems"},
    {"prompt": "A Möbius strip has only one side and one edge. Trace a pen down the middle and it covers 'both' faces returning to start; cut it lengthwise and get one longer loop, not two. Animate the trace and the cut.", "category": "elegant_theorems"},

    # ── CRYPTOGRAPHY (14) ──────────────────────────────────────────────────────
    {"prompt": "Shamir's secret sharing. Split a secret into 5 shares where any 3 reconstruct it but any 2 reveal nothing, using a random degree-2 polynomial through (0, secret). Animate the parabola and Lagrange interpolation recovering it from 3 points.", "category": "cryptography"},
    {"prompt": "Diffie-Hellman key exchange, with paint-mixing intuition then the math. Two people build a shared secret over a public channel that an eavesdropper can't reconstruct. Trace g^a, g^b, and the common g^(ab) mod p with small numbers.", "category": "cryptography"},
    {"prompt": "RSA in one example. Two primes give a public key anyone can encrypt with and a private key only you can decrypt with. Encrypt a number and decrypt it back with p=11, q=13, and show why factoring n is the wall protecting the secret.", "category": "cryptography"},
    {"prompt": "The one-time pad is unbreakable, and why you still can't use it. XOR a message with a truly random equal-length key and the ciphertext could decrypt to ANY message. Show a 3-bit example where every plaintext is equally consistent.", "category": "cryptography"},
    {"prompt": "The birthday attack. A 256-bit hash needs only ~2^128 tries to find a collision, not 2^256, because of the birthday paradox. Plot the collision probability and show why 'half the bits' is the real security level.", "category": "cryptography"},
    {"prompt": "Zero-knowledge proof, the Ali Baba cave. Prove you know a password without revealing it, by repeatedly emerging from the correct tunnel of a ring cave. Animate the rounds and plot the cheater's success probability halving each round.", "category": "cryptography"},
    {"prompt": "Elliptic curve point addition. Adding two points on y²=x³+ax+b means drawing a line, finding the third intersection, and reflecting. Animate the geometric rule and explain why it's the basis of modern public-key crypto.", "category": "cryptography"},
    {"prompt": "Merkle trees prove membership cheaply. To prove one leaf is in a tree of a million, you reveal only ~20 sibling hashes. Animate hashing up from the leaf to the root and comparing to the known root.", "category": "cryptography"},
    {"prompt": "The Caesar cipher and why frequency analysis breaks it. Shift letters by 3 and it looks scrambled, but 'E' is still the most common letter. Plot the letter-frequency histogram of the ciphertext lining up under the shift and crack it.", "category": "cryptography"},
    {"prompt": "Hash functions and the avalanche effect. Change one bit of the input and about half the output bits flip. Animate two nearly-identical inputs producing wildly different hashes and plot the bit-difference distribution centered at 50%.", "category": "cryptography"},
    {"prompt": "Commitment schemes: how to bet on a coin flip over the phone. Commit to a value you can't change but haven't revealed, using a hash. Walk through the commit-reveal protocol and show why neither party can cheat.", "category": "cryptography"},
    {"prompt": "The discrete logarithm problem. Computing g^x mod p is easy, but recovering x from the result is believed hard. Plot the chaotic scatter of g^x mod p versus x and show why there's no shortcut back.", "category": "cryptography"},
    {"prompt": "Quantum key distribution (BB84). Encode bits on photon polarizations; any eavesdropper measuring them disturbs the state and gets caught. Animate Alice, Bob, and Eve's measurements and show the error rate exposing the spy.", "category": "cryptography"},
    {"prompt": "Password hashing and why salt matters. Two users with the same password get different stored hashes when salted, defeating rainbow tables. Animate two identical passwords diverging after salting.", "category": "cryptography"},

    # ── QUANTUM INFORMATION (12) ───────────────────────────────────────────────
    {"prompt": "Superposition and the qubit as a point on the Bloch sphere. A classical bit is 0 or 1; a qubit is any point on a sphere. Animate rotations moving the state vector and show measurement collapsing it to a pole with probabilities set by the angle.", "category": "quantum_information"},
    {"prompt": "Quantum entanglement and the Bell state. Measure one of two entangled qubits and the other's outcome is instantly correlated, no matter the distance. Animate the shared state and the correlated measurement statistics.", "category": "quantum_information"},
    {"prompt": "The no-cloning theorem. You cannot copy an unknown quantum state. Show why a hypothetical copier would violate linearity of quantum mechanics, with a two-state contradiction laid out step by step.", "category": "quantum_information"},
    {"prompt": "The double-slit experiment with single particles. Fire electrons one at a time and an interference pattern still builds up, until you measure which slit, and it vanishes. Animate the dot-by-dot buildup and the collapse when observed.", "category": "quantum_information"},
    {"prompt": "Quantum teleportation. Transfer an unknown qubit's state using entanglement plus two classical bits, without moving the particle. Animate the protocol: entangle, measure, send classical bits, apply correction.", "category": "quantum_information"},
    {"prompt": "Grover's search. Finding one item in an unsorted list of N takes sqrt(N) quantum steps, not N. Animate the amplitude amplification: the target's probability bar rising as the others shrink over iterations.", "category": "quantum_information"},
    {"prompt": "Bell's inequality. Local hidden variables cap a certain correlation at 2, but quantum mechanics reaches 2*sqrt(2). Plot the correlation vs measurement angle and mark where the quantum curve exceeds the classical bound.", "category": "quantum_information"},
    {"prompt": "The quantum Zeno effect. Watching a decaying quantum system often enough freezes it. Plot survival probability vs measurement frequency and show it approaching 1 as you measure faster.", "category": "quantum_information"},
    {"prompt": "Shor's algorithm intuition. Factoring big numbers is hard classically, but a quantum computer finds the period of a modular function fast, and the period reveals the factors. Plot the periodic function and show the period-to-factor step.", "category": "quantum_information"},
    {"prompt": "Quantum tunneling. A particle with less energy than a barrier still appears on the other side. Animate a wavefunction hitting a barrier, partially transmitting, and plot tunneling probability vs barrier width dropping exponentially.", "category": "quantum_information"},
    {"prompt": "The uncertainty principle as a Fourier trade-off. A wave packet localized in position must be spread in momentum. Animate narrowing a Gaussian in space and watch its Fourier transform widen, with the product staying above hbar/2.", "category": "quantum_information"},
    {"prompt": "Decoherence: why big things don't show quantum behavior. Couple a superposed qubit to a noisy environment and the interference terms wash out fast. Animate the off-diagonal density-matrix terms decaying to zero.", "category": "quantum_information"},

    # ── PARADOXES (10) ─────────────────────────────────────────────────────────
    {"prompt": "Zeno's Achilles and the tortoise. Achilles must reach where the tortoise was, infinitely often, yet he passes it. Animate the shrinking gaps and show the infinite geometric series summing to a finite catch-up time.", "category": "paradoxes"},
    {"prompt": "The Sleeping Beauty problem. Woken once on heads, twice on tails, what credence should she give heads on waking? Simulate many runs and tally the awakenings to expose the 1/2 vs 1/3 tension.", "category": "paradoxes"},
    {"prompt": "The unexpected hanging paradox. A surprise exam can't be on Friday (it'd be predictable), so not Thursday, and so on, yet it still surprises. Walk through the backward induction and where the reasoning breaks.", "category": "paradoxes"},
    {"prompt": "The two-envelope paradox. One envelope has twice the other; switching seems to always raise your expected value, which is absurd. Lay out the flawed expectation calculation and the resolution.", "category": "paradoxes"},
    {"prompt": "Russell's paradox. The set of all sets that don't contain themselves both contains and doesn't contain itself. Animate the self-reference loop and explain why it broke naive set theory.", "category": "paradoxes"},
    {"prompt": "The Ship of Theseus, made quantitative. Replace one plank at a time; when is it a different ship? Frame identity as a threshold on a continuous swap fraction and show why no single plank is the tipping point.", "category": "paradoxes"},
    {"prompt": "The raven paradox. 'All ravens are black' is logically confirmed by seeing a green apple (a non-black non-raven). Animate the contrapositive and show why the confirmation is real but vanishingly weak.", "category": "paradoxes"},
    {"prompt": "Newcomb's problem. A predictor fills boxes based on your future choice; one-boxers get rich, yet two-boxing dominates. Lay out the payoff matrix and the clash between expected value and dominance.", "category": "paradoxes"},
    {"prompt": "The potato paradox. 100kg of potatoes at 99% water, dried to 98% water, weighs only 50kg. Animate the water and solids as blocks and show the solid mass forcing the halving.", "category": "paradoxes"},
    {"prompt": "Hilbert's Grand Hotel. A full hotel with infinitely many rooms still fits infinitely many new guests by shifting everyone. Animate the room reassignment for one new guest, then for infinitely many.", "category": "paradoxes"},

    # ── MATHEMATICAL PATTERNS (8) ──────────────────────────────────────────────
    {"prompt": "The Fibonacci sequence hidden in a sunflower. Seed spirals count 34 one way and 55 the other, consecutive Fibonacci numbers, because the golden angle packs seeds most efficiently. Animate seeds placed at 137.5 degrees forming the spirals.", "category": "mathematical_patterns"},
    {"prompt": "The Collatz conjecture. Any number, halved if even or tripled-plus-one if odd, seems to always reach 1. Animate a few trajectories bouncing wildly then crashing to 1, and plot the stopping times' surprising structure.", "category": "mathematical_patterns"},
    {"prompt": "Pascal's triangle hides everything: powers of 2, Fibonacci diagonals, and Sierpinski's fractal in its odd entries. Animate coloring the odd numbers to reveal the triangle fractal emerging.", "category": "mathematical_patterns"},
    {"prompt": "The Mandelbrot set boundary. Iterate z -> z²+c and color by escape time; the boundary is infinitely detailed. Animate zooming into a seahorse-valley and show the same shapes recurring at every scale.", "category": "mathematical_patterns"},
    {"prompt": "Ulam's spiral. Write integers in a square spiral and mark the primes; they cluster onto diagonal lines instead of scattering. Animate the spiral filling and the diagonal streaks appearing.", "category": "mathematical_patterns"},
    {"prompt": "The golden ratio from continued fractions. The 'most irrational' number is 1 + 1/(1 + 1/(1 + ...)), the hardest to approximate by fractions. Animate the continued fraction and its slow-converging rational approximations.", "category": "mathematical_patterns"},
    {"prompt": "Lissajous figures. Two perpendicular sine waves with a frequency ratio trace closed curves; simple ratios give simple shapes. Animate sweeping the ratio and watch the figure morph from a line to an ellipse to a pretzel.", "category": "mathematical_patterns"},
    {"prompt": "The prime counting function and the log. The number of primes below n is roughly n/ln(n); primes thin out but never stop. Plot the actual prime count against the estimate and show the slow, steady agreement.", "category": "mathematical_patterns"},
]


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
        time.sleep(0.2)
    print(f"\nTotal: {sent} sent, {failed} failed  (out of {len(TOPICS)} topics)")


if __name__ == "__main__":
    push_topics()
