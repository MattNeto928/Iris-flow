"""
What actually held viewers — fed back into the next piece we author.

The pipeline has always had per-post retention data sitting in Metricool and has
never once read it. Every piece was authored as if it were the first. This
closes that loop: pull the reels this channel published, match each one back to
the plan.json that produced it, and hand the authoring call a short digest of
which pieces held people and which lost them.

WHY RETENTION AND NOT VIEWS. Measured on 273 of our own reels, views correlate
with `reelsSkipRate` at rho -0.72 and with `averageWatchTime` at +0.68, while
publish hour correlates at -0.008. Views are the OUTCOME; retention is the thing
the piece controls. Ranking by views would also just rank by luck — the top 3
reels carry 46% of all views, so a single viral post would drown the signal.

Never raises. This is advisory context on the publish path: if Metricool is down
or nothing matches, authoring proceeds exactly as it did before.
"""

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import common
from common import logger

BASE = 'https://app.metricool.com/api'
LOOKBACK_DAYS = int(os.environ.get('WINNERS_LOOKBACK_DAYS', '30'))
# Below this a reel has not been seen by enough people for its retention to mean
# anything; early impressions are noisy and a 200-view post is mostly chance.
MIN_VIEWS = int(os.environ.get('WINNERS_MIN_VIEWS', '600'))
N_BEST, N_WORST = 3, 2


def _get(path, **params):
    q = urllib.parse.urlencode({
        'userId': os.environ.get('METRICOOL_USER_ID', ''),
        'blogId': (os.environ.get('METRICOOL_BLOG_ID', '') or '').split(',')[0],
        **params})
    req = urllib.request.Request(
        f'{BASE}{path}?{q}',
        headers={'X-Mc-Auth': os.environ.get('METRICOOL_API_KEY', '')})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())


def _norm(text):
    """Loose key for matching a caption we wrote to one Metricool reports."""
    return re.sub(r'[^a-z0-9]', '', (text or '').lower())[:60]


def _publish_utc(info):
    """{dateTime, timezone} as Metricool reports it -> aware UTC datetime."""
    dt_str = (info or {}).get('dateTime')
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
    except ValueError:
        return None
    try:
        from zoneinfo import ZoneInfo
        dt = dt.replace(tzinfo=ZoneInfo((info.get('timezone') or 'UTC')))
    except Exception:                                        # noqa: BLE001
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _our_pieces(days):
    """
    Everything this pipeline posted, keyed BOTH ways.

    Matching is by PUBLISH TIME first and caption second, and the order matters.
    Caption alone looked obvious and is wrong: plan.json's caption is rewritten
    every time postprocess runs, so any re-run or rehearsal against an existing
    video silently detaches it from the post that actually went out. MEASURED —
    the ice piece published as "Freezing water expands into a hexagonal
    lattice..." and its plan now reads "Almost everything shrinks when it
    freezes...", because a later dry run regenerated the copy. Zero of seven
    pieces matched on caption.

    The scheduled time is written once, by the run that booked the post, and is
    never regenerated.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = []
    paginator = common.s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=common.BUCKET, Prefix='jobs/'):
        for obj in page.get('Contents', []):
            if not obj['Key'].endswith('/plan.json') or obj['LastModified'] < cutoff:
                continue
            try:
                plan = json.loads(common.s3.get_object(
                    Bucket=common.BUCKET, Key=obj['Key'])['Body'].read())
            except Exception:                                # noqa: BLE001
                continue
            post = plan.get('post') or {}
            if post.get('status') not in ('scheduled',):
                continue
            narr = plan.get('narration') or []
            when = None
            if post.get('schedule_time'):
                try:
                    when = datetime.fromisoformat(post['schedule_time'])
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                except ValueError:
                    when = None
            rows.append({
                'when': when,
                'caption_key': _norm(post.get('caption')),
                'topic': plan.get('topic') or plan.get('title') or '',
                'hook': (narr[0].get('text') if narr else '') or '',
            })
    return rows


def _match(reel, rows):
    """The plan that produced this reel, by publish time then by caption."""
    pub = _publish_utc(reel.get('publishedAt'))
    if pub:
        for r in rows:
            # +-45 min: the orchestrator picks a time up to 90 minutes out and
            # Metricool publishes near it, but not to the second.
            if r['when'] and abs((pub - r['when']).total_seconds()) <= 2700:
                return r
    key = _norm(reel.get('content'))
    if key:
        for r in rows:
            if r['caption_key'] and r['caption_key'] == key:
                return r
    return None


def digest(days=LOOKBACK_DAYS):
    """
    A short prompt section naming what worked and what did not. '' when there is
    not enough matched data to say anything honest.
    """
    if not os.environ.get('METRICOOL_API_KEY'):
        return ''
    try:
        now = datetime.now(timezone.utc)
        data = _get('/v2/analytics/reels/instagram',
                    **{'from': (now - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S'),
                       'to': now.strftime('%Y-%m-%dT%H:%M:%S')})
        reels = data.get('data', []) if isinstance(data, dict) else []
    except Exception as e:                                   # noqa: BLE001
        logger.warning('winners: analytics fetch failed (%s) — authoring '
                       'without retention context', e)
        return ''

    try:
        ours = _our_pieces(days)
    except Exception as e:                                   # noqa: BLE001
        logger.warning('winners: could not read our own plans (%s)', e)
        return ''

    rows = []
    for r in reels:
        if (r.get('views') or 0) < MIN_VIEWS:
            continue
        mine = _match(r, ours)
        if not mine:
            continue
        dur = r.get('durationSeconds') or 0
        watch = r.get('averageWatchTime') or 0
        rows.append({
            'topic': mine['topic'][:110],
            'hook': mine['hook'][:150],
            'skip': r.get('reelsSkipRate') or 0,
            'watch': watch,
            'held': (watch / dur * 100) if dur else 0,
            'views': r.get('views') or 0,
        })

    # Four is the floor for saying "these did better than those" without it
    # being one post either side of noise.
    if len(rows) < 4:
        logger.info('winners: only %d matched reels above %d views — no digest',
                    len(rows), MIN_VIEWS)
        return ''

    rows.sort(key=lambda x: x['skip'])          # lowest skip rate = held best
    best, worst = rows[:N_BEST], rows[-N_WORST:]

    def block(rs):
        return '\n'.join(
            f'  - "{r["topic"]}"\n'
            f'    skip {r["skip"]:.0f}%, held {r["held"]:.0f}% of its length, '
            f'{r["views"]:,} views\n'
            f'    opened with: {r["hook"]}'
            for r in rs)

    logger.info('winners: %d matched reels, best skip %.0f%% / worst %.0f%%',
                len(rows), best[0]['skip'], worst[-1]['skip'])
    return f"""
THIS CHANNEL'S OWN RETENTION DATA, from the last {days} days. Skip rate is the
share of viewers who swiped away; it is the strongest predictor of reach we have
(rho -0.72 against views), so it is the number to beat.

HELD PEOPLE BEST:
{block(best)}

LOST PEOPLE FASTEST:
{block(worst)}

Read the openings above and notice what separates them. Then write a piece that
belongs in the first group. Do not copy these topics — they are done."""
