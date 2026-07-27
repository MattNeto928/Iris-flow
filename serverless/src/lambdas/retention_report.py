"""
Retention Report Lambda — the pipeline's KPI watchdog.

Runs weekly (EventBridge). Pulls the last 14 days of Instagram Reels analytics
from Metricool, joins each post to its S3 render manifest (publish-time
proximity) to recover the topic category, and emails a report via the existing
iris-flow-alerts SNS topic:

  - week-over-week median views and watch-through
  - per-category medians for the window (categories under the watch floor are
    flagged for removal from the topic mix)
  - top / bottom posts by watch-through

Watch-through (averageWatchTime / durationSeconds) is the KPI: measured views
scale ~2.6x from the lowest to the highest retention quartile, so a falling
watch%% is the earliest signal the content mix is drifting.

Pure stdlib + boto3 — no layer needed (httpx is not available in this asset).
"""

import json
import logging
import os
import statistics
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SECRET_ID = os.environ.get('API_SECRET_ID', 'iris-flow/api-keys')
ALERTS_TOPIC_ARN = os.environ['ALERTS_TOPIC_ARN']
VIDEO_BUCKET = os.environ['VIDEO_BUCKET_NAME']

# Categories whose 14-day median watch%% falls below this are flagged.
WATCH_FLOOR_PCT = 15.0
# Manifest→post join window: posts go out 30-90 min after the render finishes.
JOIN_WINDOW_HOURS = 4

METRICOOL_BASE = 'https://app.metricool.com/api'

s3 = boto3.client('s3')
sns = boto3.client('sns')
secrets = boto3.client('secretsmanager')


def _metricool_creds() -> dict:
    val = secrets.get_secret_value(SecretId=SECRET_ID)['SecretString']
    data = json.loads(val)
    return {
        'api_key': data['METRICOOL_API_KEY'],
        'user_id': data['METRICOOL_USER_ID'],
        'blog_id': data['METRICOOL_BLOG_ID'].split(',')[0],
    }


def _fetch_reels(creds: dict, start: datetime, end: datetime) -> list:
    qs = urllib.parse.urlencode({
        'from': start.strftime('%Y-%m-%dT%H:%M:%S'),
        'to': end.strftime('%Y-%m-%dT%H:%M:%S'),
        'blogId': creds['blog_id'],
        'userId': creds['user_id'],
    })
    req = urllib.request.Request(
        f'{METRICOOL_BASE}/v2/analytics/reels/instagram?{qs}',
        headers={'X-Mc-Auth': creds['api_key']},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read()).get('data', [])


def _load_manifests(start: datetime) -> list:
    """List jobs/*/manifest.json modified since `start`; return [{ts, category}]."""
    out = []
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=VIDEO_BUCKET, Prefix='jobs/'):
        for obj in page.get('Contents', []):
            if not obj['Key'].endswith('/manifest.json'):
                continue
            if obj['LastModified'] < start:
                continue
            try:
                body = s3.get_object(Bucket=VIDEO_BUCKET, Key=obj['Key'])['Body'].read()
                m = json.loads(body)
            except Exception as e:  # noqa: BLE001 - one bad manifest shouldn't kill the report
                logger.warning('Skipping unreadable manifest %s: %s', obj['Key'], e)
                continue
            out.append({
                'ts': obj['LastModified'],
                'category': m.get('category', 'unknown'),
            })
    return out


def _parse_publish_utc(post: dict) -> datetime | None:
    """Metricool reports publishedAt as wall clock + tz name; approximate UTC."""
    pub = post.get('publishedAt') or {}
    dt_str = pub.get('dateTime')
    if not dt_str:
        return None
    dt = datetime.fromisoformat(dt_str)
    tz_name = pub.get('timezone') or 'UTC'
    # Metricool returns Europe/Madrid for this account. Lambda's Python has
    # zoneinfo; fall back to UTC for unknown zones.
    try:
        from zoneinfo import ZoneInfo
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _med(values, default=None):
    return statistics.median(values) if values else default


def handler(event, context):
    now = datetime.now(timezone.utc)
    start14 = now - timedelta(days=14)
    start7 = now - timedelta(days=7)

    creds = _metricool_creds()
    posts_raw = _fetch_reels(creds, start14, now)

    posts = []
    for p in posts_raw:
        pub = _parse_publish_utc(p)
        if pub is None:
            continue
        dur = p.get('durationSeconds') or 0
        awt = p.get('averageWatchTime') or 0
        posts.append({
            'utc': pub,
            'views': p.get('views') or 0,
            'watch': (awt / dur * 100) if (awt and dur) else None,
            'content': (p.get('content') or '')[:80],
            'url': p.get('url') or '',
        })

    # Join category from manifests by publish-time proximity.
    manifests = _load_manifests(start14 - timedelta(hours=JOIN_WINDOW_HOURS))
    for post in posts:
        best, best_dt = None, timedelta(hours=JOIN_WINDOW_HOURS)
        for m in manifests:
            delta = post['utc'] - m['ts']
            if timedelta(0) <= delta < best_dt:
                best, best_dt = m, delta
        post['category'] = best['category'] if best else 'unmatched'

    this_week = [p for p in posts if p['utc'] >= start7]
    last_week = [p for p in posts if p['utc'] < start7]

    def stats_line(label, rows):
        views = [r['views'] for r in rows]
        watch = [r['watch'] for r in rows if r['watch'] is not None]
        return (
            f"{label}: {len(rows)} posts, median {_med(views, 0):,.0f} views, "
            f"median watch-through {_med(watch, 0):.1f}%"
        )

    lines = [
        'IRIS-FLOW WEEKLY RETENTION REPORT (Instagram Reels)',
        '',
        stats_line('This week', this_week),
        stats_line('Last week', last_week),
        '',
        'BY CATEGORY (14 days):',
    ]

    by_cat = {}
    for p in posts:
        by_cat.setdefault(p['category'], []).append(p)
    flagged = []
    for cat, rows in sorted(by_cat.items(),
                            key=lambda kv: -(_med([r['views'] for r in kv[1]], 0))):
        watch = [r['watch'] for r in rows if r['watch'] is not None]
        med_watch = _med(watch)
        flag = ''
        if med_watch is not None and med_watch < WATCH_FLOOR_PCT and len(rows) >= 3:
            flag = f'  << BELOW {WATCH_FLOOR_PCT:.0f}% FLOOR — cut from topic mix'
            flagged.append(cat)
        lines.append(
            f"  {cat}: n={len(rows)}, median {_med([r['views'] for r in rows], 0):,.0f} views, "
            f"watch {med_watch if med_watch is not None else float('nan'):.1f}%{flag}"
        )

    ranked = sorted((p for p in posts if p['watch'] is not None),
                    key=lambda p: -p['watch'])
    if ranked:
        lines += ['', 'TOP 3 BY WATCH-THROUGH:']
        lines += [f"  {p['watch']:.0f}% / {p['views']:,} views — {p['content']}"
                  for p in ranked[:3]]
        lines += ['', 'BOTTOM 3 BY WATCH-THROUGH:']
        lines += [f"  {p['watch']:.0f}% / {p['views']:,} views — {p['content']}"
                  for p in ranked[-3:]]

    report = '\n'.join(lines)
    logger.info(report)

    subject = 'Iris-flow retention report'
    if flagged:
        subject += f" — {len(flagged)} categor{'y' if len(flagged) == 1 else 'ies'} below floor"
    sns.publish(TopicArn=ALERTS_TOPIC_ARN, Subject=subject[:100], Message=report)

    return {'posts': len(posts), 'flagged_categories': flagged}
