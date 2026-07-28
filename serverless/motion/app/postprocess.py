"""
JOB_TYPE=postprocess -- ship the finished video: public copy, caption, Metricool.

Runs after stitch and is the only job in this pipeline that publishes anything.
Three steps, in this order because each depends on the one before:

  1. out/video.mp4 is copied from the private motion bucket into the public
     iris-flow-videos-<account>. Metricool fetches the media itself, over plain
     HTTPS with no credentials, and the motion bucket blocks all public access --
     so a video that never leaves it can never be posted. The copy is
     SERVER-SIDE: download + re-upload of a ~40 MB file through a 2 vCPU task is
     wall clock and egress spent on a byte-identical result S3 will produce for
     free.
  2. ONE Opus 5 call turns the topic and the narration into
     {title, caption, tiktok_title}.
  3. The post is scheduled, unconditionally.

UNCONDITIONALLY is the word that matters. The check.py gates are read here and
recorded into plan.json so they reach the notify email, and they do NOT gate:
stitch already encodes a gate-failing render on purpose ("a gate result is
information"), and this job takes the same line all the way through to publish.

env:  VIDEO_ID, MOTION_BUCKET            (as every other job)
      PUBLIC_BUCKET_NAME                 optional, defaults to the deployed bucket
      SCHEDULE_TIME                      ISO-8601 UTC; absent => no post
      INCLUDE_YOUTUBE, INCLUDE_TIKTOK    per-network caps, default true
      DRY_RUN                            'true' => log the payload, post nothing
      ANTHROPIC_API_KEY
      METRICOOL_API_KEY / METRICOOL_USER_ID / METRICOOL_BLOG_ID
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import common
from common import logger

# The public bucket IrisFlowStack owns (`iris-flow-videos-${account}`, with
# publicReadAccess). Defaulted rather than required so a manual run needs no
# extra env in the one account this pipeline is deployed to; the env var is there
# for the stack to be explicit and for a test bucket.
PUBLIC_BUCKET = (os.environ.get('PUBLIC_BUCKET_NAME')
                 or os.environ.get('PUBLIC_BUCKET')
                 or 'iris-flow-videos-482625028438')
# Its own prefix inside a bucket the STEM pipeline also writes to
# (`videos/<Y>/<m>/<d>/<id>.mp4`). Nothing collides and either pipeline's objects
# can be listed on their own.
PUBLIC_PREFIX = 'motion/'

CLAUDE_MODEL = 'claude-opus-5'
# Opus 5 list price, same table as prep.py. No caching here: the prompt is ~700
# tokens and changes every run, so there is nothing worth a cache write.
PRICE = {'in': 5.0 / 1e6, 'out': 25.0 / 1e6}
# A title + caption + tiktok_title is ~250 tokens of JSON. This budget is only
# credible because thinking is off below -- see _caption_claude.
CAPTION_MAX_TOKENS = 2000

# Same caps the STEM pipeline applies. schedule_post will itself cut a YouTube
# title over 100 to 97 + "...", so cutting at 97 here means the title that gets
# logged is the title that posts, rather than a longer one silently ellipsised
# two layers down.
YOUTUBE_TITLE_MAX = 97
TIKTOK_TITLE_MAX = 80

CAPTION_PROMPT = """You are writing the title and caption for a TikTok / Instagram Reel / YouTube Short.

TOPIC:
{topic}

NARRATION (the complete spoken script of the video, verbatim):
{narration}

The narration is the source of truth for what this video actually says. Do not
promise the viewer anything it does not deliver, and do not describe visuals you
cannot see.

Write the way a smart human creator writes, not the way an AI writes.

