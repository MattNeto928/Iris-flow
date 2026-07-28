"""
Per-platform post copy — ONE Opus 5 call, one block-delimited response.

This replaces postprocess._caption_claude, which produced {title, caption,
tiktok_title} and let Metricool paste the same caption onto four networks that
reward completely different things. It now writes each network's copy against
that network's own mechanics (see PLATFORM PLAYBOOK in the prompt), plus the
carousel/story/image copy the companion formats need.

NOT JSON. Deliberately, and this is the second time this codebase has arrived
at that conclusion the expensive way:
  - prep.py moved authoring off JSON after two failures at column ~2100 and
    ~30500 (`Expecting ',' delimiter`).
  - postprocess's caption call TRUNCATED mid-JSON at max_tokens=2000, the prose
    fallback treated the broken blob as the caption, and a post reading
    '{"title": "Why ice floats...' went to four real accounts. It was deleted 13
    minutes before publication.
This payload is ~4x larger than the one that broke, carries prose with quotes
and apostrophes in every field, and is assembled by a model that cannot see the
escaping rules. Block delimiters have no escaping, no nesting, and no way to be
"almost valid": a truncated response loses its LAST section and every earlier
one still parses.

Cost: ~1.5k in / ~1.4k out on Opus 5 = roughly $0.04 a run.
"""

import os
import re
import time

from common import logger

CLAUDE_MODEL = 'claude-opus-5'
PRICE = {'in': 5.0 / 1e6, 'out': 25.0 / 1e6}

# Thinking is disabled below, so the whole budget is output. The full bundle
# measures ~1.4k tokens; 6000 is >4x headroom. The last thing this file wants is
# to re-learn the truncation lesson in its own docstring.
MAX_TOKENS = 6000

# Platform hard limits. Enforced HERE rather than trusted from the model, and
# again by the API. YouTube's 100 is the API's; 97 leaves room for the ellipsis
# metricool_client adds, so the title that gets logged is the title that posts.
LIMITS = {
    'yt_title': 97,
    'yt_description': 4800,   # API max 5000
    'yt_tags_total': 480,     # API max 500 chars across all tags
    'tiktok_title': 80,
    'tiktok_caption': 2100,
    'ig_caption': 2100,       # API max 2200
    'fb_caption': 2000,
    'alt_text': 900,          # API max 1000
    'slide_title': 60,
    'slide_body': 190,
    'story_text': 90,
}

# YouTube category for every piece this pipeline makes. From
# GET /v2/scheduler/catalogs/youtube/categories — EDUCATION is the other
# defensible key, but SCIENCE_TECHNOLOGY is the narrower shelf and YouTube's
# topic clustering rewards the narrower one.
YOUTUBE_CATEGORY = 'SCIENCE_TECHNOLOGY'

# The section names the model must emit, in order. Order matters only for
# truncation behaviour: the cheapest-to-lose sections are last, so a response
# that runs out of budget loses the still-image caption before it loses the
# Instagram one.
SECTIONS = [
    'YT_TITLE', 'YT_DESCRIPTION', 'YT_TAGS',
    'IG_CAPTION', 'IG_HASHTAGS',
    'TIKTOK_TITLE', 'TIKTOK_CAPTION',
    'FB_CAPTION',
    'ALT_TEXT', 'AUDIO_QUERY',
    'SLIDES', 'STORY_TEXT', 'IMAGE_CAPTION',
]

# Sections without which the RUN fails. Everything else degrades a format.
REQUIRED = {'YT_TITLE', 'IG_CAPTION', 'TIKTOK_TITLE'}

