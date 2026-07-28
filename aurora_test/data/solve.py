#!/usr/bin/env python3
"""
Aurora physics solve.  Everything the video puts on screen is computed here and
baked to aurora.json; the scene reads that file and never invents a number.

Three things are genuinely COMPUTED (not looked up):

  1. Quenching altitudes.  Each auroral emission has a radiative lifetime.  If a
     collision arrives before the photon leaves, the energy goes into heat
     instead of light.  So each line has a floor altitude, set by where the
     collision rate falls below 1/tau.  That is the spine of the piece:
     LIFETIME SETS ALTITUDE SETS COLOUR.

  2. Electron stopping altitudes vs energy, from the Rees (1963) range-energy
     relation matched against an NRLMSIS-2.1 column mass density.

  3. Volume emission profiles for the three lines, which drive the colour ramp
     of the aurora curtain in the render.  (This one is a SCHEMATIC model -- see
     the header on emission_profiles().  Its peak altitudes are validated
     against published values rather than tuned to them.)

Atmosphere: NRLMSIS 2.1 via pymsis 0.12.0.  Fixed inputs so the solve is
reproducible without network access:
     2024-03-20 22:00 UT, 68.0 N, 20.0 E (Kiruna, in the auroral oval),
     F10.7 = 150 sfu, F10.7a = 150 sfu, Ap = 15 (moderately disturbed).
"""
import json
import numpy as np
from pymsis import calculate, Variable

OUT = "aurora.json"

# ---------------------------------------------------------------------------
# SPECTROSCOPY.  Sources recorded in `cite` and carried through into the JSON so
# the provenance travels with the number.
# ---------------------------------------------------------------------------
LINES = {
    "green": {
        "lam_nm": 557.7,
        "species": "O",
        "state": "O(1S0)",
        "trans": "O I  2p4 1S0 -> 2p4 1D2",
        # Total radiative loss of O(1S) is the sum of the 557.7 nm (->1D2) and
        # 297.2 nm (->3P1) branches.  tau = 1/sum(A).
        # NIST ASD (Wiese, Fuhr & Deters 1996, JPCRD Monograph 7).
        # Three decay channels; sum -> tau.  Branching into 557.7 = 94.3%.
        "A_557": 1.26,      # 1S0 -> 1D2, E2, acc. B+ (<=7%)
        "A_297": 7.54e-2,   # 1S0 -> 3P1, M1, acc. B+
        "A_296": 2.42e-4,   # 1S0 -> 3P2, E2, acc. C+
        "cite": "NIST ASD O I; Wiese, Fuhr & Deters 1996 JPCRD Mono. 7",
    },
    "red": {
        "lam_nm": 630.0,
        "species": "O",
        "state": "O(1D2)",
        "trans": "O I  2p4 1D2 -> 2p4 3P2",
        # O(1D) decays to the 3P2 (630.0 nm), 3P1 (636.4 nm) and 3P0 (639.2 nm)
        # levels.  639.2 is magnetic-dipole forbidden to negligible strength.
        # NIST ASD.  Sum -> tau = 133.8 s.  The widely repeated 110 s
        # corresponds to the older Garstang / Kernahan & Pang A-values and is
        # legacy; every modern determination clusters at 130-134 s.
        "A_630": 5.63e-3 + 2.11e-5,   # 1D2 -> 3P2 (M1 + E2)
        "A_636": 1.82e-3 + 3.39e-6,   # 1D2 -> 3P1 (M1 + E2)
        "A_639": 8.60e-7,             # 1D2 -> 3P0 (E2)
        "cite": "NIST ASD O I 1D2 term; cf. Storey & Zeippen 2000",
    },
    "blue": {
        "lam_nm": 427.8,
        "species": "N2",
        "state": "N2+ (B 2Sigma_u+, v'=0)",
        "trans": "N2+ First Negative (0,1)  B 2Sigma_u+ -> X 2Sigma_g+",
        # B-state TOTAL radiative lifetime.  Schmoranzer+1989 61.35+-0.29 ns,
        # Scholl+1995 61.8+-0.5 ns; recommended ~61-62 ns (Ferchichi et al.
        # 2022, A&A 661 A132).  NOTE: the (0,1) BAND alone has A ~ 3.7e6 s^-1,
        # a 270 ns band lifetime; ~23% of B-state decays go into 427.8 nm.
        "tau_ns": 62.0,
        "band_tau_ns": 270.0,
        "cite": "Ferchichi et al. 2022 A&A 661 A132; Schmoranzer et al. 1989",
    },
}

