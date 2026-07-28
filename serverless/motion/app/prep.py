"""
JOB_TYPE=prep — topic in, a validated renderable scene + narration track out.

The expensive thing in this pipeline is not compute, it is the model call. A
sharded 1440-frame render costs about $0.15; one Opus 5 authoring call costs
about $0.85. So this job makes **one** call, with the bulky, unchanging part of
the prompt marked for caching (cache reads bill at 0.1x), and it validates the
result by actually rendering three frames before 30 minutes of shard time is
committed to it.

Authoring is expressed as a list of {find, replace} edits against the template,
not as a whole file. Emitting the full 45 KB piece.html would be ~12k output
tokens of harness the model would be copying verbatim, and every copy is a
chance to corrupt it. Edits are cheap, and `assert find in s` fails loudly.

Model order: Claude (primary) -> Gemini (fallback) -> bundled seed piece. The
seed guarantees the pipeline always produces a video; the run records which
path it took in plan.json['authored_by'] so a silent downgrade is visible.
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (logger as log, page_url_path, render_env, save_plan,
                    upload_bytes, upload_file, workdir)
from narrate import beats_from_durations

APP = Path(os.path.dirname(os.path.abspath(__file__)))

FPS = 30                 # Iris-flow normalises segments to 1080x1920@30
# MEASURED on a g4dn.xlarge (Tesla T4) via ANGLE/Vulkan: 0.133 s/frame at ss12,
# 0.217 s/frame at ss24 -- against 14.2 s/frame for the same scene on Fargate's
# SwiftShader. 107x. That inverts the whole design:
#   - ss24 is now AFFORDABLE (a 1305-frame piece is 4.7 min), so quality goes up
#     rather than down; below ~12 the depth-of-field bokeh bands.
#   - Sharding stops being the lever. Render is ~3-5 min but an instance boot +
#     600 MB image pull is ~4.5 min, so more shards mostly buys more boots.
#     2 shards is the whole G-family on-demand quota (8 vCPU / 4 per instance)
#     and halves the render without paying for a third boot.
SUBSAMPLES = 24
# ONE shard. VERIFIED through common.render_env() on a T4: 0.185 s/frame at
# ss24, so all 1440 frames are 4.4 min on a single instance. A second shard
# would save 2.2 min of render and cost a whole extra ~4 min instance boot plus
# its idle tail -- instance-minutes, not frames, are what Batch bills on EC2.
SHARDS = 1
MAX_AUTHOR_ATTEMPTS = 3
# Hard ceiling. If authoring somehow spends more than this, stop and take the
# seed -- a video that costs more than the budget is worse than the fallback.
AUTHOR_COST_CEILING_USD = float(os.environ.get("AUTHOR_COST_CEILING_USD", "1.50"))

# Whether a total authoring failure may fall back to the bundled seed piece.
#
# TRUE by default, because that is what a manual run wants: the seed is a
# known-good gate-passing piece and it is how the infrastructure is exercised
# end to end without depending on a model.
#
# SCHEDULED runs set it false (see app/lambdas/orchestrator.py). Those runs post
# to the accounts unconditionally, and the seed is ONE fixed aurora piece -- so
# a fallback there would publish the same video again, under whatever topic came
# off the queue, and the only signal would be authored_by=seed buried in
# plan.json. Failing the run instead skips the slot and sends the failure email.
#
# Parsed as a negative list so a BLANK value means the default rather than
# false: a job definition that forgets to set it, or a local `docker run`, must
# behave like the manual case, not silently become fatal.
SEED_FALLBACK = os.environ.get("SEED_FALLBACK", "").strip().lower() \
    not in ("0", "false", "no", "off")

CLAUDE_MODEL = "claude-opus-5"
GEMINI_MODEL = "gemini-3.1-pro-preview"
# Opus 5 list price. Cache reads are 0.1x input, cache writes 1.25x.
PRICE = {"in": 5.0 / 1e6, "out": 25.0 / 1e6, "cache_read": 0.5 / 1e6,
         "cache_write": 6.25 / 1e6}

# The anchors the model edits against. These are the >>> AUTHOR <<< regions of
# piece_template.html. Quoted to the model verbatim so its `find` strings match.
ANCHORS = [
    ("BEATS", "const BEATS = ["),
    ("SCENE", "// ============================================================== >>> AUTHOR: SCENE"),
    ("CAMKEYS", "const CAMKEYS = ["),
    ("POSE", "  // ---- >>> AUTHOR: scene state. Everything written, never accumulated."),
    ("CAPTIONS", "  // ---- >>> AUTHOR: captions. play(frame, inStart, inEnd, outStart, outEnd)."),
]

SYSTEM = """You author short vertical explainer videos as real 3D scenes. The
scene is Three.js drawn frame-by-frame in headless Chrome; `pose(frame)` is a
PURE FUNCTION of frame — it re-derives all state every call, so no accumulation,
no Math.random, no Date.now. Motion blur and depth of field come from 12
sub-samples per frame, which is why purity is not optional.