PROMPT = """You are writing every piece of post copy for one short vertical
science video. It goes out as an Instagram Reel, a TikTok, a YouTube Short and a
Facebook Reel, plus an Instagram carousel, a story and a single still image cut
from the same footage.

TOPIC:
{topic}

NARRATION (the complete spoken script, verbatim — the source of truth for what
this video actually says):
{narration}

VIDEO LENGTH: {duration}s

Do not promise the viewer anything the narration does not deliver, and do not
describe visuals you cannot see.

THIS ACCOUNT'S ACTUAL AUDIENCE, measured, not assumed:
- The single largest country is INDIA, ahead of the US. Then Germany, the UK,
  Canada, Iran, Brazil. It is a global audience, not a US one.
- 91% male, and the biggest age bucket is 25-34.
- So: no US-centric idioms, no American sports metaphors, no "your high school
  physics teacher" framing. Give SI units first; if you use an imperial unit at
  all, put it in brackets after. Assume a numerate adult who did not
  necessarily go to school in the United States.

WRITE LIKE A SHARP HUMAN, NOT LIKE AN AI.

HARD RULES (violating any one makes the post unusable):
- NO em dashes. NO en dashes. Use commas, periods, or a plain hyphen in
  compounds like "well-known".
- NO "dive into", "fascinating", "let's explore", "uncover", "unpack", "delve",
  "journey", "buckle up", "mind-blowing", "wild", "game-changer".
- NO "did you know" / "ever wondered" openers.
- NO meta references to the video ("in this video", "today we look at").
- NO mention of "Iris Flow", "AI", or any tool or brand name.
- NO ellipses. NO emojis anywhere except where a section explicitly allows one.

PLATFORM PLAYBOOK. These are different products. Do not write one caption four
times — the whole point of this call is that each one is built for its own feed.

* YOUTUBE is a SEARCH engine. The title is a query someone types. Front-load the
  concrete noun, no cleverness, no leading "Why" if a keyword can go first.
  The description's first two lines are the only ones shown before "more", so
  the hook goes there; the rest can carry a fuller explanation, 2-4 sentences.
  YT_TAGS are SEARCH KEYWORDS, not hashtags and not a topic list: singular and
  plural forms, the phenomenon's proper name, the field it sits in, the common
  misconception someone would search instead. No "#".

* INSTAGRAM shows only the first 125 characters before "more", so the entire
  hook has to land inside them. Keep the caption itself tight and put the bulk
  of the hashtags in IG_HASHTAGS, which is posted as the FIRST COMMENT and keeps
  the caption clean. In-caption hashtags: two at most, and only if they read as
  words in the sentence.

* TIKTOK overlays TIKTOK_TITLE on the video itself, so it must work as a
  spoken-aloud challenge, not a label. State the counterintuitive claim flat, or
  ask the question the video answers. One emoji is allowed at the very end,
  never mid-sentence. The caption is separate and carries the hashtags; TikTok's
  hashtags feed its content graph, so they should name the SUBJECT, not the
  format.

* FACEBOOK has the oldest and least specialist audience of the four and hashtags
  do almost nothing there. Write it as plain prose with slightly more context
  than Instagram gets, because a Facebook viewer is less likely to already know
  the field. No hashtags at all.

OUTPUT FORMAT. Emit each section below exactly once, in this order, each opened
by its marker alone on its own line. No JSON, no markdown fences, no commentary
before the first marker or after the last. Content is plain text and may contain
quotes and apostrophes freely.

===YT_TITLE===
The YouTube title. Under 90 characters. Keyword first.
===YT_DESCRIPTION===
2-4 sentences. Hook in the first line. Then a blank line, then exactly 3
hashtags. (More than 15 hashtags makes YouTube ignore all of them; 3 is the
number that shows above the title.)
===YT_TAGS===
8-14 search keywords, comma separated, no "#", no quotes.
===IG_CAPTION===
1-2 sentences, under 400 total. The FIRST SENTENCE must land complete inside 120
characters, because Instagram truncates at 125 and a hook cut mid-clause is a
hook that did not happen. At most 2 inline hashtags.
===IG_HASHTAGS===
8-12 hashtags on one line, space separated, most specific first, 2-3 broad ones
last. These post as the first comment.
===TIKTOK_TITLE===
Under 80 characters. The claim or the question, flat.
===TIKTOK_CAPTION===
1-2 sentences, then a blank line, then 4-6 subject hashtags.
===FB_CAPTION===
2-3 sentences of plain prose. No hashtags.
===ALT_TEXT===
One sentence describing what is on screen, for a blind viewer.
YOU CANNOT SEE THIS VIDEO. Describe only what the narration guarantees is being
shown, in terms of shapes, structure and motion. Do NOT state colours, materials
or lighting: a first draft of this prompt produced "red and white water
molecules" for a video whose molecules are blue, and a confidently wrong alt
text is worse for a blind viewer than a general one.
===AUDIO_QUERY===
Two or three words naming the MOOD of a background music track that would suit
this piece, for a music catalogue search. Examples: "ambient tension",
"curious minimal", "slow orchestral wonder". Words only, no punctuation.
===SLIDES===
Exactly 6 lines, one per carousel slide, each formatted as:
  Slide title | slide body
Slide 1 is the hook and must work with no context at all. Slides 2-5 build the
argument, one idea each, and at least one of them must carry a NUMBER. Slide 6
lands the payoff. Title under 60 characters, body under 190. This deck is read
by someone who will never press play, so it has to stand alone.
===STORY_TEXT===
One line, under 90 characters, that goes over a still from the video to make
someone tap through. No call to action about "linking in bio".
===IMAGE_CAPTION===
1-2 sentences for a single still image post, plus a blank line and 4-6 hashtags.
It must make sense WITHOUT the video, because it is posted on its own."""