# Quenching rate coefficients, cm^3 s^-1, evaluated at the LOCAL NRLMSIS
# temperature -- these are strongly Arrhenius and the thermosphere runs from
# ~180 K at 90 km to ~1000 K at 300 km, so a single 300 K value is not usable.
#
# O(1S)+O2 is the one that most often gets misquoted: 4.0e-12 is the Arrhenius
# PRE-EXPONENTIAL, not the rate.  The actual coefficient at 200 K is 5.3e-14,
# about 75x smaller.  Getting this wrong moves the green-line floor by tens of km.
QUENCH = {
    # O(1S).  Slanger, Black & Wood 1972 CPL 17, 401 (measured 255-375 K,
    # E/R = 870 +- 175 K); Slanger & Black 1976 for the atomic-O channel.
    ("green", "O2"): lambda T: 4.0e-12 * np.exp(-865.0 / T),
    ("green", "O"):  lambda T: np.full_like(T, 2.0e-14),
    ("green", "N2"): lambda T: np.full_like(T, 5.0e-17),   # negligible
    # O(1D).  IUPAC / Atkinson et al. 2004 ACP 4, 1461, datasheets I.A3.36 and
    # I.A1.3.  The atomic-O channel is genuinely poorly constrained -- the
    # literature spans 1e-12 to 3e-12; NCAR GLOW's 3.0e-12 is used here and is
    # at the top of that range.  It matters for 630.0 nm in the F-region.
    ("red", "N2"): lambda T: 1.8e-11 * np.exp(107.0 / T),
    ("red", "O2"): lambda T: 3.2e-11 * np.exp(67.0 / T),
    ("red", "O"):  lambda T: np.full_like(T, 3.0e-12),
}

# ---------------------------------------------------------------------------
# ATMOSPHERE
# ---------------------------------------------------------------------------
def atmosphere(z_km):
    """NRLMSIS 2.1 number densities (cm^-3) and mass density (g cm^-3)."""
    d = np.datetime64("2024-03-20T22:00")
    out = calculate(d, 20.0, 68.0, z_km, 150.0, 150.0, [[15] * 7])
    o = out[0, 0, 0, :, :]
    M3_TO_CM3 = 1e-6                 # m^-3 -> cm^-3
    KGM3_TO_GCM3 = 1e-3              # kg m^-3 -> g cm^-3
    return {
        "z": z_km,
        "N2":  o[:, Variable.N2] * M3_TO_CM3,
        "O2":  o[:, Variable.O2] * M3_TO_CM3,
        "O":   o[:, Variable.O] * M3_TO_CM3,
        "rho": o[:, Variable.MASS_DENSITY] * KGM3_TO_GCM3,
        "T":   o[:, Variable.TEMPERATURE],
    }


def column_mass(z_km, rho_gcm3):
    """Vertical column mass density above each altitude, g cm^-2.

    Integrated downward from the top of the grid.  The neglected mass above
    500 km is ~1e-9 g/cm^2, six orders below the shallowest range we use.
    """
    dz_cm = np.gradient(z_km) * 1e5
    # cumulative sum from the top
    return np.cumsum((rho_gcm3 * dz_cm)[::-1])[::-1]