HARD RULES (violating any one of these makes the post unusable):
- NO em dashes ( — ) anywhere. Use commas or periods.
- NO en dashes ( – ). Use a regular hyphen ( - ) only when joining words like "well-known".
- NO "dive into", "fascinating", "let's explore", "uncover", "unpack", "delve", "journey", "buckle up", "mind-blowing", "wild".
- NO "did you know" / "ever wondered" openers.
- NO meta references to the video itself ("in this video", "today we look at").
- NO mention of "Iris Flow", "AI", or any tool/brand name.
- NO ellipses.
- NO emojis anywhere in the title or caption text. Hashtags only.

TITLE (used as the YouTube title):
- Under 80 characters.
- Concrete, specific noun phrase. Name the phenomenon, person, or number.
- No clickbait fluff like "you wont believe" or "shocking".
- Examples of the right tone: "Why bees make hexagons", "Bayes rule, decoded in 60 seconds", "Lorenz attractor: order from a butterfly".

TIKTOK_TITLE (used only on TikTok, where a flat noun phrase dies in the feed):
- Under 80 characters.
- State the counterintuitive claim directly, as a challenge or a tension. A question is
  allowed here. One emoji is allowed here (at the end, never mid-sentence), no more.
- Still banned: "you won't believe", "shocking", "mind-blowing", "what if I told you",
  and everything in the hard rules above.
- Examples of the right tone: "Building more roads makes traffic worse", "A magnet falls
  slower through copper. No magic", "Your intuition about this coin flip is wrong".