def _clean(text: str) -> str:
    """Strip the punctuation the prompt bans, in case it slips through."""
    return (text.replace('—', ', ')
                .replace('–', '-')
                .replace('...', '.')
                .replace('…', '.')
                .strip())


def parse_blocks(raw: str) -> dict:
    """
    Split a ===NAME=== delimited response into {name: body}.

    Tolerant by construction, because this is the whole reason the format was
    chosen over JSON:
      - Unknown section names are kept, not an error (a model that invents
        ===NOTES=== has not broken the parse for everything else).
      - A truncated response loses only its final section.
      - Leading prose before the first marker is discarded rather than fatal.
    """
    out = {}
    # Markers must own their line, so a literal "===" inside prose cannot split
    # a section. Name is restricted to the shape the prompt asks for.
    parts = re.split(r'^={2,}\s*([A-Z][A-Z0-9_]*)\s*={2,}\s*$', raw, flags=re.M)
    # re.split with one group yields [pre, name1, body1, name2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        name = parts[i].strip().upper()
        body = parts[i + 1].strip()
        if body:
            out[name] = body
    return out


def _hashtags(text: str, limit: int) -> list:
    """Pull '#tag' tokens out of a blob, deduped, order preserved, capped."""
    seen, tags = set(), []
    for tag in re.findall(r'#[A-Za-z0-9_]+', text or ''):
        low = tag.lower()
        if low in seen:
            continue
        seen.add(low)
        tags.append(tag)
        if len(tags) >= limit:
            break
    return tags


def _parse_slides(body: str) -> list:
    """
    'Title | body' per line -> [{title, body}].

    Lines without a pipe are kept as a body-only slide rather than dropped: a
    slide with no title still renders, and losing one silently would show up as
    a 5-slide carousel nobody ordered.
    """
    slides = []
    for line in (body or '').splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip a leading "1." / "-" / "Slide 3:" the model may have added.
        line = re.sub(r'^(?:slide\s*)?\d+\s*[.):]\s*', '', line, flags=re.I)
        line = re.sub(r'^[-*]\s*', '', line)
        if '|' in line:
            title, _, text = line.partition('|')
        else:
            title, text = '', line
        title = _clean(title)[:LIMITS['slide_title']]
        text = _clean(text)[:LIMITS['slide_body']]
        if title or text:
            slides.append({'title': title, 'body': text})
    return slides


def _tags_csv(body: str) -> list:
    """YT_TAGS -> a list capped at YouTube's 500-char total budget."""
    raw = [t.strip().lstrip('#') for t in re.split(r'[,\n]', body or '')]
    tags, total = [], 0
    for t in raw:
        t = _clean(t)
        if not t or len(t) > 60:
            continue
        # +1 for the separator YouTube counts between tags.
        if total + len(t) + 1 > LIMITS['yt_tags_total']:
            break
        tags.append(t)
        total += len(t) + 1
    return tags


