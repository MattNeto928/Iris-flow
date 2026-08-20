"""
Notify Lambda — the only thing in iris-motion that reports a run to a human.

It runs on BOTH paths: as the last state of a successful pipeline, and as the
target of the state machine's global `.addCatch`, in which case the event also
carries an `error` key. That makes it the single place a broken run becomes
visible, which is why nothing in here is allowed to raise: an exception in the
notifier turns a diagnosable failure into a silent one. Every section of the
email is built independently and degrades to a one-line "not available" note.

Emails via SES (mattneto928@gmail.com is a verified identity and the account is
out of the sandbox). NOT SNS — the iris-flow-alerts topic has no confirmed
subscriptions, and a presigned URL is too long to survive an SNS subject line.

What it reads from S3. Everything except video.mp4 is optional, because on the
failure path most of it will not exist yet:

  jobs/<id>/out/video.mp4   presigned, 7 days
  jobs/<id>/out/gates.txt   check.py stdout + stitch's PASSED/FAILED footer
  jobs/<id>/plan.json       written by app/prep.py, extended by app/stitch.py:
      "output":  {...}                       ffprobe facts + gates_passed +
                                             verified, written by stitch
      "cost":    {"author_usd": 0.85, ...}   every numeric entry is summed
      "timings": {"prep_s": 41.2, ...}       seconds; a _s/_sec/_seconds suffix
                                             is stripped. render, if it is ever
                                             recorded, is TASK-seconds summed
                                             across the shards.
  jobs/<id>/out/probe.json  only if some future stitch writes probe data there
                            instead of into plan["output"]
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MOTION_BUCKET = os.environ.get('MOTION_BUCKET', '')
MAIL_FROM = os.environ.get('MAIL_FROM', 'mattneto928@gmail.com')
MAIL_TO = os.environ.get('MAIL_TO', 'mattneto928@gmail.com')

# 7 days is the SigV4 ceiling. See the caveat printed next to the link in the
# body: the signature also dies with the credentials that made it.
PRESIGN_TTL = 7 * 24 * 3600

# us-east-1 Fargate on-demand, from CONTRACT.md. Spot bills materially less, so
# a cost computed from these rates is an upper bound — which is the number worth
# putting in an email against a $3.00/video budget.
VCPU_HOUR_USD = 0.04048
GB_HOUR_USD = 0.004445
BUDGET_USD = 3.00

# vCPU / GiB per JOB_TYPE, mirroring the three job definitions in the CDK stack.
PHASE_SHAPE = {'prep': (2, 4), 'render': (4, 8), 'stitch': (2, 8)}

_region = os.environ.get('AWS_REGION', 'us-east-1')
# s3v4 explicitly: a presigned GET signed with the older algorithm is rejected
# by buckets in newer regions, and the failure only shows up when someone clicks
# the link hours later.
s3 = boto3.client('s3', region_name=_region, config=Config(signature_version='s3v4'))
ses = boto3.client('ses', region_name=_region)


def _s3_text(key, limit=8000):
    """Fetch a small text object. Returns None if it is not there."""
    try:
        body = s3.get_object(Bucket=MOTION_BUCKET, Key=key)['Body'].read()
    except Exception as e:  # noqa: BLE001 - a missing file is a normal outcome here
        logger.info('no %s (%s)', key, type(e).__name__)
        return None
    text = body.decode('utf-8', 'replace')
    if len(text) > limit:
        text = text[:limit] + f'\n... [truncated at {limit} chars]'
    return text


def _s3_json(key):
    text = _s3_text(key, limit=262144)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception as e:  # noqa: BLE001
        logger.warning('%s is not valid JSON: %s', key, e)
        return None


def _fmt_bytes(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.1f} {unit}' if unit != 'B' else f'{n} B'
        n /= 1024.0
    return f'{n:.1f} GB'


def _video_lines(video_id):
    """Presigned link + the S3 fallback. Returns (lines, video_exists)."""
    key = f'jobs/{video_id}/out/video.mp4'
    uri = f's3://{MOTION_BUCKET}/{key}'
    try:
        head = s3.head_object(Bucket=MOTION_BUCKET, Key=key)
    except Exception:  # noqa: BLE001
        return ([f'  NO VIDEO at {uri}',
                 '  (stitch never uploaded it -- see the error section)'], False)

    lines = [f'  size      {_fmt_bytes(head["ContentLength"])}',
             f'  s3        {uri}']
    try:
        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': MOTION_BUCKET, 'Key': key},
            ExpiresIn=PRESIGN_TTL,
        )
        lines += [
            '',
            f'  {url}',
            '',
            '  Signed for 7 days, but a presigned URL also expires with the',
            '  credentials that signed it, and Lambda role credentials are',
            '  temporary. If the link 403s, pull it directly instead:',
            f'    aws s3 cp {uri} .',
        ]
    except Exception as e:  # noqa: BLE001
        lines.append(f'  could not presign: {e}')
    return (lines, True)


# Already reported in the VIDEO section, or noise in a probe listing.
_PROBE_SKIP = ('s3_key', 'gates_s3_key', 'gates_passed', 'bytes')


def _probe(plan, video_id):
    """app/stitch.py writes the ffprobe facts into plan["output"]."""
    for candidate in ((plan or {}).get('output'), (plan or {}).get('probe')):
        if isinstance(candidate, dict) and candidate:
            return candidate
    found = _s3_json(f'jobs/{video_id}/out/probe.json')
    return found if isinstance(found, dict) else None


def _probe_lines(probe, plan):
    """
    Flatten the probe dict. stitch already checks the file against CONTRACT
    rule 7 and raises on a mismatch, so `verified: false` should be unreachable
    -- print it loudly if it ever is, because that MP4 will break
    concatenate_videos in the existing Iris-flow pipeline rather than here.
    """
    if not probe:
        fps = (plan or {}).get('fps')
        frames = (plan or {}).get('frames')
        if fps and frames:
            return [f'  not recorded; plan.json says {frames} frames at {fps} fps '
                    f'({frames / float(fps):.1f}s)']
        return ['  not recorded']

    lines = []
    for k in sorted(probe):
        if k in _PROBE_SKIP:
            continue
        value = probe[k]
        if isinstance(value, dict):
            value = ' '.join(f'{sub}={value[sub]}' for sub in sorted(value))
        lines.append(f'  {k:<12} {value}')

    if probe.get('verified') is False:
        lines.append('  !! does NOT meet CONTRACT rule 7 '
                     '(h264 High / yuv420p / 1080x1920 / 30 fps / aac)')
    return lines


def _phase_seconds(timings):
    """Normalise {"render_seconds": 268} / {"render": 268} to {"render": 268.0}."""
    out = {}
    if not isinstance(timings, dict):
        return out
    for raw_key, value in timings.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        key = str(raw_key).lower()
        for suffix in ('_seconds', '_secs', '_sec', '_s'):
            if key.endswith(suffix):
                key = key[: -len(suffix)]
                break
        out[key] = float(value)
    return out


def _cost_lines(plan):
    """Reported cost from plan.json plus Fargate compute derived from timings."""
    lines = []
    total = 0.0

    cost = (plan or {}).get('cost')
    if isinstance(cost, dict):
        for key in sorted(cost):
            value = cost[key]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                lines.append(f'  {key:<22} ${float(value):.4f}')
                total += float(value)

    phases = _phase_seconds((plan or {}).get('timings'))
    compute = 0.0
    for phase, secs in phases.items():
        vcpu, gib = PHASE_SHAPE.get(phase, (0, 0))
        if vcpu:
            compute += secs / 3600.0 * (vcpu * VCPU_HOUR_USD + gib * GB_HOUR_USD)
    if compute:
        lines.append(f'  {"fargate_compute_usd":<22} ${compute:.4f}   '
                     f'(on-demand rate; Spot bills less)')
        total += compute

    if not lines:
        return ['  not recorded in plan.json']

    flag = '   << OVER BUDGET' if total > BUDGET_USD else ''
    lines.append(f'  {"TOTAL":<22} ${total:.4f}   '
                 f'(budget ${BUDGET_USD:.2f}){flag}')
    return lines


def _timing_lines(plan):
    phases = _phase_seconds((plan or {}).get('timings'))
    if not phases:
        return None
    return [f'  {phase:<22} {secs:7.1f}s' for phase, secs in sorted(phases.items())]


def _error_lines(error):
    """
    Render whatever addCatch produced. Step Functions hands back
    {"Error": "...", "Cause": "..."} where Cause is usually a JSON blob with the
    real message buried in it, so unpack it rather than printing one long line.
    """
    if isinstance(error, str):
        return ['  ' + error]
    if not isinstance(error, dict):
        return ['  ' + repr(error)]

    lines = []
    for key in ('Error', 'error'):
        if error.get(key):
            lines.append(f'  type   {error[key]}')
            break

    cause = error.get('Cause') or error.get('cause')
    if isinstance(cause, str):
        try:
            cause = json.loads(cause)
        except Exception:  # noqa: BLE001 - plain-string causes are common
            pass
    if isinstance(cause, dict):
        for key in sorted(cause):
            value = cause[key]
            if isinstance(value, list):
                value = ' | '.join(str(v) for v in value)
            lines.append(f'  {key:<20} {str(value)[:600]}')
    elif cause is not None:
        lines.append(f'  cause  {str(cause)[:1200]}')

    if not lines:
        lines = ['  ' + json.dumps(error)[:1200]]
    return lines


def _post_lines(plan):
    """
    What happened on the social side.

    Without this the email reports a green render and says nothing about whether
    a post was booked — and booking the post is the entire point of a scheduled
    run. A run that rendered perfectly and silently published nothing looked
    identical to a complete success.
    """
    # `plan` is None whenever plan.json could not be read — a run that died in
    # prep before writing it, or a compile run whose video_id is 'unknown'.
    # Those are exactly the runs this email has to describe, so this must not
    # raise. An AttributeError here does not lose the mail outright (handler
    # falls back to a bare "notifier failed" note) but it DOES replace the
    # report — status, gate output, video link, cost — with a tooling error,
    # so a dead pipeline reads as a broken notifier. That is what disguised the
    # 2026-08-02..08-10 prep failures. Every sibling helper (_probe,
    # _cost_lines, _timing_lines) already guards this way; this one did not.
    post = (plan or {}).get('post') or {}
    if not post:
        return None
    out = [f"  status         {post.get('status', 'unknown')}"
           + ('   [DRY RUN — nothing booked]' if post.get('dry_run') else '')]

    # The gate block is the one status that needs explaining in the mail itself.
    # Anything else and the operator can go and look; this one they need to be
    # able to judge from the phone, because the alternative to publishing it is
    # a slot that stays empty.
    if post.get('status') == 'blocked_gates_failed':
        out.append("  NOTHING WAS PUBLISHED — the render failed its quality gates.")
        out.append(f"  The video is still at {post.get('public_url', '?')}")
        out.append("  and can be posted by hand if the gates were wrong.")
        for line in (post.get('gates_text') or '').splitlines():
            if line.startswith('FAIL:') or 'gates FAILED' in line:
                out.append(f"    {line}")
    if post.get('public_url'):
        out.append(f"  public url     {post['public_url']}")
    nets = [n for n, on in (('youtube', post.get('include_youtube')),
                            ('tiktok', post.get('include_tiktok'))) if on]
    out.append(f"  networks       {', '.join(nets) if nets else 'ig/facebook only'}")
    if post.get('schedule_time'):
        out.append(f"  scheduled for  {post['schedule_time']}")

    # Every booked post, one block per format. `metricool` is keyed by format
    # now (reel / story / carousel / image), not a flat results list.
    for kind, res in (post.get('metricool') or {}).items():
        if not isinstance(res, dict):
            continue
        out.append(f"  --- {kind} ---")
        if res.get('scheduled_time'):
            out.append(f"    at           {res['scheduled_time']} ET")
        for r in (res.get('results') or []):
            ok = 'ok' if r.get('success') else 'FAILED'
            out.append(f"    brand {r.get('blog_id')}  {ok}  "
                       f"{r.get('post_id') or r.get('error', '')}   "
                       f"{','.join(r.get('networks') or [])}")
        if not res.get('results'):
            out.append(f"    not booked   {res.get('error', 'no networks')}")

    # THE COPY ITSELF. This is here because a truncated JSON blob once reached
    # four live accounts as a caption and the email at the time reported only
    # "status scheduled" — everything looked green. The email now shows what the
    # audience will actually read, so a broken caption is visible in the inbox
    # rather than in the feed.
    c = post.get('copy') or {}
    if c:
        out.append("  --- copy ---")
        out.append(f"    yt title     {(c.get('youtube') or {}).get('title', '')[:80]}")
        out.append(f"    yt tags      {', '.join((c.get('youtube') or {}).get('tags') or [])[:110]}")
        out.append(f"    ig caption   {(c.get('instagram') or {}).get('caption', '')[:150]}")
        out.append(f"    first comment {(post.get('first_comment') or '')[:110]}")
        out.append(f"    tiktok       {(c.get('tiktok') or {}).get('title', '')[:80]}")
        out.append(f"    fb caption   {(c.get('facebook') or {}).get('caption', '')[:110]}")
        out.append(f"    alt text     {(c.get('alt_text') or '')[:110]}")
    a = post.get('assets') or {}
    out.append(f"  assets         {len(a.get('slides') or [])} slides, "
               f"image={'y' if a.get('image') else 'n'}, "
               f"story={'y' if a.get('story') else 'n'}, "
               f"cover={post.get('cover_ms')}ms")
    if post.get('audio'):
        out.append(f"  ig audio       {post['audio'].get('title')} "
                   f"— {post['audio'].get('artist')}")
    return out


def _section(title, lines):
    return [title] + (lines if lines else ['  n/a']) + ['']


def handler(event, context):
    """Never raises. Returns {'sent': bool, 'status': str, ...}."""
    try:
        return _notify(event)
    except Exception as e:  # noqa: BLE001 - a crash here loses the only report
        logger.exception('notify failed before it could send: %s', e)
        try:
            ses.send_email(
                Source=MAIL_FROM,
                Destination={'ToAddresses': [MAIL_TO]},
                Message={
                    'Subject': {'Data': 'iris-motion: notifier failed', 'Charset': 'UTF-8'},
                    'Body': {'Text': {'Data':
                        f'notify.py raised {type(e).__name__}: {e}\n\n'
                        f'event:\n{json.dumps(event, default=str)[:8000]}\n',
                        'Charset': 'UTF-8'}},
                },
            )
            return {'sent': True, 'status': 'NOTIFIER_ERROR'}
        except Exception as e2:  # noqa: BLE001
            logger.exception('SES also failed: %s', e2)
            return {'sent': False, 'status': 'NOTIFIER_ERROR'}


def _notify(event):
    if not isinstance(event, dict):
        event = {'raw_event': event}

    video_id = str(event.get('video_id') or 'unknown')
    error = event.get('error')
    plan = _s3_json(f'jobs/{video_id}/plan.json') if video_id != 'unknown' else None

    topic = event.get('topic') or (plan or {}).get('topic') or '(no topic)'
    gates = _s3_text(f'jobs/{video_id}/out/gates.txt')
    video_lines, have_video = _video_lines(video_id) if video_id != 'unknown' \
        else (['  no video_id in the event'], False)

    probe = _probe(plan, video_id)

    # stitch records the verdict in plan["output"]["gates_passed"] and never
    # aborts on it, so a gate failure reaches this Lambda as a SUCCESSFUL
    # execution. Without its own status it would be reported as OK and the bad
    # render would ship. The gates.txt scan is the fallback for a run that died
    # between writing the file and updating the plan.
    gates_passed = (probe or {}).get('gates_passed')
    gates_failed = gates_passed is False or (
        gates_passed is None and bool(gates) and
        ('FAIL:' in gates or 'gates FAILED' in gates)
    )

    if error is not None:
        status = 'FAILED'
    elif gates_failed:
        # The MP4 exists and is watchable, it just should not ship.
        status = 'GATES FAILED'
    elif not have_video:
        status = 'NO OUTPUT'
    else:
        status = 'OK'

    lines = [
        f'iris-motion: {topic}',
        f'status     {status}',
        f'video_id   {video_id}',
        f'reported   {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}',
        '',
    ]

    if error is not None:
        lines += _section('ERROR', _error_lines(error))

    lines += _section('VIDEO', video_lines)
    lines += _section('FFPROBE', _probe_lines(probe, plan))
    lines += _section('GATES (check.py)',
                      ['  ' + ln for ln in gates.splitlines()] if gates else None)
    lines += _section('POST', _post_lines(plan))
    lines += _section('COST', _cost_lines(plan))

    timings = _timing_lines(plan)
    if timings:
        lines += _section('TIMINGS', timings)

    if plan:
        lines += _section('PLAN', [
            f'  {k:<22} {plan[k]}' for k in
            ('title', 'fps', 'frames', 'subsamples', 'shards', 'authored_by',
             'created_at')
            if k in plan
        ])

    body = '\n'.join(lines)
    logger.info('notify %s status=%s have_video=%s', video_id, status, have_video)

    subject = f'iris-motion: {str(topic)[:70]} - {status}'
    try:
        resp = ses.send_email(
            Source=MAIL_FROM,
            Destination={'ToAddresses': [MAIL_TO]},
            Message={
                'Subject': {'Data': subject[:200], 'Charset': 'UTF-8'},
                'Body': {'Text': {'Data': body, 'Charset': 'UTF-8'}},
            },
        )
    except Exception as e:  # noqa: BLE001 - the run's outcome does not hinge on the email
        logger.exception('SES send_email failed: %s', e)
        logger.info('undelivered report follows:\n%s', body)
        return {'sent': False, 'status': status, 'video_id': video_id,
                'error': f'{type(e).__name__}: {e}'}

    return {'sent': True, 'status': status, 'video_id': video_id,
            'message_id': resp.get('MessageId')}