You will be given a complete working template. You do NOT rewrite it. You return
a list of {find, replace} edits applied in order with `assert find in source`.
Keep `find` strings short but unique — an exact substring of the template.

EDITS ARE APPLIED IN ORDER TO THE EVOLVING DOCUMENT, and this is the single most
common way these fail:
- Two edits must NOT overlap. If edit 3 replaces a block, edit 6 cannot then
  anchor on text that was INSIDE that block — it no longer exists, and the whole
  attempt is rejected.
- Every `find` must still be present after all EARLIER edits have been applied.
- If you replace the SCENE block and remove an object the template's pose() uses
  (`hero`, `moteMesh`, `STARS`), you MUST also replace the pose() block in the
  same edit list, or the piece throws `ReferenceError: <name> is not defined` on
  frame 0.
- Each `find` must match EXACTLY ONCE in the whole document. If a short string
  appears twice, extend it until it is unique.

BUILD THE THING. This is the single biggest quality lever and the one most
often missed. The subject of the video must exist as REAL 3D GEOMETRY that the
camera moves around — not as a background gradient with captions on top.
- A piece about Earth's shadow builds the shadow CONE as geometry and flies
  along it. It does not draw a pink-to-blue vertical gradient and label it.
  That exact mistake produced 35 seconds of wallpaper on a real run.
- A piece about an ice crystal builds the hexagonal prism, with facets, and
  refracts a ray through it.
- A piece about a spider builds a jointed spider. A piece about a bee builds a
  bee from scaled spheres, a parametric wing and a translucent quad.
Assemble subjects from primitives — spheres, cylinders, lathes, tubes, extrudes,
BufferGeometry you generate — the way the template's hero is assembled. A scene
whose only geometry is a backdrop plane is a failed scene, however pretty the
gradient is.

EVERY BEAT NEEDS SOMETHING ON SCREEN, ALL THE WAY TO THE LAST FRAME.
- The final beat is the most commonly dead one: the narration ends, the captions
  have exited, and the last 10-15 seconds are an empty backdrop. Measured on a
  real run: 13 seconds of nothing. Give the closing beat a title card, a held
  hero shot, or a slow push — something.
- Check every beat in your BEATS table against your pose() and captions: if a
  beat drives no object and shows no caption, it is dead air. Delete the beat or
  fill it.
- A caption alone is not content. If the only thing changing on screen is text,
  the beat is a slide, not a shot.

CONTRAST. Aim for a dark scene with bright subjects. The gates measure the 1st
percentile of luma and expect low single digits; a full-frame pastel wash reads
as flat and washed out, and bloom has nothing to bite on. If the subject is
genuinely bright (a sky, a flame), keep something dark in frame for it to read
against.

Hard rules, each learned from a real failure:
- `new THREE.Color(r,g,b)` treats floats as ALREADY LINEAR. Use the template's
  `C(0xRRGGBB)` helper for every authored colour.
- `Matrix4.lookAt(eye,target)` sets +z to normalize(eye-target). To aim a
  +z-forward model along a tangent, pass lookAt(tangent, ZERO, UP).
- Bloom threshold near 0 hazes the frame milky. Leave the threshold alone; tune
  the per-beat `bloom` multiplier instead, and expect it to span 3x or more if
  the lit fraction swings by an order of magnitude.
- Put anything at infinity in `bgScene`, or depth of field renders it once per
  aperture sample and a starfield becomes clumps of dots.
- POINT FIELDS. makePointField's `size` is a WORLD-SPACE DIAMETER, and getting
  it wrong by 10x is the most repeated mistake in this pipeline -- twice now a
  scene has been ruined by dust the size of tennis balls. COMPUTE it, never
  guess:  px = size * (H/2) * (1/tan(fov/2)) / dist
  At H=1920 and fov=32 that is  size * 3348 / dist.  Aim for 1.5-3 px on screen.
  On a radius-900 shell that means size ~0.6, NOT 4. If a point field is meant
  to read as dust or stars it must be small enough to be texture, not objects.
- Use the existing helpers rather than rebuilding them: makePointField, makePanel,
  makeCard, makeAxis, makeGlow, makeScrim, makeCaption, makeAnchoredLabel.
  Every make* returns a controller with .set() and .mesh — never reach past it.
- A camera key may set cut:1 (10th element) to SNAP instead of interpolating.
  Use it between staging areas rather than flying the camera across the gap.
- The safe box is x 60-900, y 200-1560 of 1080x1920. It is NOT centred; compose
  on x 480.
- A single NaN in shading turns the WHOLE frame black, because the bloom mip
  chain spreads it. Guard any normalize() on a difference of two path points.