# ---------------------------------------------------------------------------
# 1. QUENCHING ALTITUDES
# ---------------------------------------------------------------------------
def quench_altitudes(atm):
    """Altitude at which the collisional loss rate equals the radiative rate.

    Below it the emission is progressively extinguished; above it the photon
    almost always escapes.  The survival fraction is A/(A + sum_i k_i n_i).
    """
    res = {}

    # --- green, O(1S)
    A_green = (LINES["green"]["A_557"] + LINES["green"]["A_297"]
               + LINES["green"]["A_296"])
    T = atm["T"]
    q_green = (QUENCH[("green", "O2")](T) * atm["O2"]
               + QUENCH[("green", "O")](T) * atm["O"]
               + QUENCH[("green", "N2")](T) * atm["N2"])
    res["green"] = _cross(atm["z"], q_green, A_green)
    res["green"].update(tau_s=1.0 / A_green, A_total=A_green,
                        z10_km=_cross(atm["z"], q_green, A_green * 9.0)["z_km"],
                        surv=A_green / (A_green + q_green))

    # --- red, O(1D)
    A_red = (LINES["red"]["A_630"] + LINES["red"]["A_636"]
             + LINES["red"]["A_639"])
    q_red = (QUENCH[("red", "N2")](T) * atm["N2"]
             + QUENCH[("red", "O2")](T) * atm["O2"]
             + QUENCH[("red", "O")](T) * atm["O"])
    res["red"] = _cross(atm["z"], q_red, A_red)
    res["red"].update(tau_s=1.0 / A_red, A_total=A_red,
                      z10_km=_cross(atm["z"], q_red, A_red * 9.0)["z_km"],
                      surv=A_red / (A_red + q_red))

    # --- blue, N2+ (B).  62 ns is so fast that nothing in the atmosphere can
    # compete.  Report the density that WOULD be needed, at a gas-kinetic rate
    # coefficient of 1e-10 cm^3/s, to make the point quantitatively.
    A_blue = 1.0 / (LINES["blue"]["tau_ns"] * 1e-9)
    n_needed = A_blue / 1e-10                      # cm^-3
    res["blue"] = {
        "z_km": None, "tau_s": 1.0 / A_blue, "A_total": A_blue,
        "n_needed_cm3": n_needed,
        "surv": np.ones_like(atm["z"]),
    }
    return res


def _cross(z, q, A):
    """Highest altitude at which q(z) == A, by log-linear interpolation."""
    f = np.log(q / A)
    idx = np.where(np.diff(np.sign(f)) != 0)[0]
    if len(idx) == 0:
        return {"z_km": None}
    i = idx[-1]
    t = -f[i] / (f[i + 1] - f[i])
    return {"z_km": float(z[i] + t * (z[i + 1] - z[i]))}


# ---------------------------------------------------------------------------
# 2. ELECTRON STOPPING
# ---------------------------------------------------------------------------
# Rees (1963), Planet. Space Sci. 11, 1209: range of a monoenergetic electron
# in air, R [g cm^-2] = 4.30e-7 + 5.36e-6 * E^1.67,  E in keV.
def rees_range(E_keV):
    return 4.30e-7 + 5.36e-6 * np.power(E_keV, 1.67)


def stopping_altitude(E_keV, z, colmass):
    """Altitude where the overhead column mass equals the electron's range."""
    R = rees_range(E_keV)
    if R < colmass[-1] or R > colmass[0]:
        return None
    return float(np.interp(np.log(R), np.log(colmass[::-1]), z[::-1]))