def generate(topic: str, narration: str, duration_s: float) -> tuple:
    """
    One Opus 5 call -> (bundle, usd).

    Raises only when a REQUIRED section is missing. Every optional section that
    fails to parse degrades exactly one format: no SLIDES means no carousel,
    no STORY_TEXT means no story. A run never dies because the still-image
    caption did not come back.
    """
    import anthropic

    t0 = time.time()
    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        # DISABLED against the SDK default, same as prep.py and for the same
        # measured reason: with thinking adaptive on Opus 5 this account has
        # twice seen the model spend an ENTIRE 32k budget inside one thinking
        # block and return stop_reason=max_tokens with zero text. Opus 5 rejects
        # budget_tokens, so off is the only cap there is, and post copy needs
        # none of it.
        thinking={'type': 'disabled'},
        messages=[{'role': 'user', 'content': PROMPT.format(
            topic=topic, narration=narration, duration=int(duration_s or 0))}],
    )

    raw = ''.join(b.text for b in msg.content
                  if getattr(b, 'type', None) == 'text').strip()
    usage = msg.usage.model_dump() if hasattr(msg.usage, 'model_dump') else dict(msg.usage)
    cost = (usage.get('input_tokens', 0) * PRICE['in']
            + usage.get('output_tokens', 0) * PRICE['out'])
    logger.info('copy: stop=%s out=%s text=%d chars $%.4f in %.1fs',
                msg.stop_reason, usage.get('output_tokens'), len(raw), cost,
                time.time() - t0)

    if not raw:
        raise RuntimeError(
            f'copy call returned no text (stop_reason={msg.stop_reason}, '
            f'output_tokens={usage.get("output_tokens")})')

    blocks = parse_blocks(raw)
    missing = REQUIRED - set(blocks)
    if missing:
        # No prose fallback here, on purpose. postprocess used to have one, it
        # could not tell "answered in prose" from "answered in broken JSON", and
        # that is exactly how a raw blob reached four accounts. If the required
        # sections are not there, the response is not usable — say so and let
        # the run fail loudly into the notify email.
        raise RuntimeError(
            f'copy response is missing required section(s) {sorted(missing)}; '
            f'got {sorted(blocks)} from {len(raw)} chars '
            f'(stop_reason={msg.stop_reason})')
    if len(blocks) < len(SECTIONS):
        logger.warning('copy: %d/%d sections parsed, missing %s — the formats '
                       'that need them will be skipped',
                       len(blocks), len(SECTIONS),
                       sorted(set(SECTIONS) - set(blocks)))

    def take(name, limit_key=None):
        text = _clean(blocks.get(name, ''))
        return text[:LIMITS[limit_key]] if limit_key else text

    ig_caption = take('IG_CAPTION', 'ig_caption')
    slides = _parse_slides(blocks.get('SLIDES', ''))

    bundle = {
        'youtube': {
            'title': take('YT_TITLE', 'yt_title'),
            'description': take('YT_DESCRIPTION', 'yt_description'),
            'tags': _tags_csv(blocks.get('YT_TAGS', '')),
            'category': YOUTUBE_CATEGORY,
        },
        'instagram': {
            'caption': ig_caption,
            # First comment. Falls back to the caption's own tags so the field
            # is never empty when the model skipped the section.
            'hashtags': (_hashtags(blocks.get('IG_HASHTAGS', ''), 12)
                         or _hashtags(ig_caption, 8)),
        },
        'tiktok': {
            'title': take('TIKTOK_TITLE', 'tiktok_title'),
            'caption': take('TIKTOK_CAPTION', 'tiktok_caption') or ig_caption,
        },
        'facebook': {
            'caption': take('FB_CAPTION', 'fb_caption') or ig_caption,
        },
        'alt_text': take('ALT_TEXT', 'alt_text'),
        'audio_query': take('AUDIO_QUERY')[:60],
        'slides': slides,
        'story_text': take('STORY_TEXT', 'story_text'),
        'image_caption': take('IMAGE_CAPTION', 'ig_caption') or ig_caption,
    }

    logger.info(
        "copy: yt_title=%r tags=%d ig_caption=%d chars ig_tags=%d "
        "tiktok_title=%r slides=%d audio_query=%r",
        bundle['youtube']['title'], len(bundle['youtube']['tags']),
        len(ig_caption), len(bundle['instagram']['hashtags']),
        bundle['tiktok']['title'], len(slides), bundle['audio_query'])
    return bundle, cost