Return your answer in EXACTLY this format. The header is JSON; the EDITS are
NOT, because they carry JavaScript, and embedding multi-kilobyte code inside
JSON strings means escaping every quote, newline and backslash perfectly across
the whole payload. One slip discards everything — MEASURED: a 30,505-character
response was thrown away over a single delimiter.

HEADER
{"title": "short title card text",
 "narration": [{"id": "hook", "text": "one or two spoken sentences"}, ...]}

<<<<<<< FIND
the exact text to find, verbatim, newlines and all
=======
the replacement text
>>>>>>> END

<<<<<<< FIND
...
=======
...
>>>>>>> END

Repeat the FIND/REPLACE block once per edit. Write the code literally, with
real newlines and real quotes — nothing is escaped.

NARRATION — IT NEEDS A BEGINNING AND AN END.

The failure to avoid: starting in the middle of the mechanism and stopping when
the mechanism runs out. That reads as a fragment overheard halfway through, and
it is what the last two scripts did. Every piece follows this arc:

1. NAME THE THING (segment 1). Say what the viewer is looking at, in plain
   words, in the first three seconds. Not "at sunset, look east" — the viewer
   does not yet know what they are being shown or why. A viewer who cannot
   answer "what is this about?" after one sentence has already scrolled.
2. THE TURN (segment 2). The counterintuitive claim, stated flatly. "Lightning
   doesn't fall. It climbs." This is the reason to keep watching, and it is a
   promise you must then pay off.
3. THE MECHANISM (3-5 segments). One causal step each, in order, each one
   earning the next. No step may be skipped as obvious.
4. LAND IT (final segment). Close the loop opened in 1 and 2 — say what the
   viewer now understands that they did not 40 seconds ago, and NAME THE
   PHENOMENON again so it is memorable and searchable. A piece that just stops
   has no ending; a piece whose last line restates the turn does.

Write it so the first and last lines could stand alone as the whole idea.

LENGTH. BUDGET WORDS AT 3.2 WORDS/SECOND — MEASURED for this narrator at its
configured pace. A 45 s piece is about 145 words, a 60 s piece about 190. That
is roughly 18-22 words per segment: two or three real sentences.

If you have seen an older version of this instruction quoting 1.4 words/second
and a 60-word ceiling, IGNORE IT. That number was an artifact of a previous
voice that padded its output with silence, and writing to it produces a script
too thin to introduce its own subject or close it — which was the single most
common complaint about these pieces. You now have room for a real opening and a
real ending. Use it, but do not pad: sparse, declarative, Anglo-Saxon, every
sentence earning its place. The visual still carries the weight.

Narration carries the ARGUMENT. Captions carry numbers and labels — never write
a line that just reads a caption aloud, and never put a number in the narration
that is not already on screen.

Beat ids in BEATS must match narration ids exactly and in order. Leave `from`/`to`
as any integers; they are overwritten from the measured audio durations."""


def _read(p):
    return (APP / p).read_text()


def _price(usage, cached):
    """Dollars for one Anthropic call. usage is the SDK usage object as a dict."""
    return (usage.get("input_tokens", 0) * PRICE["in"]
            + usage.get("output_tokens", 0) * PRICE["out"]
            + usage.get("cache_read_input_tokens", 0) * PRICE["cache_read"]
            + usage.get("cache_creation_input_tokens", 0) * PRICE["cache_write"])


def _extract_json(text):
    """Models wrap JSON in prose or a fence more often than they should."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        i, j = text.find("{"), text.rfind("}")
        if i < 0 or j <= i:
            raise
        return json.loads(text[i:j + 1])


def _user_prompt(topic, seconds, previous_error=None):
    anchor_help = "\n".join(f"  {n}: {a!r}" for n, a in ANCHORS)
    p = (f"Topic: {topic}\n"
         f"Target duration: {seconds} seconds at {FPS} fps.\n\n"
         f"Anchors you will most likely edit (exact substrings of the template):\n"
         f"{anchor_help}\n\n"
         "Make it beautiful and make every number on screen defensible. One clear "
         "idea per beat. Prefer one dense well-composed scene over many thin ones.")
    if previous_error:
        # The single highest-value thing to feed a repair attempt is the actual
        # runtime error, not a description of it.
        p += ("\n\nYOUR PREVIOUS ATTEMPT FAILED. Fix it. The renderer reported:\n"
              f"{previous_error[:4000]}\n\n"
              "Return the COMPLETE corrected edit list against the ORIGINAL "
              "template, not a patch to your broken output.")
    return p