# ---------------------------------------------------------------------------
# 3. EMISSION PROFILES  (SCHEMATIC -- read this before trusting the shape)
# ---------------------------------------------------------------------------
# The volume emission rate is modelled as
#
#     eta_X(z)  ~  rho(z) * Lambda(chi(z)) * f_X(z) * S_X(z)
#
#   rho * Lambda   energy deposited per unit volume.  Lambda is the normalised
#                  energy-dissipation function of fractional range chi; the form
#                  used here is a smooth bump of the same SHAPE as the Rees
#                  (1963) tabulation (peak near chi ~ 0.6, vanishing at chi = 0
#                  and chi ~ 1.1).  It is a FIT TO THE SHAPE, not the tabulation
#                  itself.
#   f_X            number fraction of the excitable target (O, or N2)
#   S_X            the quenching survival fraction computed above -- the only
#                  part of this that is first-principles
#
# What this deliberately omits: the Barth mechanism (N2(A) + O -> O(1S) + N2),
# which is believed to dominate 557.7 nm production; dissociative recombination
# O2+ + e -> O(1D), which contributes to 630.0 nm; secondary-electron transport;
# and any cross-section energy dependence.  The peak altitudes it produces are
# CHECKED against published values in validate() rather than tuned to them, but
# treat the shape as illustrative, not as a radiative-transfer result.
def rees_lambda(chi):
    lam = np.where((chi > 0) & (chi < 1.12),
                   np.power(np.clip(chi, 1e-9, None), 1.4)
                   * np.exp(-2.9 * np.power(np.clip(chi, 1e-9, None), 2.3)),
                   0.0)
    return lam


# Relative COLUMN intensities of the three lines.  The deposition model has no
# excitation cross-sections in it, so it cannot predict how bright one line is
# relative to another -- left alone it makes 427.8 nm swamp everything, because
# N2 outnumbers atomic O 20:1 at 100 km and the model would read that as twenty
# times the blue emission.  The vertical SHAPE of each profile is solved; the
# relative NORMALISATION is calibrated to the intensity ratios of a typical
# moderately bright discrete arc.  An observational input, not a derived result;
# the piece does not put these three numbers on screen.
COLUMN_RATIO = {"green": 1.00, "red": 0.35, "blue": 0.20}


def maxwellian_profiles(atm, colmass, surv, E0_keV, nE=44):
    """Emission profiles for a Maxwellian differential number flux.

    phi(E) ~ E exp(-E/E0), the standard auroral form.  Integrating over it
    rather than using one monoenergetic beam matters twice over: it is what real
    precipitation looks like, and a single beam produces an emission layer only
    a few km thick -- which would draw an auroral curtain as a thin bright line.
    """
    Es = np.logspace(np.log10(0.15), np.log10(60.0), nE)
    w = Es * np.exp(-Es / E0_keV) * Es          # phi(E) dE, log-spaced -> x E
    w = w / w.sum()
    acc = {"green": 0.0, "red": 0.0, "blue": 0.0}
    for E, wi in zip(Es, w):
        e = emission_profiles(atm, colmass, surv, float(E))
        for k in acc:
            acc[k] = acc[k] + wi * e[k]
    return acc


def emission_profiles(atm, colmass, surv, E_keV):
    R = rees_range(E_keV)
    chi = colmass / R
    dep = atm["rho"] * rees_lambda(chi)
    n_tot = atm["N2"] + atm["O2"] + atm["O"]
    f_O = atm["O"] / n_tot
    f_N2 = atm["N2"] / n_tot
    return {
        "green": dep * f_O * surv["green"]["surv"],
        "red":   dep * f_O * surv["red"]["surv"],
        "blue":  dep * f_N2,
    }


def peak_alt(z, eta):
    if eta.max() <= 0:
        return None
    return float(z[int(np.argmax(eta))])


# ---------------------------------------------------------------------------
# COLOUR.  The three lines are monochromatic, so their screen colours are not a
# choice -- they follow from the CIE 1931 observer.  Using the analytic
# multi-lobe Gaussian fit of Wyman, Sloan & Shirley (2013), "Simple Analytic
# Approximations to the CIE XYZ Color Matching Functions", JCGT 2(2), which is
# accurate to about 1% of peak.
#
# This also gets the piece's best physical joke for free: ybar IS the photopic
# luminous efficiency, and ybar(557.7)/ybar(630.0) is about 4.  Red aurora look
# faint next to green partly because the eye is four times less sensitive there,
# not only because there is less of it.
# ---------------------------------------------------------------------------
def _g(x, mu, s1, s2):
    s = np.where(x < mu, s1, s2)
    return np.exp(-0.5 * ((x - mu) / s) ** 2)


