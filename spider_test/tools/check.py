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
        # Black level as a low percentile of luma, NOT a corner patch: in a 3D
        # scene the corners hold real lit geometry, so a corner probe measures
        # content and fails honest frames.
        float(np.percentile(luma, 1)),
        float((g >= 254).mean()),
        int((mask & ~box).sum()),
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
        name, rng = part.split(":")
        a, b = rng.split("-")
        beats.append((name, int(a), int(b)))
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
                    help="max allowed 1st-percentile luma outside exempt frames")
    ap.add_argument("--max-clipped", type=float, default=0.16,
                    help="max allowed fraction of a frame at >=254")
    ap.add_argument("--safe", default="60,900,200,1560", help="x0,x1,y0,y1 of the safe box")
    ap.add_argument("--jobs", type=int, default=0, help="worker processes (0 = cpu count)")
    args = ap.parse_args()

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

    exempt = parse_ranges(args.exempt)
    keep = np.array([j for j, i in enumerate(idx) if i not in exempt])
    if not len(keep):
        sys.exit("every sampled frame is exempt -- nothing to gate")

    fails = []
    dead = [idx[j] for j, v in enumerate(lit) if v < 0.002]
    if dead:
        fails.append(f"dead frames (nothing lit): {dead[:12]}")
    if 0 in idx and lit[idx.index(0)] < 0.004:
        fails.append(f"first frame nearly empty ({lit[0]:.4f}) -- it is the thumbnail")
    if black[keep].max() > args.max_black:
        worst = idx[int(keep[black[keep].argmax()])]
        fails.append(f"blacks lifted: p1 luma {black[keep].max():.1f} at f{worst} "
                     f"(limit {args.max_black}) -- bloom threshold likely too low")
    if clipped[keep].max() > args.max_clipped:
        worst = idx[int(keep[clipped[keep].argmax()])]
        fails.append(f"blown highlights: {clipped[keep].max()*100:.1f}% of f{worst} at >=254 "
                     f"(limit {args.max_clipped*100:.0f}%)")

    scope = f"{len(idx)} of {total}" if args.stride > 1 else f"{total}"
    if span != total:
        scope += f" (covering f0-f{span-1})"
    print(f"frames            {scope}   {span/24:.1f}s at 24fps"
          + (f"   [stride {args.stride}]" if args.stride > 1 else ""))
    print(f"lit fraction      min {lit.min():.4f}  mean {lit.mean():.4f}")
    print(f"frame mean luma   min {means.min():.1f}  mean {means.mean():.1f}  max {means.max():.1f}")
    print(f"black level (p1)  median {np.median(black[keep]):.1f}  "
          f"p98 {np.percentile(black[keep],98):.1f}  max {black[keep].max():.1f}   "
          f"(target: low single digits)")
    print(f"clipped px        max {clipped[keep].max()*100:.2f}% of a frame")
    print(f"lit px outside    max {outside.max()} ({outside.max()/(W_PX*H_PX)*100:.1f}% of frame)   "
          f"box x{safe[0]}-{safe[1]} y{safe[2]}-{safe[3]}")
    print("                  reported, not gated -- and only meaningful on a dark-background")
    print("                  piece. On a bright scene this is mostly background, not content.")

    beats = parse_beats(args.beats)
    if beats:
        print("\nper-beat:")
        pos = {f: j for j, f in enumerate(idx)}
        for name, a, b in beats:
            sel = [pos[f] for f in idx if a <= f <= b]
            if not sel:
                continue
            print(f"  {name:12s} f{a:4d}-{b:<4d}  luma {means[sel].mean():5.1f}   "
                  f"lit {lit[sel].mean()*100:5.2f}%")

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
