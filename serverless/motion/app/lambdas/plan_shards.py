"""
PlanShards Lambda — cut a render into contiguous frame ranges, one per shard.

Everything downstream trusts this split blindly. The Map fans out one Batch
render job per entry, and stitch encodes with `-i frames/f%04d.png`, which is a
DENSE sequence: ffmpeg stops at the first missing number and silently produces a
short video instead of an error. So:

  - a GAP truncates the film at the hole, and nothing upstream notices;
  - an OVERLAP has two Spot tasks writing the same PNG at the same time, and one
    of them can lose the race with a half-written object.

Hence the split is computed once from cumulative counts, and the coverage
invariant is asserted before the result is returned rather than trusted.

Input  (the Step Functions state):  {"video_id": "...", ...}
Output:
    {"shards": [{"video_id": "..", "shard": 0, "frame_from": 0, "frame_to": 179},
                ...],
     "shard_count": 8, "frames": 1440, "fps": 30}

Run the file directly to execute the coverage self-test:

    python3 plan_shards.py
"""

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MOTION_BUCKET = os.environ.get('MOTION_BUCKET', '')

# plan.json is written by prep and always carries `shards`; the default only
# covers a hand-written plan.json used for a one-off re-render.
DEFAULT_SHARDS = 8

# The Map runs 8 at a time and the compute environment caps at 64 vCPU, so more
# than 64 shards buys nothing and just multiplies Batch SubmitJob calls and
# per-task container-pull overhead (~20 s each) across a longer queue.
MAX_SHARDS = 64

# region_name explicitly: Lambda always sets AWS_REGION, but the __main__
# self-test below has to import this module on a laptop where it may not be set,
# and boto3 raises NoRegionError at client construction, not at first call.
s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))


def split_frames(frames, shards):
    """
    Split [0, frames-1] into `shards` contiguous, inclusive ranges.

    Pure and total — no S3, no env, no logging — so the self-test below can
    hammer it. Returns a list of (frame_from, frame_to) tuples.

    The remainder is spread one frame at a time over the LEADING shards rather
    than dumped on the last one: with frames=1441, shards=8 that gives
    181,180,180,180,180,180,180,180 instead of 180x7 + 181, so no single shard
    is ever more than one frame longer than any other and the Map's 8 branches
    finish together. Starts are accumulated, never recomputed as i*base, which
    is what keeps the ranges butted up against each other with no drift.
    """
    frames = int(frames)
    shards = int(shards)
    if frames < 1:
        raise ValueError(f'frames must be >= 1, got {frames}')
    if shards < 1:
        raise ValueError(f'shards must be >= 1, got {shards}')

    # Clamping to `frames` is what makes short renders safe: 1 frame over 8
    # shards would otherwise produce seven empty ranges, and an empty range
    # becomes a Batch job that renders nothing and a range whose frame_to is
    # frame_from-1.
    n = min(shards, frames, MAX_SHARDS)
    if n != shards:
        logger.warning('shard count clamped from %d to %d (frames=%d, max=%d)',
                       shards, n, frames, MAX_SHARDS)

    base, remainder = divmod(frames, n)
    ranges = []
    start = 0
    for i in range(n):
        count = base + (1 if i < remainder else 0)
        ranges.append((start, start + count - 1))
        start += count

    # Cheap, and it fires in the Lambda log before a wrong plan can reach Batch.
    if start != frames:
        raise AssertionError(
            f'coverage error: {start} frames allocated for frames={frames}, shards={n}')
    return ranges


def _load_plan(video_id):
    key = f'jobs/{video_id}/plan.json'
    body = s3.get_object(Bucket=MOTION_BUCKET, Key=key)['Body'].read()
    return json.loads(body)


def handler(event, context):
    video_id = event['video_id']
    plan = _load_plan(video_id)

    frames = int(plan['frames'])
    shards = int(plan.get('shards', DEFAULT_SHARDS))
    ranges = split_frames(frames, shards)

    out = [
        {'video_id': video_id, 'shard': i, 'frame_from': lo, 'frame_to': hi}
        for i, (lo, hi) in enumerate(ranges)
    ]

    logger.info('video_id=%s frames=%d -> %d shards: %s',
                video_id, frames, len(out),
                ', '.join(f'{lo}-{hi}' for lo, hi in ranges))

    return {
        'shards': out,
        'shard_count': len(out),
        'frames': frames,
        'fps': int(plan.get('fps', 30)),
    }


def _self_test():
    """
    Assert full coverage with no overlap. Rebuilding the covered frame list and
    comparing it to range(frames) checks ordering, contiguity, gaps and overlaps
    in one equality — a set comparison would pass on a duplicated frame.
    """
    import random

    # Most random cases below deliberately over-shard, and the clamp warning
    # would drown the actual result.
    logger.setLevel(logging.ERROR)

    cases = [
        (1440, 8),      # the nominal render: 8 x 180
        (1441, 8),      # +1 frame: the remainder must land somewhere
        (1439, 8),      # -1 frame: 179 shows up, nothing is dropped
        (1, 1),
        (1, 8),         # more shards than frames
        (2, 3),
        (3, 2),         # 2,1
        (7, 3),         # 3,2,2
        (8, 8),         # exactly one frame each
        (9, 8),         # one shard gets two
        (100, 7),       # 15,15,14,14,14,14,14
        (1440, 1),      # single-shard re-render
        (5, 5),
        (17, 5),
        (31, 7),
        (64, 64),
        (65, 64),
        (999, 64),
        (1000, 999),    # clamped to MAX_SHARDS
        (1800, 16),
        (2700, 12),     # 90 s at 30 fps
    ]
    cases += [(random.randint(1, 5000), random.randint(1, 200)) for _ in range(600)]

    for frames, shards in cases:
        ranges = split_frames(frames, shards)
        expected_n = min(shards, frames, MAX_SHARDS)
        assert len(ranges) == expected_n, \
            f'{frames}/{shards}: got {len(ranges)} shards, expected {expected_n}'

        covered = []
        for lo, hi in ranges:
            assert lo <= hi, f'{frames}/{shards}: empty/inverted range {lo}-{hi}'
            covered.extend(range(lo, hi + 1))
        assert covered == list(range(frames)), \
            f'{frames}/{shards}: coverage is not exactly 0..{frames - 1}'

        sizes = [hi - lo + 1 for lo, hi in ranges]
        assert max(sizes) - min(sizes) <= 1, \
            f'{frames}/{shards}: unbalanced shard sizes {sizes}'

    for bad in [(0, 8), (-1, 8), (1440, 0), (1440, -3)]:
        try:
            split_frames(*bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f'split_frames{bad} should have raised ValueError')

    print(f'plan_shards self-test: {len(cases)} cases, '
          f'full coverage and no overlap in every one')


if __name__ == '__main__':
    _self_test()
