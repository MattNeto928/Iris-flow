"""
JOB_TYPE=postprocess -- ship the finished piece: public copies, copy, Metricool.

Runs after stitch and is the only job in this pipeline that publishes anything.

  1. out/video.mp4 is copied from the private motion bucket into the public
     iris-flow-videos-<account>. Metricool fetches the media itself, over plain
     HTTPS with no credentials, and the motion bucket blocks all public access --
     so a video that never leaves it can never be posted. The copy is
     SERVER-SIDE: download + re-upload of a ~40 MB file through a 2 vCPU task is
     wall clock and egress spent on a byte-identical result S3 will produce for
     free.
  2. ONE Opus 5 call (app/postcopy.py) writes copy for EVERY network and every
     companion format.
  3. Companion assets are cut from the finished video (app/slides.py): a
     carousel deck, a still, a 15s story.
  4. Up to four posts are scheduled -- the reel always, plus whichever
     companions this slot is flagged for.

UNCONDITIONALLY is still the word that matters. The check.py gates are read here
and recorded into plan.json so they reach the notify email, and they do NOT
gate: stitch already encodes a gate-failing render on purpose ("a gate result is
information"), and this job takes the same line all the way through to publish.

COMPANIONS ARE BUILT ON EVERY RUN, and only POSTED when the slot says so. They
cost ffmpeg seconds against a video that already exists, and building them
always means the assets are in S3 for any piece, so a good deck can be posted by
hand later without re-running the pipeline.

env:  VIDEO_ID, MOTION_BUCKET            (as every other job)
      PUBLIC_BUCKET_NAME                 optional, defaults to the deployed bucket
      SCHEDULE_TIME                      ISO-8601 UTC; absent => no post
      INCLUDE_YOUTUBE, INCLUDE_TIKTOK    per-network caps, default true
      POST_CAROUSEL, POST_STORY, POST_IMAGE   per-format caps, default FALSE
      DRY_RUN                            'true' => log the payload, post nothing
      ANTHROPIC_API_KEY
      METRICOOL_API_KEY / METRICOOL_USER_ID / METRICOOL_BLOG_ID
"""

import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import common
import postcopy
import slides as slidegen
from common import logger

PUBLIC_BUCKET = (os.environ.get('PUBLIC_BUCKET_NAME')
                 or os.environ.get('PUBLIC_BUCKET')
                 or 'iris-flow-videos-482625028438')
PUBLIC_PREFIX = 'motion/'

YOUTUBE_TITLE_MAX = 97
TIKTOK_TITLE_MAX = 80

# When each companion publishes, in Eastern wall-clock hours.
#
# The reel slots publish at roughly 8, 10, 12, 14 and 16 ET, so the companions
# take the ODD hours between them: 9 ET and 11 ET are the two best hours of the
# week for Instagram on this account (index 90 and 98 of 100) AND they are gaps
# in the reel schedule, so a carousel never lands on top of a reel.
#
# The story is the exception and goes out 90 MINUTES after its reel, on purpose:
# a story is a pointer to the reel, and a pointer is worth nothing once the
# thing it points at has scrolled away.
COMPANION_PLAN = {
    'story': {'offset_minutes': 90},
    'carousel': {'next_day_hour_et': 11},
    'image': {'next_day_hour_et': 9},
}
_ET = ZoneInfo('America/New_York')

_TRUTHY = ('1', 'true', 'yes', 'on')


# ============================================================
# env
# ============================================================
def _flag(name: str, default: str = 'true') -> bool:
    return os.environ.get(name, default).strip().lower() in _TRUTHY


def _motion_bucket() -> str:
    if not common.BUCKET:
        raise RuntimeError('MOTION_BUCKET / MOTION_BUCKET_NAME not set')
    return common.BUCKET


# ============================================================
# gates -- recorded, never enforced
# ============================================================
def _gates_text(vid: str, wd):
    path = common.download_file(vid, 'out/gates.txt', wd / 'gates.txt', optional=True)
    return path.read_text() if path else None


def _gates_passed(plan: dict, text):
    passed = (plan.get('output') or {}).get('gates_passed')
    if passed is None and text:
        passed = not ('FAIL:' in text or 'gates FAILED' in text)
    return passed