def cie_xyz(lam):
    lam = np.asarray(lam, dtype=float)
    x = (1.056 * _g(lam, 599.8, 37.9, 31.0)
         + 0.362 * _g(lam, 442.0, 16.0, 26.7)
         - 0.065 * _g(lam, 501.1, 20.4, 26.2))
    y = (0.821 * _g(lam, 568.8, 46.9, 40.5)
         + 0.286 * _g(lam, 530.9, 16.3, 31.1))
    z = (1.217 * _g(lam, 437.0, 11.8, 36.0)
         + 0.681 * _g(lam, 459.0, 26.0, 13.8))
    return np.stack([x, y, z], axis=-1)


# XYZ (D65) -> linear sRGB
M_XYZ_RGB = np.array([[3.2406, -1.5372, -0.4986],
                      [-0.9689, 1.8758, 0.0415],
                      [0.0557, -0.2040, 1.0570]])


def xyz_to_lin_srgb(xyz):
    rgb = xyz @ M_XYZ_RGB.T
    # Monochromatic stimuli sit outside the sRGB gamut, so one or two channels
    # come out negative.  Clipping desaturates them toward the gamut edge, which
    # is the standard (and only) thing a display can do.
    return np.clip(rgb, 0.0, None)


# ---------------------------------------------------------------------------
# SOLAR WIND / GEOMETRY
# ---------------------------------------------------------------------------
AU_KM = 149_597_870.7        # IAU 2012 exact definition of the astronomical unit
R_E_KM = 6371.0              # IUGG mean Earth radius


def transit_days(v_kms):
    return AU_KM / v_kms / 86400.0


def shue_magnetopause(Bz_nT=-5.0, Dp_nPa=2.0):
    """Shue et al. (1997), JGR 102, 9497:  r = r0 (2/(1+cos theta))^alpha.

    Returns r0 in R_E and the flaring exponent alpha, for a moderately
    southward IMF and typical dynamic pressure -- i.e. conditions that actually
    produce an aurora.
    """
    if Bz_nT >= 0:
        r0 = (11.4 + 0.013 * Bz_nT) * Dp_nPa ** (-1.0 / 6.6)
    else:
        r0 = (11.4 + 0.140 * Bz_nT) * Dp_nPa ** (-1.0 / 6.6)
    alpha = (0.58 - 0.007 * Bz_nT) * (1.0 + 0.024 * np.log(Dp_nPa))
    return float(r0), float(alpha)


