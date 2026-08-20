#!/usr/bin/env python3
"""
Pre-registered gates on a rendered frame sequence.

SSIM needs a reference, and an original piece has none -- so rather than invent a
number that sounds rigorous, this gates on the failures that actually ruin
renders: dead frames, an empty first frame (the thumbnail), lifted blacks
(bloom hazing), blown highlights, and content outside the platform-safe box.

These catch a broken render. They cannot tell you whether the piece is any good
-- that still needs looking at a contact sheet.

SPEED. Decoding full-res PNGs dominates, so frames are decoded in parallel and
--stride gates a subset. Use a stride while iterating and one full pass at the
end: a stride can step over a single bad frame, which is exactly what the
dead-frame gate exists to catch.

    python3 check.py --frames out/frames --stride 8      # fast preflight
    python3 check.py --frames out/frames                 # full, before shipping
    python3 check.py --frames out/frames --exempt 391-418 --beats "intro:0-95,body:96-600"
"""

import argparse
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from PIL import Image

_CFG = {}


def _init(safe, lit_threshold):
    _CFG["safe"] = safe
    _CFG["lit"] = lit_threshold


def _measure(path):
    """Per-frame statistics. Top-level so it survives pickling to the pool."""
    x0, x1, y0, y1 = _CFG["safe"]
    im = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    # Explicit weighted sum, not `im @ REC709`: float32 matmul on a 3D array
    # trips spurious divide/overflow warnings on some BLAS builds.
    luma = 0.2126 * im[:, :, 0] + 0.7152 * im[:, :, 1] + 0.0722 * im[:, :, 2]
    g = im.max(axis=2)
    mask = g > _CFG["lit"]
    box = np.zeros_like(mask)
    box[y0:y1, x0:x1] = True
    return (
        float(mask.mean()),
        float(luma.mean()),
        # Peak channel value. The dead-frame gate keys off THIS, not the lit
        # fraction: a deliberately dark opening -- a night sky, a black-field
        # emissive piece -- can have almost nothing above the lit threshold and
        # still be a perfectly composed frame. A measured example: frame 0 of an
        # authored piece had 0.12% of pixels above 28 but a peak of 170 and 72%
        # of pixels non-zero. The lit-fraction test called it dead. It was not.
        # Black level as a low percentile of luma, NOT a corner patch: in a 3D
        # scene the corners hold real lit geometry, so a corner probe measures
        # content and fails honest frames.
        float(np.percentile(luma, 1)),
        float((g >= 254).mean()),
        int((mask & ~box).sum()),
        float(g.max()),
    )