# ============================================================
# public copies
# ============================================================
def _public_url(key: str) -> str:
    # Same URL shape the STEM pipeline hands Metricool today. Path style over
    # the bucket's regional endpoint would also resolve, but this is the form
    # already known to work with their fetcher.
    return f'https://{PUBLIC_BUCKET}.s3.amazonaws.com/{key}'


def _publish_video(vid: str) -> tuple:
    """Server-side copy of out/video.mp4 into the public bucket -> (url, bytes)."""
    src_bucket = _motion_bucket()
    src_key = common.key(vid, 'out/video.mp4')
    dst_key = f'{PUBLIC_PREFIX}{vid}.mp4'

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
    # inherited from however stitch happened to upload the file.
    common.s3.copy_object(
        Bucket=PUBLIC_BUCKET, Key=dst_key,
        CopySource={'Bucket': src_bucket, 'Key': src_key},
        MetadataDirective='REPLACE', ContentType='video/mp4')

    url = _public_url(dst_key)
    logger.info(f'[{vid}] published {size / 1e6:.1f} MB -> {url}')
    return url, size


def _publish_asset(local, vid: str, name: str) -> str:
    """Upload one companion asset straight into the public bucket."""
    key = f'{PUBLIC_PREFIX}{vid}/{name}'
    common.s3.upload_file(
        str(local), PUBLIC_BUCKET, key,
        ExtraArgs={'ContentType': common._content_type(name)})
    return _public_url(key)


# ============================================================
# scheduling times
# ============================================================
def _companion_time(base: datetime, spec: dict) -> datetime:
    """
    When a companion publishes, from the reel's own schedule_time.

    next_day_hour_et is resolved in EASTERN wall clock and converted back to
    UTC, not computed as "+21 hours". Those differ by an hour across a DST
    boundary, and the whole point of the chosen hours is that they sit in the
    gaps between reel slots -- an hour of drift puts a carousel on top of a reel.
    """
    if 'offset_minutes' in spec:
        return base + timedelta(minutes=spec['offset_minutes'])
    et = base.astimezone(_ET) + timedelta(days=1)
    et = et.replace(hour=spec['next_day_hour_et'], minute=0,
                    second=0, microsecond=0)
    return et.astimezone(timezone.utc)


# Words that carry no topic. Instagram's hashtag suggestion endpoint keys off a
# single word, so handing it the FIRST word of the topic asks it about "Why" —
# which is what the first version of this did, for a piece titled "Why ice
# floats". The suggestions came back generic and the whole call was wasted.
_STOP = {'why', 'how', 'what', 'when', 'the', 'a', 'an', 'and', 'or', 'of',
         'in', 'on', 'is', 'are', 'does', 'do', 'this', 'that', 'to', 'for',
         'from', 'with', 'its', 'it', 'you', 'your', 'can', 'not'}


def _hashtag_seed(topic: str, fallback: str) -> str:
    """
    The one word to ask Instagram about: the longest non-stopword available.

    Longest is a crude proxy for most specific, and it is the right crude proxy
    here — "hydrogen" and "hexagonal" beat "ice" for finding the tags a niche
    audience actually follows, and a bad seed costs only a generic list.
    """
    for source in (topic, fallback):
        words = [w.strip('.,:;!?()"\'').lower() for w in (source or '').split()]
        words = [w for w in words if w.isalpha() and len(w) >= 4 and w not in _STOP]
        if words:
            return max(words, key=len)
    return ''


