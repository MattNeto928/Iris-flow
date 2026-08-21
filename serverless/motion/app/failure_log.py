"""
Best-effort failure corpus in DynamoDB, for curating the prompts against real data.

WHY. The repair loop's failures were only ever visible in CloudWatch, on a 7-day
retention that expired before anyone looked — the 2026-08-02..08-10 prep failures
were diagnosed on 08-20 against log groups that read `storedBytes 0`, and the
root cause was permanently unrecoverable. Worse, the interesting signal is
LONGITUDINAL: "does adding a camera-target rule to REPAIR_SYSTEM reduce
EDIT_SYNTAX_ERROR next month" is not a question CloudWatch can answer at all.
So failures are written to a table that outlives them, keyed so a class can be
read back in time order.

THE ONE HARD RULE: this must never break a run. A pipeline that dies because its
telemetry failed is worse than a pipeline with no telemetry. Every path here
swallows its exception and returns False. `record()` no-ops entirely when
FAILURE_TABLE is unset, which is what makes local runs and tests silent.

Failure classes currently written (keep this list honest as it grows):
  EDIT_SYNTAX_ERROR    a repair edit list left piece.html unparseable
  PROBE_RENDER_FAILED  the repaired piece threw at render time
  EDIT_APPLY_FAILED    anchors did not apply at all (invented or overlapping)
  ASSESSMENT_MISSING   the model returned edits with no ASSESSMENT line
  GATE_FAILED          preflight gates failed on a cycle
  AUTHORING_FAILED     an authoring attempt did not produce a usable piece
"""

import decimal
import json
import os
import time
from datetime import datetime, timezone

from common import logger as log

TABLE = os.environ.get("FAILURE_TABLE", "").strip()

# Field caps. A gate dump or a page-error trace can be tens of kilobytes and the
# DynamoDB item limit is 400 KB; nothing here needs more than the head of the
# message to be useful for curation.
_MAX_FIELD = 4000
_MAX_ITEM_FIELDS = 24

_table = None


def _get_table():
    global _table
    if _table is not None:
        return _table
    if not TABLE:
        return None
    try:
        import boto3
        _table = boto3.resource("dynamodb").Table(TABLE)
        return _table
    except Exception as e:  # noqa: BLE001 - telemetry must never be fatal
        log.warning("failure_log: cannot reach table %s (%s) — not recording",
                    TABLE, type(e).__name__)
        return None


def _clip(v):
    """Coerce to something DynamoDB accepts, truncating long text."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        # DynamoDB has no float type; Decimal via str avoids binary float noise.
        return decimal.Decimal(str(round(v, 6)))
    if isinstance(v, int):
        return v
    if isinstance(v, (list, tuple)):
        return [_clip(x) for x in v][:64]
    if isinstance(v, dict):
        return {str(k): _clip(x) for k, x in list(v.items())[:32]}
    s = str(v)
    return s[:_MAX_FIELD] + f"... [truncated, {len(s)} chars]" \
        if len(s) > _MAX_FIELD else s


def record(failure_class, *, video_id, cycle=None, error=None, **extra):
    """
    Write one failure. Returns True if it was stored, False otherwise.

    Never raises. `failure_class` partitions the table so a whole class can be
    read back chronologically, which is the query prompt curation actually needs.
    """
    t = _get_table()
    if t is None:
        return False
    try:
        now = datetime.now(timezone.utc)
        # created_at leads the sort key so a class reads back in time order;
        # video_id and cycle disambiguate two failures in the same millisecond.
        sk = f"{now.isoformat()}#{video_id}#{'' if cycle is None else cycle}"
        item = {
            "failure_class": str(failure_class),
            "occurred_at_video_cycle": sk,
            "video_id": str(video_id),
            "created_at": now.isoformat(),
            "created_date": now.strftime("%Y-%m-%d"),
            "epoch_ms": int(time.time() * 1000),
        }
        if cycle is not None:
            item["cycle"] = int(cycle)
        if error is not None:
            item["error"] = _clip(error)
        for k, v in list(extra.items())[:_MAX_ITEM_FIELDS]:
            cv = _clip(v)
            if cv is not None and cv != "":
                item[k] = cv
        t.put_item(Item=item)
        log.info("failure_log: recorded %s for %s cycle=%s",
                 failure_class, video_id, cycle)
        return True
    except Exception as e:  # noqa: BLE001 - telemetry must never be fatal
        log.warning("failure_log: could not record %s for %s (%s: %s)",
                    failure_class, video_id, type(e).__name__, e)
        return False


def summarise(days=30):
    """
    Counts per failure class over the last `days`, newest classes first.

    A convenience for reading the corpus back from a shell without writing a
    query each time:  python3 -c "import failure_log; print(failure_log.summarise())"
    Uses a scan, which is fine at this volume — the pipeline writes single-digit
    items a day — and returns {} on any failure rather than raising.
    """
    t = _get_table()
    if t is None:
        return {}
    try:
        cutoff = int((time.time() - days * 86400) * 1000)
        counts, kw = {}, {}
        while True:
            page = t.scan(**kw)
            for it in page.get("Items", []):
                if int(it.get("epoch_ms", 0)) >= cutoff:
                    counts[it.get("failure_class", "?")] = \
                        counts.get(it.get("failure_class", "?"), 0) + 1
            if "LastEvaluatedKey" not in page:
                break
            kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    except Exception as e:  # noqa: BLE001
        log.warning("failure_log: summarise failed (%s)", e)
        return {}


__all__ = ["record", "summarise", "TABLE"]
