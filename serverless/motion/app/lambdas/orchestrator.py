"""
Orchestrator Lambda — starts ONE iris-motion Step Functions execution.

Triggered by EventBridge. A close copy of the STEM orchestrator
(serverless/src/lambdas/orchestrator.py), because that shape is proven; every
difference below is deliberate.

  - The topic comes off the SHARED queue `iris-flow-topic-queue`, not a new
    motion-only one. Both pipelines drawing from the one curated queue is the
    point: `iris-flow-topic-queue-low` is the alarm that says "go refill topics"
    (scripts/populate_motion_phenomena.py for THIS pipeline —
    populate_mega_topics.py fills the same queue with chart/manim topics for the
    STEM renderer, which produce poor Three.js scenes), and a second queue would
    leave that alarm watching a pipeline that no longer runs.

    TWO THINGS THAT SHARING COSTS, both learned the hard way in 2026-08:
    a topic is DELETED as soon as it is read (see below), so a run that fails
    burns it; and SQS caps message retention at 14 days, so the queue cannot be
    used as a long-term backlog. On 2026-08-10 a batch of ~99 queued on 07-27
    hit that ceiling and ~53 topics expired unread in a single day — only 1 was
    consumed. Refill in batches of ~40 (3/day x 14 days), or hold the backlog
    somewhere durable and top the queue up from it.

  - The queue body is a JSON envelope, but motion's app/prep.py reads TOPIC as
    prose and drops it straight into the authoring prompt — it does NOT
    json.loads it the way src/worker.py's job_prep does. So the prompt is
    unwrapped here. Passing the envelope through would put a JSON blob in the
    model prompt and in plan.json's `topic`, which is also what the notify email
    prints.

  - force_seed AND seed_fallback are both pinned false. A scheduled motion run
    is Claude-authored or it is nothing: the seed is one fixed aurora piece, so
    falling back to it would post the same video again under whatever topic came
    off the queue. A skipped slot is cheaper than that. app/prep.py raises when
    SEED_FALLBACK is off, the state machine's global catch emails the failure,
    and the next slot runs normally. Manual runs simply leave seed_fallback
    unset — it defaults to true in prep — which is how the infrastructure is
    smoke-tested without spending on a model call.
"""

import json
import logging
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs = boto3.client('sqs')
sfn = boto3.client('stepfunctions')