def _clamp(when: datetime) -> datetime:
    """
    Never hand Metricool a publicationDate in the past.

    schedule_time is chosen by the orchestrator BEFORE the pipeline runs
    (now + 30..90 min), but the run itself can outlast that. A past date either
    errors or publishes instantly, which defeats spreading posts across the day.
    """
    floor = datetime.now(timezone.utc) + timedelta(minutes=5)
    if when < floor:
        logger.warning('schedule time %s is in the past (pipeline outran its '
                       'window) - clamping to %s', when.isoformat(), floor.isoformat())
        return floor
    return when


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
    public_url, public_bytes = _publish_video(vid)

    # --- 3. copy ------------------------------------------------------------
    segs = plan.get('narration') or []
    narration = '\n'.join(str(s.get('text', '')).strip()
                          for s in segs if isinstance(s, dict) and s.get('text'))
    if not narration:
        logger.warning(f'[{vid}] plan.json has no narration text -- '
                       f'writing copy from the topic alone')
    duration = sum(float(s.get('duration') or 0) for s in segs if isinstance(s, dict))
    bundle, copy_usd = postcopy.generate(topic, narration, duration)

    youtube_title = bundle['youtube']['title'][:YOUTUBE_TITLE_MAX]
    bundle['youtube']['title'] = youtube_title
    bundle['tiktok']['title'] = bundle['tiktok']['title'][:TIKTOK_TITLE_MAX]

    # --- 4. companion assets ------------------------------------------------
    # Built for every run whether or not this slot posts them: they are cheap
    # against a video that already exists, and an asset in S3 can be posted by
    # hand later, while an asset never built cannot.
    video_local = common.download_file(vid, 'out/video.mp4', wd / 'video.mp4')
    piece_html = ''
    piece_path = common.download_file(vid, 'piece.html', wd / 'piece_ro.html',
                                      optional=True)
    if piece_path:
        piece_html = piece_path.read_text(errors='replace')
    fps = float(plan.get('fps') or 30)

    assets = {}
    try:
        deck = slidegen.build_slides(video_local, wd, bundle['slides'],
                                     piece_html=piece_html, fps=fps)
        assets['slides'] = [_publish_asset(p, vid, p.name) for p in deck]
    except Exception as e:  # noqa: BLE001 - one format failing is not the run failing
        logger.warning('[%s] carousel assets failed: %s', vid, e)
        assets['slides'] = []
    try:
        still = slidegen.build_image(video_local, wd, bundle['slides'],
                                     piece_html=piece_html, fps=fps)
        assets['image'] = _publish_asset(still, vid, 'image.jpg') if still else None
    except Exception as e:  # noqa: BLE001
        logger.warning('[%s] still image failed: %s', vid, e)
        assets['image'] = None
    try:
        story = slidegen.build_story(video_local, wd)
        assets['story'] = _publish_asset(story, vid, 'story.mp4')
    except Exception as e:  # noqa: BLE001
        logger.warning('[%s] story asset failed: %s', vid, e)
        assets['story'] = None
    try:
        cover_ms = slidegen.best_cover_ms(video_local, wd, piece_html, fps)
    except Exception as e:  # noqa: BLE001 - Metricool defaults to frame 0
        logger.warning('[%s] cover frame selection failed: %s', vid, e)
        cover_ms = None

    logger.info('[%s] assets: %d slides, image=%s, story=%s, cover=%sms',
                vid, len(assets['slides']), bool(assets['image']),
                bool(assets['story']), cover_ms)

    # --- 5. schedule --------------------------------------------------------
    schedule_time_str = os.environ.get('SCHEDULE_TIME')
    dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'
    include_youtube = _flag('INCLUDE_YOUTUBE')
    include_tiktok = _flag('INCLUDE_TIKTOK')
    # Default FALSE, unlike the network flags: a hand-run execution should post
    # the reel and nothing else rather than surprise the accounts with three
    # extra posts it never asked for.
    post_carousel = _flag('POST_CAROUSEL', 'false')
    post_story = _flag('POST_STORY', 'false')
    post_image = _flag('POST_IMAGE', 'false')

    from metricool_client import MetricoolClient
    mc = MetricoolClient()

    # Instagram's own suggestions, merged behind the model's tags: the model's
    # are topical, Instagram's are the ones it recognises, and a caption wants
    # both. Never replaces, only tops up to 12.
    tags = list(bundle['instagram']['hashtags'])
    for extra in await mc.suggest_hashtags(_hashtag_seed(topic, youtube_title), limit=8):
        if len(tags) >= 12:
            break
        if extra.lower() not in {t.lower() for t in tags}:
            tags.append(extra)
    bundle['instagram']['hashtags'] = tags
    first_comment = ' '.join(tags)

    audio = None
    if mc.instagram_audio and bundle.get('audio_query'):
        audio = await mc.find_instagram_audio(bundle['audio_query'],
                                              min_ms=int(duration * 1000))

    # GATES NOW DECIDE WHETHER THIS PUBLISHES.
    #
    # This job used to post unconditionally, on the reasoning that "a gate
    # result is information" and stitch encodes a gate-failing render anyway.
    # That reasoning did not survive contact: on 2026-07-29 both pieces that
    # reached this point had FAILED their gates and both went to live accounts —
    # one a black screen with captions at mean luma 7.9, the other swinging from
    # luma 12 to 64 with 25% blown pixels. One had to be deleted by hand.
    #
    # A skipped slot costs one post out of a 98-topic queue. A bad post costs
    # the account. The email is the deliverable when this trips: notify sends
    # the failure mail with the gate output in it, so the run is not silent.
    require_gates = _flag('REQUIRE_GATES', 'true')
    gate_block = require_gates and gates_passed is False
    if gate_block:
        logger.error(
            '[%s] GATES FAILED and REQUIRE_GATES is on — publishing nothing. '
            'Gate output:\n%s', vid, (gates_text or '(no gates.txt)')[:2000])

    posts = {}
    if gate_block:
        status = 'blocked_gates_failed'
    elif dry_run:
        status = 'dry_run'
        logger.info(
            f'[{vid}] DRY_RUN -- would schedule:\n'
            f'  reel        {public_url}\n'
            f'  at          {schedule_time_str} (yt={include_youtube} tt={include_tiktok})\n'
            f'  yt_title    {youtube_title}\n'
            f'  yt_tags     {bundle["youtube"]["tags"]}\n'
            f'  yt_category {bundle["youtube"]["category"]}\n'
            f'  ig_caption  {bundle["instagram"]["caption"]}\n'
            f'  first_comm  {first_comment}\n'
            f'  tiktok      {bundle["tiktok"]["title"]} | {bundle["tiktok"]["caption"][:80]}\n'
            f'  fb_caption  {bundle["facebook"]["caption"][:120]}\n'
            f'  alt_text    {bundle["alt_text"]}\n'
            f'  cover_ms    {cover_ms}\n'
            f'  audio       {audio.get("title") if audio else None}\n'
            f'  carousel    {post_carousel} ({len(assets["slides"])} slides)\n'
            f'  story       {post_story} ({assets["story"]})\n'
            f'  image       {post_image} ({assets["image"]})'
        )
    elif not schedule_time_str:
        status = 'no_schedule_time'
        logger.warning(f'[{vid}] SCHEDULE_TIME is not set -- nothing was posted')
    else:
        try:
            base = datetime.fromisoformat(schedule_time_str)
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
        except ValueError as e:
            raise RuntimeError(
                f'SCHEDULE_TIME={schedule_time_str!r} is not ISO-8601: {e}') from e

        # The reel. This one is the post; the rest are companions to it.
        posts['reel'] = await mc.schedule(
            kind='reel', media=[public_url], copy=bundle,
            schedule_time=_clamp(base),
            include_youtube=include_youtube, include_tiktok=include_tiktok,
            alt_text=bundle['alt_text'], first_comment=first_comment,
            cover_ms=cover_ms, audio=audio)

        # Companions. Each is independently gated by its slot flag AND by
        # whether its asset actually got built, and a failure in one never
        # touches another -- schedule() reports rather than raises.
        if post_story and assets['story']:
            story_copy = dict(bundle)
            story_copy['instagram'] = dict(bundle['instagram'],
                                           caption=bundle.get('story_text') or '')
            posts['story'] = await mc.schedule(
                kind='story', media=[assets['story']], copy=story_copy,
                schedule_time=_clamp(_companion_time(base, COMPANION_PLAN['story'])),
                include_youtube=False, include_tiktok=False,
                alt_text=bundle['alt_text'])

        if post_carousel and assets['slides']:
            posts['carousel'] = await mc.schedule(
                kind='carousel', media=assets['slides'], copy=bundle,
                schedule_time=_clamp(_companion_time(base, COMPANION_PLAN['carousel'])),
                include_youtube=False, include_tiktok=include_tiktok,
                alt_text=bundle['alt_text'], first_comment=first_comment)

        if post_image and assets['image']:
            image_copy = dict(bundle)
            image_copy['instagram'] = dict(bundle['instagram'],
                                           caption=bundle.get('image_caption') or '')
            posts['image'] = await mc.schedule(
                kind='image', media=[assets['image']], copy=image_copy,
                schedule_time=_clamp(_companion_time(base, COMPANION_PLAN['image'])),
                include_youtube=False, include_tiktok=False,
                alt_text=bundle['alt_text'], first_comment=first_comment)

        for kind, res in posts.items():
            for brand in res.get('results', []):
                if brand.get('success'):
                    logger.info(f'[{vid}] {kind} -> blog {brand.get("blog_id")} '
                                f'post {brand.get("post_id")} '
                                f'networks={brand.get("networks")}')
                else:
                    logger.error(f'[{vid}] {kind} -> blog {brand.get("blog_id")} '
                                 f'FAILED: {brand.get("error")}')

        # The REEL is what decides the run's verdict. A companion that fails is
        # logged and reported but does not fail the job: the piece published,
        # and failing here would send a FAILED email about a post that went out
        # fine, on top of retry semantics for a job that must never retry.
        status = 'scheduled' if posts['reel'].get('success') else 'failed'

    # --- 6. record ----------------------------------------------------------
    plan['post'] = {
        'public_bucket': PUBLIC_BUCKET,
        'public_key': f'{PUBLIC_PREFIX}{vid}.mp4',
        'public_url': public_url,
        'bytes': public_bytes,
        'title': youtube_title,
        'tiktok_title': bundle['tiktok']['title'],
        'caption': bundle['instagram']['caption'],
        'copy': bundle,
        'assets': assets,
        'cover_ms': cover_ms,
        'audio': {'id': audio.get('audioId'), 'title': audio.get('title'),
                  'artist': audio.get('displayArtist')} if audio else None,
        'first_comment': first_comment,
        'schedule_time': schedule_time_str,
        'include_youtube': include_youtube,
        'include_tiktok': include_tiktok,
        'post_carousel': post_carousel,
        'post_story': post_story,
        'post_image': post_image,
        'dry_run': dry_run,
        'gates_passed': gates_passed,
        'require_gates': require_gates,
        # Carried so the failure email can say WHY nothing published, instead of
        # sending the operator to CloudWatch to find out.
        'gates_text': (gates_text or '')[:4000],
        'status': status,
        'metricool': posts,
        'recorded_at': datetime.now(timezone.utc).isoformat(),
    }
    plan.setdefault('cost', {})['caption_usd'] = round(copy_usd, 4)
    plan.setdefault('timings', {})['postprocess_s'] = round(time.time() - t0, 1)
    common.save_plan(vid, plan)

    logger.info(f'[{vid}] postprocess {status} in {time.time() - t0:.1f}s '
                f'({len(posts)} post(s) scheduled)')

    # Raised AFTER the plan is saved, so the URLs, the copy and Metricool's own
    # error are all on record before the job dies. A scheduled slot that quietly
    # rendered a video and never posted it is the one failure mode nobody
    # notices; this turns it into the FAILED notify email. It cannot cause a
    # double post: the job definition's terminal catch-all evaluateOnExit rule
    # ends the job on attempt 1 for anything that is not a known transient.
    # Raised AFTER the plan is saved so the assets, the copy and the gate output
    # are all on record first. Both of these route the execution to the failure
    # path, which is what actually sends the email.
    if gate_block:
        raise RuntimeError(
            f'gates FAILED and REQUIRE_GATES is on — nothing was published for '
            f'{vid}. The video and all its assets are in S3 and can be posted by '
            f'hand from {public_url} if the gate call was wrong.\n\n'
            f'{(gates_text or "(no gates.txt)")[:1500]}')
    if status == 'failed':
        raise RuntimeError(f'Metricool scheduling failed: '
                           f'{posts["reel"].get("error")}')