# ---------------------------------------------------------------------------
def validate(rows):
    """Compare the solve against published values.  Printed, never silenced."""
    print("\n=== VALIDATION against published values " + "=" * 30)
    checks = [
        ("O(1S) radiative lifetime",
         rows["quench"]["green"]["tau_s"], 0.749, "s",
         "NIST A-sum 1.335 s^-1; note GLOW uses K&P1975 -> 0.91 s"),
        ("O(1D) radiative lifetime",
         rows["quench"]["red"]["tau_s"], 133.8, "s",
         "NIST A-sum; the folklore 110 s is legacy Garstang-era values"),
        # NOTE ON DEFINITION.  z_km is where HALF the excited atoms still
        # radiate; z10_km is where only 10% do, which is closer to what an
        # observer calls the "lower border" because emission is still visible
        # well into the quenched regime.  Both are reported; the video quotes
        # the 50% figure and says so.
        ("green 50% survival",
         rows["quench"]["green"]["z_km"], 100.0, "km",
         "green lower border observed near 90-100 km"),
        # green 10% survival falls below the 80 km grid floor once the correct
        # (Arrhenius-evaluated) O(1S)+O2 rate is used -- i.e. 557.7 nm is barely
        # quenched anywhere an aurora actually reaches. Reported, not gated.
        ("red 50% survival",
         rows["quench"]["red"]["z_km"], 300.0, "km",
         "630.0 nm is strongly quenched below ~250-300 km"),
        ("red 10% survival",
         rows["quench"]["red"]["z10_km"], 220.0, "km",
         "observed red floor ~200-250 km"),
        ("magnetopause standoff",
         rows["magnetosphere"]["magnetopause_RE"], 10.0, "R_E",
         "Shue+1997 at Bz=-5 nT, Dp=2 nPa; quiet value ~10-11"),
        # Whiter et al. 2023, Ann. Geophys. 41, 1: measured mean peak emission
        # altitudes 114.84 +- 0.06 km (557.7) and 116.55 +- 0.07 km (427.8).
        ("557.7 peak alt, mixed spectrum",
         rows["mix_peaks"]["green"], 114.84, "km", "Whiter et al. 2023, MEASURED"),
        ("427.8 peak alt, mixed spectrum",
         rows["mix_peaks"]["blue"], 116.55, "km", "Whiter et al. 2023, MEASURED"),
        ("630.0 peak alt, mixed spectrum",
         rows["mix_peaks"]["red"], 240.0, "km", "red aurora peaks ~200-300 km"),
        # These assume VERTICAL incidence.  Real precipitation is closer to
        # isotropic, which traverses more mass per km of descent and therefore
        # stops 10-30 km HIGHER than these figures.  Stated as a limitation.
        ("stopping altitude, 1 keV",
         rows["stopping"]["1.0"], 150.0, "km", "vertical incidence; isotropic is higher"),
        ("stopping altitude, 10 keV",
         rows["stopping"]["10.0"], 105.0, "km", "Rees: ~100-110 km"),
        ("Sun-Earth transit at 400 km/s",
         rows["solar_wind"]["transit_400_days"], 4.33, "d",
         "1 AU / 400 km/s"),
    ]
    worst = 0.0
    for name, got, exp, unit, note in checks:
        if got is None:
            print(f"  {name:34s}  NONE  -- expected ~{exp} {unit}")
            continue
        rel = abs(got - exp) / abs(exp)
        worst = max(worst, rel)
        flag = "ok " if rel < 0.30 else "!! "
        print(f"  {flag}{name:34s} {got:9.3f} {unit:3s}  vs published ~{exp:<7.4g} "
              f"({rel*100:5.1f}%)   {note}")
    print(f"  worst relative deviation: {worst*100:.1f}%")
    print("=" * 72)