# QUEUE_URL / TOPIC_QUEUE_URL are both accepted for the same reason the STEM
# orchestrator accepts both: it lets one Lambda serve more than one schedule
# without a code change.
DRY_RUN = os.environ.get('MOTION_DRY_RUN', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
TOPIC_QUEUE_URL = os.environ.get('QUEUE_URL') or os.environ['TOPIC_QUEUE_URL']
STATE_MACHINE_ARN = os.environ['STATE_MACHINE_ARN']
# 75 s, up from 60. Still inside the retention window (measured watch-through
# falls sharply past ~90 s) and it buys the room the pieces actually need: at
# 3.2 spoken words/second that is about 105 words and 8-10 beats, against the
# 6 beats a 60 s target was producing.
#
# NOTE THE GAP THIS HAS TO CLOSE. The target is advisory — real duration comes
# from the MEASURED narration audio, so the piece is as long as the script is.
# Against a 60 s target recent pieces came in at 41-46 s, because the model wrote
# six segments and stopped. The authoring prompt now states the segment count and
# the word budget explicitly rather than leaving the target to imply them.
TARGET_DURATION = int(os.environ.get('TARGET_DURATION', '75'))
EXEC_PREFIX = os.environ.get('EXEC_PREFIX', 'iris-motion')

# Random scheduling window: post anywhere from MIN_DELAY_MIN to MAX_DELAY_MIN
# minutes from now. schedule_time is computed HERE, at trigger time, before any
# of the pipeline has run, so MIN_DELAY_MIN must stay safely above the pipeline's
# wall-clock runtime or Metricool is handed a slot that arrives before video.mp4
# exists. Motion is ~12 min of work (prep ~5, GPU render ~5, stitch ~2) plus up
# to ~4 min of g4dn boot and image pull, since the GPU compute environment sits
# at minvCpus 0 between runs. 30 min still leaves ~14 min of margin.
MIN_DELAY_MIN = 30
MAX_DELAY_MIN = 90        # 1.5 h — keeps posts fresh while still adding jitter

# Mirror of _SAFE_ID in app/common.py, which validates VIDEO_ID at the top of
# every Batch job and raises if it does not match. Duplicated rather than
# imported because the Lambda asset (app/lambdas/) ships without app/common.py;
# asserting against it here turns a bad id into a clear failure in this log
# instead of an opaque one three states later.
_SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')


def _random_schedule_time() -> str:
    """Pick a random time between MIN_DELAY_MIN and MAX_DELAY_MIN from now, ISO-8601 UTC."""
    delay = random.randint(MIN_DELAY_MIN, MAX_DELAY_MIN)
    ts = datetime.now(timezone.utc) + timedelta(minutes=delay)
    return ts.isoformat()


def _new_video_id() -> str:
    """
    A unique, lexicographically sortable id that is also a safe S3 key segment
    and URL path segment.

    The UTC stamp leads so `aws s3 ls s3://iris-motion-<account>/jobs/` comes
    back in chronological order — that listing is the only index this pipeline
    has. The uuid tail separates two runs that start in the same second, which
    is a manual invoke racing a scheduled one rather than a theoretical concern.
    The alphabet is not free choice: app/common.py's video_id() rejects anything
    outside [A-Za-z0-9][A-Za-z0-9._-]{0,127}, and the id also becomes a URL path
    segment for the page render.mjs fetches.
    """
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    vid = f'{stamp}-{uuid.uuid4().hex[:8]}'
    if not _SAFE_ID.fullmatch(vid):
        raise RuntimeError(f'generated video_id {vid!r} is not a safe S3 key / URL segment')
    return vid


def _topic_text(body: str) -> str:
    """
    One queue message -> the prose app/prep.py wants in TOPIC.

    Messages are JSON envelopes ({"prompt": ..., "category": ...}) written by
    scripts/populate_mega_topics.py, but a hand-queued bare string is legitimate
    too and must survive untouched. Both `prompt` and `topic` are accepted as the
    text key because src/worker.py's job_prep accepts both and the queue has
    carried both.
    """
    body = (body or '').strip()
    if not body:
        return ''
    try:
        data = json.loads(body)
    except ValueError:
        return body                       # a plain-text topic, not an envelope
    if isinstance(data, dict):
        text = str(data.get('prompt') or data.get('topic') or '').strip()
        if text:
            return text
        # An envelope with no recognisable text key. The raw body at least
        # carries the information; an empty topic would silently hand the run to
        # prep's hardcoded default and nobody would know the message was wasted.
        logger.warning('Queue message has no prompt/topic key, passing it raw: %s',
                       body[:200])
        return body
    if isinstance(data, str):
        return data.strip()               # a JSON-encoded bare string
    return body


def handler(event, context):
    """
    1. Take one topic off the shared queue, if there is one.
    2. Mint a video_id and a random schedule_time 30-90 min out.
    3. Start one iris-motion-pipeline execution, authored-only.
    """
    topic = ''

    resp = sqs.receive_message(
        QueueUrl=TOPIC_QUEUE_URL,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=0,
    )
    messages = resp.get('Messages', [])
    if messages:
        msg = messages[0]
        topic = _topic_text(msg['Body'])
        # Deleted straight away, exactly as the STEM orchestrator does. The
        # execution outlives this Lambda by ~12 minutes, so there is nothing to
        # wait on. The cost is that a run which fails — authoring, Spot, a scene
        # that will not render — burns its topic. That is the accepted trade:
        # the alternative is letting the 30-minute visibility timeout redeliver
        # it into an arbitrary later slot, and the queue holds hundreds.
        sqs.delete_message(
            QueueUrl=TOPIC_QUEUE_URL,
            ReceiptHandle=msg['ReceiptHandle'],
        )
        logger.info('Using queued topic: %s', topic[:120])
    else:
        # SKIP THE SLOT. This used to fall through to prep's own default topic,
        # which on an empty queue means every scheduled slot authors, renders
        # and PUBLISHES a video about the same hardcoded subject — five
        # identical posts a day, for as long as the queue stays empty, to real
        # accounts. The queue is empty right now and its low-queue alarm is
        # already firing, so this is the live case, not a hypothetical.
        # A skipped slot is the same trade seed_fallback:false already makes:
        # publish nothing rather than publish filler.
        logger.warning('No queued topic in %s — skipping this slot. '
                       'Refill with scripts/populate_motion_phenomena.py '
                       '(NOT populate_mega_topics.py — that one is shaped for the '
                       'STEM chart renderer, not for Three.js scenes). Enqueue at '
                       'most ~40: SQS retention is capped at 14 days and this '
                       'pipeline consumes 3/day, so a larger batch expires '
                       'unconsumed — which is what emptied the queue on '
                       '2026-08-10.',
                       TOPIC_QUEUE_URL)
        return {'started': False, 'reason': 'topic-queue-empty'}

    video_id = _new_video_id()
    schedule_time = _random_schedule_time()

    # EventBridge passes {"include_youtube": bool, "include_tiktok": bool} as a
    # constant input; the rules use them to cap YouTube and TikTok per day. Both
    # default to True for manual invokes and for any raw scheduled event that
    # does not set them, so a hand-run execution posts everywhere.
    include_youtube = event.get('include_youtube', True) if isinstance(event, dict) else True
    include_tiktok = event.get('include_tiktok', True) if isinstance(event, dict) else True

    # COMPANION FORMATS. Same mechanism, opposite default: these come off the
    # rule and default to FALSE, so a hand-invoke posts the reel only and never
    # surprises the accounts with three extra posts. Exactly one scheduled rule
    # sets each of carousel/image and two set story — that IS the per-format
    # daily cap, expressed where it can be read (see IrisMotionStack) rather
    # than in a counter that has to be reset at midnight.
    ev = event if isinstance(event, dict) else {}
    post_carousel = ev.get('post_carousel', False)
    post_story = ev.get('post_story', False)
    post_image = ev.get('post_image', False)

    execution_input = {
        'video_id': video_id,
        'topic': topic,                      # '' → prep picks its own
        'target_duration': TARGET_DURATION,
        'schedule_time': schedule_time,      # ISO-8601 UTC, passed to postprocess
        'include_youtube': include_youtube,  # gates the YouTube network in postprocess
        'include_tiktok': include_tiktok,    # gates the TikTok network in postprocess
        # Companion formats, resolved the same way and for the same reason as
        # force_seed below: written explicitly on EVERY execution because the
        # state machine reads them with States.Format('{}', $.post_carousel),
        # and a JsonPath to a missing field fails the STATE, not just the field.
        'post_carousel': post_carousel,
        'post_story': post_story,
        'post_image': post_image,
        # Both false on every scheduled run — see the module docstring. They are
        # written explicitly rather than omitted because the state machine reads
        # them with States.Format('{}', $.force_seed), and a JsonPath to a
        # missing field fails the STATE, not just the field.
        'force_seed': False,
        'seed_fallback': False,
        # Read by PostprocessJob as DRY_RUN. Present on EVERY execution because the

        # state machine resolves it with a JsonPath, and a JsonPath to a missing

        # field fails the state rather than defaulting. DRY_RUN is honoured by

        # app/postprocess.py, so flipping this to True rehearses the whole

        # pipeline including the S3 publish, without booking a post.

        'dry_run': DRY_RUN,
    }

    # Step Functions execution names are capped at 80 characters and must be
    # unique for 90 days; '<prefix>-<stamp>-<hex8>' is 37 and unique by
    # construction, so no truncation and no collision retry is needed.
    started = sfn.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=f'{EXEC_PREFIX}-{video_id}',
        input=json.dumps(execution_input),
    )
    execution_arn = started['executionArn']

    logger.info(
        'Started %s video_id=%s schedule_time=%s include_youtube=%s '
        'include_tiktok=%s carousel=%s story=%s image=%s target_duration=%s '
        'authored_only=true',
        execution_arn, video_id, schedule_time, include_youtube,
        include_tiktok, post_carousel, post_story, post_image, TARGET_DURATION,
    )
    return {
        'execution_arn': execution_arn,
        'video_id': video_id,
        'topic': topic,
        'schedule_time': schedule_time,
        'include_youtube': include_youtube,
        'include_tiktok': include_tiktok,
        'post_carousel': post_carousel,
        'post_story': post_story,
        'post_image': post_image,
        'started': True,
    }