CAPTION:
- 1-2 short sentences, under 220 chars total before hashtags.
- Open with a concrete claim or surprising fact drawn from the narration. Mention a number, a name, or a specific phenomenon. Be SPECIFIC.
- The second sentence (if any) is the "but here's the twist" line, the part that makes a viewer want to watch.
- Tone: a sharp graduate student texting a friend who is curious about science. Confident, no filler.
- Then a blank line, then 4-6 hashtags. Hashtags should be specific to the topic (not just generic #science #stem). Include a couple broad ones at the end.

OUTPUT FORMAT (must parse as JSON, no markdown fences, no commentary):
{{"title": "...", "tiktok_title": "...", "caption": "...\\n\\n#tag1 #tag2 #tag3 #tag4"}}"""

_TRUTHY = ('1', 'true', 'yes', 'on')


# ============================================================
# env
# ============================================================
def _flag(name: str, default: str = 'true') -> bool:
    """INCLUDE_YOUTUBE / INCLUDE_TIKTOK, parsed exactly as src/worker.py does."""
    return os.environ.get(name, default).strip().lower() in _TRUTHY


def _motion_bucket() -> str:
    """
    The private bucket, by name.

    common resolves it into a module constant at import; re-check it here so an
    unset env fails with that sentence instead of as `Bucket=None` inside
    copy_object.
    """
    if not common.BUCKET:
        raise RuntimeError('MOTION_BUCKET / MOTION_BUCKET_NAME not set')
    return common.BUCKET


# ============================================================
# gates -- recorded, never enforced
# ============================================================
def _gates_text(vid: str, wd):
    """check.py's output, or None if stitch never got as far as uploading it."""
    path = common.download_file(vid, 'out/gates.txt', wd / 'gates.txt', optional=True)
    return path.read_text() if path else None


def _gates_passed(plan: dict, text):
    """
    The gate verdict, or None if there isn't one. Recorded, never enforced.

    stitch writes it into plan["output"]["gates_passed"] and uploads the file;
    the text scan is the fallback for a run that died between the two, and is
    the same rule the notify Lambda applies.
    """
    passed = (plan.get('output') or {}).get('gates_passed')
    if passed is None and text:
        passed = not ('FAIL:' in text or 'gates FAILED' in text)
    return passed


# ============================================================
# public copy
# ============================================================
def _publish(vid: str) -> tuple:
    """
    Server-side copy of out/video.mp4 into the public bucket. Returns (url, bytes).

    No ACL is set: IrisFlowStack gives that bucket a policy granting s3:GetObject
    on every key, so the object is readable the moment it lands, and a per-object
    ACL would simply fail if the bucket ever moves to BucketOwnerEnforced.
    """
    src_bucket = _motion_bucket()
    src_key = common.key(vid, 'out/video.mp4')
    dst_key = f'{PUBLIC_PREFIX}{vid}.mp4'

    # head first: a missing source here means stitch did not finish, and saying
    # so beats a bare NoSuchKey out of copy_object.
    try:
        head = common.s3.head_object(Bucket=src_bucket, Key=src_key)
    except Exception as e:  # noqa: BLE001 - re-raised immediately with context
        raise RuntimeError(
            f's3://{src_bucket}/{src_key} is not there ({type(e).__name__}) -- '
            f'stitch has not produced a video for {vid}') from e
    size = int(head.get('ContentLength', 0))
    if size <= 0:
        raise RuntimeError(f's3://{src_bucket}/{src_key} is zero bytes')

    # MetadataDirective=REPLACE so the Content-Type is asserted here rather than
    # inherited. A plain COPY carries whatever header the private object happens
    # to have, which makes what Metricool sees over HTTPS depend on how stitch
    # uploaded the file; this pins it at the one point that matters.
    common.s3.copy_object(
        Bucket=PUBLIC_BUCKET,
        Key=dst_key,
        CopySource={'Bucket': src_bucket, 'Key': src_key},
        MetadataDirective='REPLACE',
        ContentType='video/mp4',
    )

    # Same URL shape the STEM pipeline hands Metricool today (src/worker.py
    # job_concatenate). Path style over the bucket's regional endpoint would also
    # resolve, but this is the form already known to work with their fetcher.
    url = f'https://{PUBLIC_BUCKET}.s3.amazonaws.com/{dst_key}'
    logger.info(f'[{vid}] published {size / 1e6:.1f} MB -> {url}')
    return url, size


# ============================================================
# caption
# ============================================================
def _clean(text: str) -> str:
    """Belt-and-braces: strip the punctuation the prompt bans, in case it slips."""
    return (text.replace('—', ', ')
                .replace('–', ', ')
                .replace('...', '.')
                .replace('…', '.'))


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        i, j = text.find('{'), text.rfind('}')
        if i < 0 or j <= i:
            raise
        return json.loads(text[i:j + 1])


def _narration_text(plan: dict) -> str:
    segs = plan.get('narration') or []
    lines = [str(s.get('text', '')).strip()
             for s in segs if isinstance(s, dict) and s.get('text')]
    return '\n'.join(ln for ln in lines if ln)


def _caption_claude(topic: str, narration: str) -> tuple:
    """
    One Opus 5 call -> ({title, caption, tiktok_title}, usd).

    thinking is DISABLED, deliberately, against the SDK default. MEASURED on this
    account on prep.py's authoring call: with thinking adaptive -- which is what
    omitting the parameter gives on Opus 5 -- the model spent the ENTIRE 32,000
    token budget inside one thinking block and returned stop_reason=max_tokens
    with zero text. Twice. Billed, and downstream it looks like malformed JSON.
    Opus 5 rejects budget_tokens, so switching thinking off is the only cap
    available, and a caption needs none of it.

    That is also what makes CAPTION_MAX_TOKENS=2000 safe: with thinking off the
    whole budget is output, and the output is ~250 tokens of JSON.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CAPTION_MAX_TOKENS,
        thinking={'type': 'disabled'},
        messages=[{'role': 'user',
                   'content': CAPTION_PROMPT.format(topic=topic,
                                                    narration=narration)}],
    )

    raw = ''.join(b.text for b in msg.content
                  if getattr(b, 'type', None) == 'text').strip()
    usage = msg.usage.model_dump() if hasattr(msg.usage, 'model_dump') else dict(msg.usage)
    cost = (usage.get('input_tokens', 0) * PRICE['in']
            + usage.get('output_tokens', 0) * PRICE['out'])
    logger.info('caption: stop=%s out=%s text=%d chars $%.4f',
                msg.stop_reason, usage.get('output_tokens'), len(raw), cost)

    if not raw:
        # Fail loudly rather than posting an empty caption. The publish is
        # already done, so the video is recoverable by hand from the URL in
        # plan.json; a post with no words is not.
        raise RuntimeError(
            f'caption call returned no text (stop_reason={msg.stop_reason}, '
            f'output_tokens={usage.get("output_tokens")})')

    try:
        data = _extract_json(raw)
        title = _clean(str(data.get('title', '')).strip())
        caption = _clean(str(data.get('caption', '')).strip())
        tiktok_title = _clean(str(data.get('tiktok_title', '')).strip()) or title
    except Exception:  # noqa: BLE001 - any parse failure takes the same recovery
        # Same recovery as the STEM pipeline's generate_caption: the model wrote
        # a usable caption in prose, so use it rather than throwing the call away.
        cleaned = _clean(raw)
        caption = cleaned
        title = cleaned.split('.')[0].strip()[:80]
        tiktok_title = title
        logger.warning('caption response was not JSON; derived title heuristically')

    if not caption or not title:
        raise RuntimeError(f'caption call produced an unusable result: '
                           f'title={title!r} caption={caption[:80]!r}')
    return {'title': title, 'caption': caption, 'tiktok_title': tiktok_title}, cost


# ============================================================
# job
# ============================================================
async def run():
    vid = common.video_id()
    t0 = time.time()

    # --- 1. plan + gates ----------------------------------------------------
    plan = common.load_plan(vid)
    topic = plan.get('topic') or plan.get('title') or ''
    wd = common.workdir(vid)
    gates_text = _gates_text(vid, wd)
    gates_passed = _gates_passed(plan, gates_text)
    logger.info(f'[{vid}] gates_passed={gates_passed} '
                f'(recorded only -- this job posts either way)')

    # --- 2. public copy -----------------------------------------------------
    public_url, public_bytes = _publish(vid)

    # --- 3. caption ---------------------------------------------------------
    narration = _narration_text(plan)
    if not narration:
        # Every path through prep writes narration, including the seed. An empty
        # one means a hand-edited or truncated plan; the topic alone still gives
        # the model something to work from, so say so and continue.
        logger.warning(f'[{vid}] plan.json has no narration text -- '
                       f'captioning from the topic alone')
    cap, caption_usd = _caption_claude(topic, narration)
    caption = cap['caption']
    youtube_title = cap['title'][:YOUTUBE_TITLE_MAX]
    tiktok_title = (cap.get('tiktok_title') or cap['title'])[:TIKTOK_TITLE_MAX]
    logger.info(f"[{vid}] title='{youtube_title}'  tiktok_title='{tiktok_title}'  "
                f"caption_first40='{caption[:40]}'")

    # --- 4. schedule --------------------------------------------------------
    schedule_time_str = os.environ.get('SCHEDULE_TIME')
    dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'
    # Set per-execution by the orchestrator (via the triggering EventBridge rule)
    # to hold YouTube and TikTok to their daily caps. When false, Metricool drops
    # that network from every blog. Both default to true.
    include_youtube = _flag('INCLUDE_YOUTUBE')
    include_tiktok = _flag('INCLUDE_TIKTOK')

    schedule_result = None
    if dry_run:
        status = 'dry_run'
        logger.info(
            f'[{vid}] DRY_RUN -- would schedule to Metricool:\n'
            f'  video_url       {public_url}\n'
            f'  schedule_time   {schedule_time_str}\n'
            f'  include_youtube {include_youtube}\n'
            f'  include_tiktok  {include_tiktok}\n'
            f'  youtube_title   {youtube_title}\n'
            f'  tiktok_title    {tiktok_title}\n'
            f'  caption         {caption}'
        )
    elif not schedule_time_str:
        # Non-fatal: this is what a manual smoke test looks like. Logged at
        # WARNING because on a scheduled run it means the slot silently produced
        # no post, which is otherwise invisible.
        status = 'no_schedule_time'
        logger.warning(f'[{vid}] SCHEDULE_TIME is not set -- nothing was posted')
    else:
        try:
            schedule_time = datetime.fromisoformat(schedule_time_str)
            # CLAMP. schedule_time is chosen by the orchestrator BEFORE the pipeline
            # runs (now + 30..90 min), but the run itself can outlast that: measured
            # end-to-end has already exceeded 30 minutes once, and the deployed
            # timeouts permit far more. Handing Metricool a publicationDate in the
            # past either errors or publishes instantly, which defeats the whole
            # point of spreading posts across the day.
            _floor = datetime.now(timezone.utc) + timedelta(minutes=5)
            if schedule_time < _floor:
                logger.warning(
                    "schedule_time %s is in the past (pipeline outran its window) "
                    "- clamping to %s", schedule_time.isoformat(), _floor.isoformat())
                schedule_time = _floor
        except ValueError as e:
            raise RuntimeError(
                f'SCHEDULE_TIME={schedule_time_str!r} is not ISO-8601: {e}') from e

        # Imported from THIS app dir, never from serverless/src: the two
        # pipelines share the secret and SES and nothing else (CONTRACT.md).
        from metricool_client import MetricoolClient

        logger.info(f'[{vid}] scheduling to Metricool for {schedule_time} '
                    f'(include_youtube={include_youtube}, '
                    f'include_tiktok={include_tiktok})...')
        schedule_result = await MetricoolClient().schedule_post(
            video_url=public_url,
            caption=caption,
            schedule_time=schedule_time,
            youtube_title=youtube_title,
            include_youtube=include_youtube,
            include_tiktok=include_tiktok,
            tiktok_title=tiktok_title,
        )
        for brand in schedule_result.get('results', []):
            if brand.get('success'):
                logger.info(f'[{vid}] scheduled brand {brand.get("blog_id")}: '
                            f'{brand.get("post_id")} '
                            f'(networks={brand.get("networks")})')
            else:
                logger.error(f'[{vid}] brand {brand.get("blog_id")} failed: '
                             f'{brand.get("error")}')
        status = 'scheduled' if schedule_result.get('success') else 'failed'

    # --- 5. record ----------------------------------------------------------
    plan['post'] = {
        'public_bucket': PUBLIC_BUCKET,
        'public_key': f'{PUBLIC_PREFIX}{vid}.mp4',
        'public_url': public_url,
        'bytes': public_bytes,
        'title': youtube_title,
        'tiktok_title': tiktok_title,
        'caption': caption,
        'schedule_time': schedule_time_str,
        'include_youtube': include_youtube,
        'include_tiktok': include_tiktok,
        'dry_run': dry_run,
        # Carried so the notify email can show the verdict next to a post that
        # went out regardless of it.
        'gates_passed': gates_passed,
        'status': status,
        'metricool': schedule_result,
        'recorded_at': datetime.now(timezone.utc).isoformat(),
    }
    plan.setdefault('cost', {})['caption_usd'] = round(caption_usd, 4)
    plan.setdefault('timings', {})['postprocess_s'] = round(time.time() - t0, 1)
    common.save_plan(vid, plan)

    logger.info(f'[{vid}] postprocess {status} in {time.time() - t0:.1f}s')

    # Raised AFTER the plan is saved, so the URL, the caption and Metricool's own
    # error are all on record before the job dies. A scheduled slot that quietly
    # rendered a video and never posted it is the one failure mode nobody
    # notices; this turns it into the FAILED notify email. It cannot cause a
    # double post: the job definition's terminal catch-all evaluateOnExit rule
    # ends the job on attempt 1 for anything that is not a known transient.
    if status == 'failed':
        raise RuntimeError(f'Metricool scheduling failed: '
                           f'{schedule_result.get("error")}')