def main():
    mp_r0, mp_alpha = shue_magnetopause(-5.0, 2.0)
    z = np.arange(80.0, 500.5, 1.0)
    atm = atmosphere(z)
    colmass = column_mass(z, atm["rho"])
    q = quench_altitudes(atm)

    energies = [0.3, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0]
    stopping = {f"{E}": stopping_altitude(E, z, colmass) for E in energies}

    peaks, profiles = {}, {}
    for E in energies:
        eta = emission_profiles(atm, colmass, q, E)
        peaks[f"{E}"] = {k: peak_alt(z, v) for k, v in eta.items()}
        profiles[f"{E}"] = eta

    # ---- the colour ramp the render actually draws -------------------------
    # The curtain is lit by a MIXED spectrum: a hard component making the bright
    # green/blue lower body and a soft one making the diffuse red top.  The two
    # weights below are chosen for the picture and are NOT derived -- flagged
    # here so nobody mistakes them for physics.  Everything downstream of them
    # (which altitude gets which colour, and how bright) is the solve.
    # Two Maxwellian populations, which is what a discrete arc actually carries:
    # an inverted-V accelerated beam plus a soft component.  The characteristic
    # energies are typical measured values; the WEIGHT between them is a
    # picture choice and is flagged as such.
    HARD_E, HARD_W, SOFT_E, SOFT_W = 4.0, 1.0, 0.35, 0.60
    inten = {"green": 0.0, "red": 0.0, "blue": 0.0}
    for E0, w in [(HARD_E, HARD_W), (SOFT_E, SOFT_W)]:
        e = maxwellian_profiles(atm, colmass, q, E0)
        for k in inten:
            inten[k] = inten[k] + w * e[k]

    # Apply the observational column calibration (see COLUMN_RATIO above).
    dz_cm = np.gradient(z) * 1e5
    for k in inten:
        inten[k] = inten[k] / max(float((inten[k] * dz_cm).sum()), 1e-30) \
                   * COLUMN_RATIO[k]
    mix_peaks = {k: peak_alt(z, inten[k]) for k in inten}

    # Photon rate -> CIE XYZ -> linear sRGB.  The eye's response is doing real
    # work here: ybar(557.7) = %.3f vs ybar(630.0) = %.3f.
    cie = {k: cie_xyz(LINES[k]["lam_nm"]) for k in inten}
    xyz = sum(inten[k][:, None] * cie[k][None, :] for k in inten)
    rgb_lin = xyz_to_lin_srgb(xyz)
    rgb_lin /= max(rgb_lin.max(), 1e-30)

    # Sample the ramp at 128 points over the altitude band the curtain spans.
    Z0, Z1 = 85.0, 420.0
    zs = np.linspace(Z0, Z1, 128)
    ramp = np.stack([np.interp(zs, z, rgb_lin[:, c]) for c in range(3)], axis=1)
    ramp /= max(ramp.max(), 1e-9)

    # Per-line display colours (unit peak), for swatches in the render.
    swatch = {}
    for k in inten:
        c = xyz_to_lin_srgb(cie[k][None, :])[0]
        swatch[k] = (c / max(c.max(), 1e-9)).round(5).tolist()
    ybar = {k: float(cie[k][1]) for k in inten}

    rows = {
        "_meta": {
            "atmosphere": "NRLMSIS 2.1 via pymsis 0.12.0",
            "conditions": "2024-03-20 22:00 UT, 68.0N 20.0E, F10.7=150, F10.7a=150, Ap=15",
            "range_energy": "Rees (1963) Planet. Space Sci. 11, 1209",
            "au_km": AU_KM, "earth_radius_km": R_E_KM,
        },
        "lines": LINES,
        "quench": {
            k: {kk: (float(vv) if isinstance(vv, (int, float, np.floating)) else None)
                for kk, vv in v.items() if kk != "surv"}
            for k, v in q.items()
        },
        "stopping": stopping,
        "peaks": peaks,
        "ramp": {"z0": Z0, "z1": Z1, "rgb": ramp.round(5).tolist(),
                 "mix": {"hard_keV": HARD_E, "hard_w": HARD_W,
                         "soft_keV": SOFT_E, "soft_w": SOFT_W}},
        "swatch": swatch,
        "mix_peaks": mix_peaks,
        "column_ratio": COLUMN_RATIO,
        "ybar": ybar,
        "ybar_ratio_green_red": ybar["green"] / ybar["red"],
        "atm_samples": {
            f"{int(zz)}": {
                "N2": float(np.interp(zz, z, atm["N2"])),
                "O":  float(np.interp(zz, z, atm["O"])),
                "O2": float(np.interp(zz, z, atm["O2"])),
                "colmass_gcm2": float(np.interp(zz, z, colmass)),
            } for zz in [90, 100, 110, 120, 150, 200, 250, 300, 400]
        },
        "solar_wind": {
            "v_slow_kms": 300, "v_typ_kms": 400, "v_fast_kms": 750,
            "n_p_cm3": 5.0,
            "transit_400_days": transit_days(400.0),
            "transit_750_days": transit_days(750.0),
            "au_km": AU_KM,
        },
        "magnetosphere": {
            "magnetopause_RE": mp_r0,
            "magnetopause_alpha": mp_alpha,
            "magnetopause_model": "Shue et al. (1997) JGR 102, 9497; Bz=-5 nT, Dp=2 nPa",
            "oval_lat_deg": [65, 70],
            "R_E_km": R_E_KM,
            # Magnetic dip angle at 68 deg geomagnetic latitude, from the
            # centred-dipole relation tan(I) = 2 tan(lambda).  This is the tilt
            # the auroral rays are drawn at in the render.
            "dip_deg_at_68": float(np.degrees(np.arctan(2 * np.tan(np.radians(68.0))))),
        },
    }
    rows["quench"]["blue"]["n_needed_cm3"] = float(q["blue"]["n_needed_cm3"])

    print("\n--- colour (CIE 1931, Wyman et al. 2013 fit) ---")
    for k in ("blue", "green", "red"):
        print(f"{k:6s} {LINES[k]['lam_nm']:6.1f} nm  ybar={ybar[k]:.4f}  "
              f"linear sRGB {['%.3f' % c for c in swatch[k]]}")
    print(f"       eye is {rows['ybar_ratio_green_red']:.2f}x more sensitive at "
          f"557.7 nm than at 630.0 nm")
    print(f"\n--- magnetopause (Shue+1997, Bz=-5 nT, Dp=2 nPa) ---")
    print(f"subsolar standoff r0 = {mp_r0:.2f} R_E = {mp_r0 * R_E_KM:,.0f} km ; "
          f"flaring alpha = {mp_alpha:.3f}")

    print("--- atmosphere (NRLMSIS 2.1), cm^-3 ---")
    print(f"{'z':>5} {'N2':>10} {'O':>10} {'O2':>10} {'col g/cm2':>11}")
    for zz in [90, 100, 110, 120, 150, 200, 250, 300, 400]:
        s = rows["atm_samples"][str(zz)]
        print(f"{zz:5d} {s['N2']:10.3e} {s['O']:10.3e} {s['O2']:10.3e} {s['colmass_gcm2']:11.3e}")

    print("\n--- quenching ---")
    for k in ("green", "red", "blue"):
        v = rows["quench"][k]
        L = LINES[k]
        zk = v["z_km"]
        print(f"{k:6s} {L['lam_nm']:6.1f} nm  {L['state']:22s} "
              f"tau={v['tau_s']:.3e} s  floor={'n/a' if zk is None else f'{zk:6.1f} km'}")
    print(f"       427.8 nm would need {rows['quench']['blue']['n_needed_cm3']:.3e} cm^-3 "
          f"to be quenched -- denser than the atmosphere below ~30 km.")

    print("\n--- electron stopping (Rees 1963) ---")
    for E in energies:
        s = stopping[f"{E}"]
        p = peaks[f"{E}"]
        print(f"{E:6.1f} keV  R={rees_range(E):.3e} g/cm2  stops at "
              f"{'--' if s is None else f'{s:6.1f}'} km   peaks G/R/B = "
              f"{p['green']}/{p['red']}/{p['blue']} km")

    print("\n--- solar wind ---")
    sw = rows["solar_wind"]
    print(f"1 AU = {sw['au_km']:,.1f} km")
    print(f"400 km/s -> {sw['transit_400_days']:.2f} days ; "
          f"750 km/s -> {sw['transit_750_days']:.2f} days")
    print(f"magnetic dip at 68N: {rows['magnetosphere']['dip_deg_at_68']:.1f} deg "
          f"({90 - rows['magnetosphere']['dip_deg_at_68']:.1f} deg off vertical)")

    validate(rows)

    with open(OUT, "w") as f:
        json.dump(rows, f, indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