def author_claude(topic, seconds, template, previous_error=None):
    """
    One Opus 5 call. STREAMED, and with room for thinking.

    max_tokens is the budget for thinking AND output together. At 16000 the
    model spent the whole allowance reasoning and returned 200 OK with zero text
    blocks, which surfaced downstream as a bare JSONDecodeError on an empty
    string -- a 4-minute call, billed, that looked like malformed JSON.
    A full edit list is ~8-12k output tokens on its own, so the budget has to
    cover both. Streaming because a single non-streamed request this long risks
    the SDK's own request timeout.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=32000,
        # thinking DISABLED, deliberately, against the usual default.
        # MEASURED on this exact prompt: with adaptive thinking (and also with
        # `thinking` omitted, which still thinks on Opus 5) the model spent the
        # ENTIRE 32,000-token budget inside one thinking block and returned
        # stop_reason=max_tokens with ZERO text — a 7-minute call, billed at
        # $0.80, that produced nothing. Twice. Authoring a whole scene is
        # open-ended enough that the reasoning does not terminate on its own,
        # and Opus 5 rejects budget_tokens, so there is no way to cap it.
        # The probe-render + repair loop below is the substitute for internal
        # deliberation: it feeds the real renderer error back on attempt 2.
        thinking={"type": "disabled"},
        system=[
            {"type": "text", "text": SYSTEM},
            # The template is ~21k tokens and identical on every call in the
            # fleet, so it is the whole reason caching pays here. MEASURED:
            # first call writes 21,315 cache tokens for $0.134, every later call
            # reads them for $0.011 -- a 12x saving on the input side.
            {"type": "text", "text": "TEMPLATE:\n" + template,
             "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user",
                   "content": _user_prompt(topic, seconds, previous_error)}],
    ) as stream:
        r = stream.get_final_message()

    kinds = {}
    for b in r.content:
        kinds[b.type] = kinds.get(b.type, 0) + 1
    text = "".join(b.text for b in r.content if b.type == "text")
    usage = r.usage.model_dump() if hasattr(r.usage, "model_dump") else dict(r.usage)
    log.info("claude: stop=%s blocks=%s out=%s text=%d chars",
             r.stop_reason, kinds, usage.get("output_tokens"), len(text))
    if not text.strip():
        # Name the real cause instead of letting json.loads('') do it.
        raise RuntimeError(
            f"model returned no text (stop_reason={r.stop_reason}, blocks={kinds}, "
            f"output_tokens={usage.get('output_tokens')}) — "
            f"max_tokens likely exhausted by thinking")
    return _parse_authored(text), _price(usage, True), "claude"


def author_gemini(topic, seconds, template, previous_error=None):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GOOGLE_AI_API_KEY"])
    r = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=(SYSTEM + "\n\nTEMPLATE:\n" + template + "\n\n"
                  + _user_prompt(topic, seconds, previous_error)),
        config=types.GenerateContentConfig(
            response_mime_type="application/json", max_output_tokens=32000),
    )
    return _parse_authored(r.text), 0.0, "gemini"


def apply_edits(template, edits):
    """
    Apply {find, replace} in order, failing loudly on a stale anchor.

    `find` must be UNIQUE: a prefix match is how a previous run silently
    prepended a whole function to line 1 of the document and produced a
    ReferenceError a thousand lines from the cause.
    """
    s = template
    for i, e in enumerate(edits):
        find, repl = e["find"], e["replace"]
        n = s.count(find)
        if n == 0:
            # Distinguish "never existed" from "an earlier edit ate it" — the
            # second is by far the more common, and the model can only fix it if
            # the message says so.
            why = ("it was still in the ORIGINAL template, so an EARLIER edit in "
                   "this list replaced the region containing it — your edits "
                   "overlap"
                   if find in template else
                   "it is not in the template at all — you invented the anchor")
            raise ValueError(f"edit {i}: anchor not found. {why}. "
                             f"anchor was: {find[:200]!r}")
        if n > 1:
            raise ValueError(f"edit {i}: anchor matches {n} places, must be "
                             f"unique: {find[:120]!r}")
        s = s.replace(find, repl, 1)
    return s


def inject_timing(piece, fps, frames, beats):
    """Overwrite FPS / FRAMES / BEATS with values measured from the real audio."""
    piece = re.sub(r"const W = 1080, H = 1920, FPS = \d+;",
                   f"const W = 1080, H = 1920, FPS = {fps};", piece, count=1)
    piece = re.sub(r"const FRAMES = \d+;", f"const FRAMES = {frames};",
                   piece, count=1)
    rows = "\n".join(
        f"  {{ id: {b['id']!r}, from: {b['from']}, to: {b['to']}, "
        f"bloom: {b.get('bloom', 1.0)} }},"
        for b in beats)
    piece = re.sub(r"const BEATS = \[.*?\n\];",
                   "const BEATS = [\n" + rows + "\n];", piece, count=1, flags=re.S)
    return piece


REPAIR_SYSTEM = """You are reviewing a contact sheet from a 3D explainer video
you just authored, plus the numeric gates. Frames run left to right, top to
bottom, evenly spaced across the whole piece.

Judge it the way a viewer would, then return edits that fix what you find. Look
for these first, in this order — they are the failures that actually happen:

1. DEAD FRAMES. Tiles that are empty, or a backdrop with nothing on it. The tail
   is the usual offender. Any tile with no subject and no caption is dead air.