def parse_ranges(spec):
    out = set()
    for part in filter(None, (s.strip() for s in (spec or "").split(","))):
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def parse_beats(spec):
    beats = []
    for part in filter(None, (s.strip() for s in (spec or "").split(","))):
        try:
            name, rng = part.split(":")
            a, b = rng.split("-")
            beats.append((name, int(a), int(b)))
        except ValueError:
            # These are typed by hand on a long command line; a traceback here
            # costs a whole iteration cycle to a missing colon.
            sys.exit(f"bad --beats entry {part!r} -- expected name:first-last, "
                     f'e.g. --beats "intro:0-95,body:96-600"')
    return beats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="out/frames")
    ap.add_argument("--stride", type=int, default=1,
                    help="gate every Nth frame; fast preflight, but can step over a bad frame")
    ap.add_argument("--exempt", default="", help="frame ranges exempt from look gates, e.g. 391-418")
    ap.add_argument("--beats", default="", help='name:a-b,name:a-b for a per-beat report')
    ap.add_argument("--lit-threshold", type=int, default=28)
    ap.add_argument("--max-black", type=float, default=24.0,
                    help="a frame whose 1st-percentile luma exceeds this counts as lifted")
    # LIFTED BLACKS ARE GATED ON A FRACTION, NOT ON THE WORST FRAME.
    #
    # This was `black.max() > 24.0`, and a single frame over the line failed the
    # whole piece. MEASURED on the two runs that stopped the pipeline in
    # 2026-08 (p1 luma recomputed from the surviving MP4s):
    #
    #   Jul 30, passed     0 of 2345 frames over 24  (0.00%)
    #   Jul 31, failed   172 of 1883 frames over 24  (9.13%), longest run 126
    #                    frames = 4.2 s. Looked at: a flat blue gradient with a
    #                    data card and a caption and NO subject geometry. An
    #                    empty render. It deserved to fail.
    #   Aug  1, failed     7 of 2205 frames over 24  (0.32%), longest run 4
    #                    frames = 0.13 s, in three bursts around f1750. Looked
    #                    at: translucent vortex geometry stacking up into one
    #                    washed-out flash. A real defect, but 0.23 s of one, and
    #                    a 73-second piece was discarded for it.
    #
    # 1% separates 0.32% from 9.13% with an order of magnitude of margin either
    # side. The alternative to publishing the Aug 1 piece was an empty slot.
    #
    # This mirrors --max-dark-frac below, which already gates a look defect on
    # the fraction of frames affected rather than on the single worst one.
    ap.add_argument("--max-black-frac", type=float, default=0.01,
                    help="max allowed fraction of lifted frames (0 = gate on the worst frame)")
    # Insurance against the fraction rule swallowing a catastrophe: a frame this
    # washed out is a broken render however brief it is. 96 is ~38% grey, far
    # above the 44-48 the real failures produced, so it only trips on a frame
    # with essentially no dark pixels anywhere.
    ap.add_argument("--max-black-hard", type=float, default=96.0,
                    help="any single frame above this fails regardless of --max-black-frac")
    ap.add_argument("--max-clipped", type=float, default=0.16,
                    help="max allowed fraction of a frame at >=254")
    # BRIGHTNESS FLOOR. Everything else here catches a render that is BROKEN;
    # this catches one that is EMPTY, which until now no gate could see.
    #
    # MEASURED, from the piece that made this necessary: a crepuscular-rays
    # piece rendered at whole-piece mean luma 7.9/255, per-beat 5.0 to 12.7 —
    # a black screen with captions on it, no subject geometry at all — and
    # check.py printed "all gates passed". It published.
    #
    # Reference points on the same scale: the ice piece that everyone agreed
    # looked good ran mean 77.4 with per-beat 49-121, and the pistol shrimp,
    # which was mediocre but not empty, ran mean 38.3. So 18 sits well below
    # anything acceptable and well above the failure. Per-beat 10 catches the
    # narrower case of one dead beat inside an otherwise lit piece — usually
    # the last one, after the captions have exited.
    ap.add_argument("--min-mean-luma", type=float, default=18.0,
                    help="min allowed whole-piece mean luma (0 disables)")
    ap.add_argument("--min-beat-luma", type=float, default=10.0,
                    help="min allowed per-beat mean luma (0 disables)")
    # DEAD STRETCHES. A mean and a per-beat mean both AVERAGE, and averaging is
    # exactly what hides "six seconds of nothing in the middle". MEASURED on an
    # authored piece whose numbers all passed (whole-piece mean 22.7, worst beat
    # 17.9): the vision pass looked at the same frames and reported "frames 4,
    # 5, 9, 10, 11, 12 and 13 show nothing but a dark blue gradient" — 7 of 24.
    # Counting dark FRAMES rather than averaging them separates cleanly:
    #   ice (good)   0.0% of frames below luma 12
    #   rays (bad)  92.3%
    #   that piece  ~29%
    ap.add_argument("--dark-luma", type=float, default=12.0,
                    help="a frame below this mean luma counts as dark")
    ap.add_argument("--max-dark-frac", type=float, default=0.25,
                    help="max allowed fraction of dark frames (0 disables)")
    ap.add_argument("--safe", default="60,900,200,1560", help="x0,x1,y0,y1 of the safe box")
    ap.add_argument("--jobs", type=int, default=0, help="worker processes (0 = cpu count)")
    ap.add_argument("--fps", type=int, default=24,
                    help="only used to report duration; 30 for Iris-flow segments")
    args = ap.parse_args()

    # Validate the hand-typed range specs before decoding anything -- a typo
    # should cost a second, not a full pass over the sequence.
    exempt = parse_ranges(args.exempt)
    beats = parse_beats(args.beats)

    names = sorted(f for f in os.listdir(args.frames) if f.lower().endswith(".png"))
    # A partial render leaves stale frames behind, and cloud-sync conflict copies
    # like "f0719 2.png" sort in next to the real thing and corrupt the results.
    strays = [f for f in names if " " in f]
    if strays:
        print(f"WARNING: {len(strays)} stray/duplicate files ignored, e.g. {strays[:3]}")
        print("         Cloud-synced folders (iCloud/Dropbox) generate these during a render.")
        names = [f for f in names if " " not in f]
    if not names:
        sys.exit(f"no frames in {args.frames}")

    # Frame numbers come from the FILENAME, not list position: a strided render
    # leaves f0000, f0008, f0016... on disk, and positional indexing would then
    # report every failure against the wrong frame.
    numbered = []
    for n in names:
        m = re.search(r"(\d+)", n)
        if m:
            numbered.append((int(m.group(1)), n))
    numbered.sort()
    total = len(numbered)
    picked = numbered[::max(1, args.stride)]
    idx = [f for f, _ in picked]
    paths = [os.path.join(args.frames, n) for _, n in picked]
    span = (numbered[-1][0] - numbered[0][0] + 1) if total else 0

    safe = tuple(int(v) for v in args.safe.split(","))
    probe = np.asarray(Image.open(paths[0]))
    H_PX, W_PX = probe.shape[:2]

    jobs = args.jobs or (os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=jobs, initializer=_init,
                             initargs=(safe, args.lit_threshold)) as ex:
        res = list(ex.map(_measure, paths, chunksize=8))

    lit = np.array([r[0] for r in res])
    means = np.array([r[1] for r in res])
    black = np.array([r[2] for r in res])
    clipped = np.array([r[3] for r in res])
    outside = np.array([r[4] for r in res])
    peak = np.array([r[5] for r in res])

    keep = np.array([j for j, i in enumerate(idx) if i not in exempt])
    if not len(keep):
        sys.exit("every sampled frame is exempt -- nothing to gate")

    fails = []
    # DEAD means nothing was drawn at all -- a peak near black. Judging this by
    # lit fraction produced false positives on every dark scene.
    dead = [idx[j] for j, v in enumerate(peak) if v < 16]
    if dead:
        fails.append(f"dead frames (peak < 16/255, nothing drawn): {dead[:12]}")
    if 0 in idx and peak[idx.index(0)] < 24:
        fails.append(f"first frame is blank (peak {peak[idx.index(0)]:.0f}/255) "
                     f"-- it is the thumbnail")
    lifted = black[keep] > args.max_black
    if args.max_black_frac:
        # Perceptibility is about how LONG the blacks stay lifted, so report the
        # longest contiguous run alongside the fraction: 4 frames is a flash,
        # 126 frames is four seconds of washed-out picture.
        worst = idx[int(keep[black[keep].argmax()])]
        runs, start = [], None
        for j, v in enumerate(lifted):
            if v and start is None:
                start = j
            elif not v and start is not None:
                runs.append(j - start)
                start = None
        if start is not None:
            runs.append(len(lifted) - start)
        longest = max(runs) if runs else 0
        if float(lifted.mean()) > args.max_black_frac:
            fails.append(
                f"blacks lifted: {lifted.sum()} of {len(lifted)} frames over p1 luma "
                f"{args.max_black:.0f} ({lifted.mean()*100:.2f}%, limit "
                f"{args.max_black_frac*100:.2f}%), longest run {longest} frames, "
                f"worst {black[keep].max():.1f} at f{worst} -- bloom threshold likely "
                f"too low, or the scene has no subject and you are gating background")
        if black[keep].max() > args.max_black_hard:
            fails.append(
                f"blacks blown: p1 luma {black[keep].max():.1f} at f{worst} "
                f"(hard limit {args.max_black_hard:.0f}) -- no dark pixels anywhere "
                f"in that frame; a single frame this washed out is a broken render")
    elif black[keep].max() > args.max_black:
        worst = idx[int(keep[black[keep].argmax()])]
        fails.append(f"blacks lifted: p1 luma {black[keep].max():.1f} at f{worst} "
                     f"(limit {args.max_black}) -- bloom threshold likely too low")
    if clipped[keep].max() > args.max_clipped:
        worst = idx[int(keep[clipped[keep].argmax()])]
        fails.append(f"blown highlights: {clipped[keep].max()*100:.1f}% of f{worst} at >=254 "
                     f"(limit {args.max_clipped*100:.0f}%)")
    if args.min_mean_luma and means[keep].mean() < args.min_mean_luma:
        fails.append(
            f"scene is unlit: whole-piece mean luma {means[keep].mean():.1f} "
            f"(floor {args.min_mean_luma:.0f}) -- this is a dark frame with "
            f"captions on it, not a scene. Light the subject, or build one.")
    if args.max_dark_frac:
        dark_mask = means[keep] < args.dark_luma
        dark_frac = float(dark_mask.mean())
        if dark_frac > args.max_dark_frac:
            worst = [int(idx[int(keep[j])]) for j in np.flatnonzero(dark_mask)][:12]
            fails.append(
                f"dead stretches: {dark_frac*100:.0f}% of frames are below luma "
                f"{args.dark_luma:.0f} (limit {args.max_dark_frac*100:.0f}%) -- "
                f"e.g. f{worst}. The averages can look fine while whole seconds "
                f"of the middle show nothing.")

    scope = f"{len(idx)} of {total}" if args.stride > 1 else f"{total}"
    if span != total:
        scope += f" (covering f0-f{span-1})"
    print(f"frames            {scope}   {span/args.fps:.1f}s at {args.fps}fps"
          + (f"   [stride {args.stride}]" if args.stride > 1 else ""))
    print(f"lit fraction      min {lit.min():.4f}  mean {lit.mean():.4f}")
    print(f"peak channel      min {peak.min():.0f}  mean {peak.mean():.0f}   "
          f"(dead = peak < 16)")
    print(f"frame mean luma   min {means.min():.1f}  mean {means.mean():.1f}  max {means.max():.1f}")
    print(f"black level (p1)  median {np.median(black[keep]):.1f}  "
          f"p98 {np.percentile(black[keep],98):.1f}  max {black[keep].max():.1f}   "
          f"(target: low single digits)")
    print(f"                  {int((black[keep] > args.max_black).sum())} of "
          f"{len(keep)} frames over {args.max_black:.0f} "
          f"({(black[keep] > args.max_black).mean()*100:.2f}%, "
          f"limit {args.max_black_frac*100:.2f}%)")
    print(f"clipped px        max {clipped[keep].max()*100:.2f}% of a frame")
    print(f"lit px outside    max {outside.max()} ({outside.max()/(W_PX*H_PX)*100:.1f}% of frame)   "
          f"box x{safe[0]}-{safe[1]} y{safe[2]}-{safe[3]}")
    print("                  reported, not gated -- and only meaningful on a dark-background")
    print("                  piece. On a bright scene this is mostly background, not content.")

    if beats:
        print("\nper-beat:")
        pos = {f: j for j, f in enumerate(idx)}
        dim = []
        for name, a, b in beats:
            sel = [pos[f] for f in idx if a <= f <= b]
            if not sel:
                continue
            beat_luma = means[sel].mean()
            print(f"  {name:12s} f{a:4d}-{b:<4d}  luma {beat_luma:5.1f}   "
                  f"lit {lit[sel].mean()*100:5.2f}%")
            if args.min_beat_luma and beat_luma < args.min_beat_luma:
                dim.append(f"{name} (f{a}-{b}, luma {beat_luma:.1f})")
        # Appended AFTER the per-beat table is printed, so the report shows the
        # numbers that produced the verdict. The `if fails:` block below has not
        # run yet -- ordering here is load-bearing.
        if dim:
            fails.append(
                f"dead beat(s) below luma {args.min_beat_luma:.0f}: "
                f"{', '.join(dim)} -- the beat drives nothing on screen. "
                f"The LAST beat is the usual offender: the narration ends, the "
                f"captions exit, and the shot is left empty.")

    if fails:
        print()
        for f in fails:
            print("FAIL: " + f)
        print("\nSee references/debugging.md for symptom -> cause.")
        return 1

    if args.stride > 1:
        print(f"\nall gates passed on a stride-{args.stride} sample "
              f"-- run without --stride before shipping")
    else:
        print("\nall gates passed")
    print("Gates check for broken renders only -- look at a contact sheet for quality.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