2. NO SUBJECT. If the piece is a background gradient with text over it, that is
   the failure mode to fix — build the thing the video is about as real
   geometry and stage the camera on it.
3. WASHED OUT. A flat pastel frame with no dark anywhere. The gates report the
   1st percentile of luma; low single digits is the target.
4. BLOWN OUT. Large white areas, or a clipped-pixel figure above ~2%.
5. UNREADABLE TYPE. Captions overlapping the subject, or too small to read at
   thumbnail size — which is how this will actually be watched.
6. MONOTONY. Six tiles that look identical mean six seconds where nothing
   happened.

Return your answer in EXACTLY this format. Not JSON — the replacement blocks
are JavaScript, and embedding them in JSON strings means escaping every quote,
newline and backslash correctly across thousands of characters. One slip
invalidates the whole payload.

ASSESSMENT: one or two sentences on what is actually wrong

<<<<<<< FIND
the exact text to find, verbatim, newlines and all
=======
the replacement text
>>>>>>> END

<<<<<<< FIND
...
=======
...
>>>>>>> END

Repeat the block per edit. Write the code literally, with real newlines. Emit no
blocks at all if there is nothing to fix.

The edits apply to the CURRENT piece.html, which is given to you below — not to
the original template. Same rules as before: each `find` must appear EXACTLY
ONCE, edits must not overlap, and anything you delete must not still be
referenced by pose().

If the sheet genuinely looks good, return {"assessment": "...", "edits": []}.
Do not invent work. A cosmetic tweak that risks a ReferenceError is worse than
leaving it alone."""


_EDIT_RE = re.compile(
    r"<<<<<<<+ *FIND\r?\n(.*?)\r?\n=======+\r?\n(.*?)\r?\n>>>>>>>+ *END",
    re.S)


def _parse_authored(text):
    """
    HEADER json + conflict-marker edits -> the same dict the JSON format gave.

    The header stays JSON because it is small, flat and has nothing to escape;
    the edits do not, for the reason in the prompt.
    """
    blocks = _parse_edit_blocks(text)
    m = re.search(r"HEADER\s*\n(\{.*?\})\s*(?:\n\s*<<<<<<<|\Z)", text, re.S)
    head = _extract_json(m.group(1)) if m else _extract_json(text)
    return {"title": head.get("title", ""),
            "narration": head.get("narration") or [],
            "edits": blocks["edits"]}


def _parse_edit_blocks(text):
    """
    Conflict-marker edits -> {"assessment": str, "edits": [{find, replace}]}.

    NOT JSON, on purpose. The first real production use of the repair pass died
    on `Expecting ',' delimiter: line 1 column 2167` — the model had to escape
    every quote, newline and backslash of a multi-kilobyte JavaScript block into
    a JSON string, and one slip discards the entire response. There is nothing
    to escape in this format.
    """
    m = re.search(r"ASSESSMENT:\s*(.+?)(?:\n\s*\n|<<<<<<<|$)", text, re.S)
    edits = [{"find": f, "replace": r} for f, r in _EDIT_RE.findall(text)]
    return {"assessment": (m.group(1).strip() if m else "").strip(),
            "edits": edits}


def _contact_sheet(frames_dir, dest, cols=6, rows=4):
    """
    Tile the preflight frames into one PNG for the model to look at.

    Scaled so the long edge lands near 1500 px: past that the image costs more
    tokens without the model seeing more, and these tiles only need to answer
    "is anything on screen" and "does it read", not "is the bokeh right".
    """
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-pattern_type", "glob",
         "-i", str(Path(frames_dir) / "*.png"),
         "-vf", f"scale=240:-1,tile={cols}x{rows}:padding=4:color=0x202020",
         "-frames:v", "1", str(dest)],
        check=True)
    return dest


def preflight_repair(piece_path, wd, plan_frames, fps, attempt_cost):
    """
    Render a strided preflight, gate it, LOOK at it, and let the model fix it.

    This is the loop a human runs with the motion-video skill -- render a
    handful of frames, put them in a contact sheet, look, batch the fixes -- and
    it is the step whose absence produced the two bad pieces so far. Both were
    mechanically perfect: valid MP4, right length, right codec, and 13 seconds
    of empty frame that no numeric gate can see.

    Cheap on purpose: ~24 frames at ss2 is about a minute on Fargate, against
    ~$0.30 for the repair call and a full render that would otherwise be spent
    on a scene nobody would watch.

    Returns (repaired: bool, cost_usd: float). Never raises -- a failed repair
    leaves the original piece in place, because the original at least renders.
    """
    import anthropic
    import base64

    # .resolve(): render.mjs resolves a RELATIVE --out against its own ROOT, not
    # against cwd, so a relative workdir silently writes the frames somewhere
    # else and the glob below finds nothing. Same trap that made probe_render
    # always report failure.
    frames = (Path(wd) / "preflight").resolve()
    sheet = (Path(wd) / "preflight_sheet.png").resolve()
    stride = max(1, plan_frames // 24)
    r = subprocess.run(
        ["node", str(APP / "render.mjs"), "--page", page_url_path(piece_path),
         "--out", str(frames), "--stride", str(stride), "--ss", "2"],
        cwd=wd, capture_output=True, text=True, timeout=1800, env=render_env())
    n = len(list(frames.glob("*.png")))
    if r.returncode != 0 or n < 8:
        log.warning("preflight render produced %d frames — skipping repair", n)
        return False, 0.0

    g = subprocess.run(
        [sys.executable, str(APP / "check.py"), "--frames", str(frames),
         "--fps", str(fps)],
        capture_output=True, text=True)
    gates = (g.stdout + g.stderr).strip()
    log.info("preflight gates:\n%s", gates)

    try:
        _contact_sheet(frames, sheet)
        png = base64.standard_b64encode(sheet.read_bytes()).decode()
    except Exception as e:                                  # noqa: BLE001
        log.warning("could not build contact sheet: %s", e)
        return False, 0.0

    piece = piece_path.read_text()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    try:
        with client.messages.stream(
            # 24000, not 16000: MEASURED, a real repair emitted 16,679 output
            # tokens (13 edits carrying whole replacement blocks) and 16000 cut
            # the JSON mid-string, which surfaces as an unparseable response
            # rather than as "too small".
            model=CLAUDE_MODEL, max_tokens=24000,
            thinking={"type": "disabled"},
            system=REPAIR_SYSTEM,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/png",
                                             "data": png}},
                {"type": "text", "text":
                    f"{n} frames, evenly spaced across the whole piece.\n\n"
                    f"GATES:\n{gates}\n\nCURRENT piece.html:\n{piece}"},
            ]}],
        ) as stream:
            resp = stream.get_final_message()
        text = "".join(b.text for b in resp.content if b.type == "text")
        usage = (resp.usage.model_dump() if hasattr(resp.usage, "model_dump")
                 else dict(resp.usage))
        cost = _price(usage, False)
        spec = _parse_edit_blocks(text)
    except Exception as e:                                  # noqa: BLE001
        log.warning("repair call failed: %s", e)
        return False, 0.0

    log.info("repair assessment: %s", spec.get("assessment", "")[:400])
    edits = spec.get("edits") or []
    if not edits:
        log.info("model reports nothing to fix")
        return False, cost

    # Apply to a COPY. If the repaired piece does not render, the original is
    # still on disk and still works -- a repair must never be able to make
    # things worse than not repairing.
    backup = piece_path.read_text()
    try:
        piece_path.write_text(apply_edits(backup, edits))
    except Exception as e:                                  # noqa: BLE001
        log.warning("repair edits did not apply (%s) — keeping original", e)
        piece_path.write_text(backup)
        return False, cost

    ok, out = probe_render(piece_path, wd)
    if not ok:
        log.warning("repaired piece failed its probe render — reverting:\n%s",
                    out[:800])
        piece_path.write_text(backup)
        return False, cost
    log.info("repair applied: %d edits, $%.3f", len(edits), cost)
    return True, cost


def probe_render(piece_path, wd, ss=2):
    """
    Render three frames to prove the scene actually runs.

    This is the cheapest possible insurance: ~3 seconds against ~30 minutes of
    shard time spent rendering a scene that throws on frame 0. render.mjs exits
    non-zero and prints the page error, which is exactly what a repair attempt
    needs to be fed.
    """
    # BOTH paths must be computed the way render.mjs computes them, not the way
    # a shell would. render.mjs resolves --page AND a relative --out against
    # ROOT = dirname(render.mjs)/.. -- which is "/" in this image -- never
    # against cwd. Passing "piece.html" made the server look for /piece.html and
    # 404; passing "probe" wrote frames to /probe while this function globbed
    # /work/<id>/probe. Either one alone makes probe_render ALWAYS report
    # failure, which burns every authoring retry and then raises after the seed
    # fallback -- prep could never succeed.
    out = Path(wd) / "probe"
    r = subprocess.run(
        ["node", str(APP / "render.mjs"),
         "--page", page_url_path(piece_path),
         "--out", str(out), "--only", "0,1,2", "--ss", str(ss)],
        cwd=wd, capture_output=True, text=True, timeout=900, env=render_env())
    ok = r.returncode == 0 and len(list(out.glob("*.png"))) == 3
    return ok, (r.stdout + "\n" + r.stderr).strip()


def _tts_one(text, out_path, seg_id):
    from tts import generate_voiceover
    p, d = generate_voiceover(text, out_path)
    log.info("  tts %-12s %5.2fs", seg_id, d)
    return p, d


def _tts_all(narration, wd):
    """
    Synthesise every segment, 4 at a time.

    MEASURED on ElevenLabs: ~1.2 s per segment, so 8 segments is about ten
    seconds, against the five minutes the previous engine took (60-203 s each,
    a 504 on the first call being routine). 4 workers rather than 2: the old cap
    existed because that model silently throttled above 2, returning empty audio
    parts. That constraint is gone.
    """
    from concurrent.futures import ThreadPoolExecutor
    jobs = [(i, s) for i, s in enumerate(narration)]
    out = [None] * len(jobs)
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(_tts_one, s["text"], Path(wd) / f"vo_{i:02d}.wav",
                          s["id"]): i for i, s in jobs}
        for f in futs:
            pass
        for f, i in futs.items():
            out[i] = f.result()
    return [p for p, _ in out], [d for _, d in out]


def synthesise(narration, wd):
    """Gemini TTS per segment. Returns durations in seconds, in order."""
    from tts import mix_track
    paths, durs = _tts_all(narration, wd)
    # lead/gap MUST match beats_from_durations below or picture drifts off voice.
    mix_track(paths, Path(wd) / "narration.wav", lead=0.4, gap=0.25)
    return durs


def run():
    video_id = os.environ["VIDEO_ID"]
    topic = os.environ.get("TOPIC") or "why the sky is blue"
    seconds = int(os.environ.get("TARGET_DURATION", "60"))
    wd = workdir(video_id)
    t0 = time.time()

    template = _read("piece_template.html")
    (Path(wd) / "piece.html").write_text(template)

    spec, cost, source, err = None, 0.0, "seed", None
    providers = []
    # FORCE_SEED skips authoring entirely. This is how the infrastructure is
    # tested independently of the models -- a render/stitch/notify regression and
    # a bad scene look identical from the outside otherwise, and the seed is a
    # known-good 60 s piece that has already passed the gates.
    force_seed = os.environ.get("FORCE_SEED", "").lower() in ("1", "true", "yes")
    if not force_seed:
        if os.environ.get("ANTHROPIC_API_KEY"):
            providers.append(author_claude)
        if os.environ.get("GOOGLE_AI_API_KEY"):
            providers.append(author_gemini)
    else:
        log.info("FORCE_SEED set — skipping model authoring")

    # One flat attempt list, consumed once. Claude gets the first two tries
    # (the second is a repair fed the actual renderer error); Gemini is the
    # third, so a provider outage or an empty credit balance still yields a
    # video without doubling the spend.
    attempts = ([providers[0]] * min(2, MAX_AUTHOR_ATTEMPTS) + providers[1:]
                )[:MAX_AUTHOR_ATTEMPTS] if providers else []
    for i, fn in enumerate(attempts):
        if cost > AUTHOR_COST_CEILING_USD:
            log.error("author spend $%.2f exceeded the $%.2f ceiling — stopping",
                      cost, AUTHOR_COST_CEILING_USD)
            break
        try:
            log.info("authoring attempt %d/%d via %s", i + 1, len(attempts),
                     fn.__name__)
            cand, c, src = fn(topic, seconds, template, err)
            cost += c
            piece = apply_edits(template, cand["edits"])
            (Path(wd) / "piece.html").write_text(piece)
            ok, out = probe_render(Path(wd) / "piece.html", wd)
            if ok:
                spec, source = cand, src
                log.info("scene validated by probe render (%s)", src)
                break
            err = out
            log.warning("probe render failed:\n%s", out[:1500])
        except Exception as e:                # noqa: BLE001 - any failure retries
            err = f"{type(e).__name__}: {e}"
            log.warning("author attempt failed: %s", err)

    if not spec:
        # FORCE_SEED is checked first and wins: it is an explicit request for the
        # seed, not a downgrade, so SEED_FALLBACK has no say over it.
        if not force_seed and not SEED_FALLBACK:
            why = err or ("no authoring provider was configured — neither "
                          "ANTHROPIC_API_KEY nor GOOGLE_AI_API_KEY is set")
            # Truncated: `err` may be a full page stack trace from probe_render,
            # and this string is the Batch failure message the state machine
            # carries into the failure email.
            raise RuntimeError(
                f"authoring failed after {len(attempts)} attempt(s) and "
                f"SEED_FALLBACK is off, so this run will not publish the seed "
                f"piece. Last authoring error:\n{why[:2000]}")
        # Never leave the pipeline with nothing to render. The seed is a real,
        # gate-passing 60 s piece; the run is still honest because authored_by
        # records that the model path did not produce it.
        log.error("all authoring attempts failed — falling back to the seed piece")
        (Path(wd) / "piece.html").write_text(_read("seed_aurora.html"))
        # The seed piece fetches 'data/aurora.json' RELATIVE to itself, so the
        # data has to travel with it into the workdir and then into S3 —
        # otherwise every render shard 404s and render.mjs exits before frame 0.
        (Path(wd) / "data").mkdir(exist_ok=True)
        (Path(wd) / "data" / "aurora.json").write_text(_read("data/aurora.json"))
        spec = json.loads(_read("seed_narration.json"))
        source = "seed"

    # ONE repair pass. Look at what was actually rendered, not just whether it
    # ran. Skipped for the seed (it is a known-good piece and there is nothing
    # to fix) and when authoring never produced anything.
    if source in ("claude", "gemini") and os.environ.get("SKIP_REPAIR", "").lower() \
            not in ("1", "true", "yes"):
        try:
            _probe_frames = int(re.search(r"const FRAMES = (\d+);",
                                          (Path(wd) / "piece.html").read_text()).group(1))
            repaired, rcost = preflight_repair(
                Path(wd) / "piece.html", wd, _probe_frames, FPS, cost)
            cost += rcost
            log.info("repair pass: %s (running author cost $%.3f)",
                     "applied" if repaired else "no change", cost)
        except Exception as e:                              # noqa: BLE001
            # A repair that crashes must not lose a scene that already renders.
            log.warning("repair pass errored, keeping original: %s", e)

    piece_src = (Path(wd) / "piece.html").read_text()

    if spec.get("picture_locked"):
        # The scene's pose() is keyed to fixed frame numbers, so the picture
        # cannot move. Read its real timing out of the file rather than trusting
        # the narration JSON, and fit the audio into those slots.
        fps = int(re.search(r"FPS = (\d+);", piece_src).group(1))
        frames = int(re.search(r"const FRAMES = (\d+);", piece_src).group(1))
        beats = [{"id": s["id"], "from": s["from"], "to": s["to"]}
                 for s in spec["narration"]]
        if beats[-1]["to"] + 1 != frames:
            raise RuntimeError(f"seed narration slots end at {beats[-1]['to']} "
                               f"but the piece is {frames} frames — they must match")
        paths, durs = _tts_all(spec["narration"], wd)
        # Fit each segment to its slot with a clamped atempo. Gemini has no speed
        # control, so this is the only pacing lever, and it is a nudge not a
        # rescue: past 1.15 the pitch artefacts are audible, so anything still
        # overrunning after clamping is a script that is too long and is logged
        # as such rather than silently mangled.
        from tts import retime
        fitted = []
        for i, (seg, p, d) in enumerate(zip(spec["narration"], paths, durs)):
            slot = (seg["to"] - seg["from"] + 1) / fps
            want = d / slot if slot > 0 else 1.0
            if want > 1.02:
                p2, d2, applied = retime(p, Path(wd) / f"vo_{i:02d}_fit.wav", want)
                log.info("  fit %-9s %5.2fs -> %5.2fs (slot %4.1fs, atempo %.3f)",
                         seg["id"], d, d2, slot, applied)
                p, d = p2, d2
            fitted.append(p)
            seg["duration"] = d
            over = d - slot
            if over > 0.5:
                log.warning("  '%s' STILL overruns its slot by %.1fs after atempo "
                            "— the script is too long for this beat",
                            seg["id"], over)
        paths = fitted
        from tts import mix_track_to_slots
        mix_track_to_slots(paths, [s["from"] / fps for s in spec["narration"]],
                           frames / fps, Path(wd) / "narration.wav")
    else:
        fps = FPS
        durs = synthesise(spec["narration"], wd)
        for seg, d in zip(spec["narration"], durs):
            seg["duration"] = d
        beats, frames = beats_from_durations(spec["narration"], fps,
                                             lead=0.4, gap=0.25, tail=0.8)
        piece_src = inject_timing(piece_src, fps, frames, beats)
        (Path(wd) / "piece.html").write_text(piece_src)

    ok, out = probe_render(Path(wd) / "piece.html", wd)
    if not ok:
        raise RuntimeError(f"scene broke after timing injection:\n{out[:2000]}")

    plan = {
        "video_id": video_id, "topic": topic, "title": spec.get("title", topic),
        "fps": fps, "frames": frames, "subsamples": SUBSAMPLES, "shards": SHARDS,
        "authored_by": source,
        "cost": {"author_usd": round(cost, 4)},
        "narration": [{"id": s["id"], "text": s["text"],
                       "duration": s["duration"]} for s in spec["narration"]],
        "beats": beats,
        "timings": {"prep_s": round(time.time() - t0, 1)},
    }
    upload_file(Path(wd) / "piece.html", video_id, "piece.html")
    upload_file(Path(wd) / "narration.wav", video_id, "narration.wav")
    # Anything the piece fetch()es at runtime must reach the shards too.
    for f in sorted((Path(wd) / "data").glob("*")) if (Path(wd) / "data").is_dir() else []:
        if f.is_file():
            upload_file(f, video_id, f"data/{f.name}")
    upload_bytes(json.dumps({"fps": fps, "frames": frames, "beats": beats},
                            indent=2).encode(), video_id, "beats.json")
    save_plan(video_id, plan)
    log.info("prep done: %d frames (%.1fs at %dfps), authored_by=%s, "
             "author cost $%.3f", frames, frames / fps, fps, source, cost)
