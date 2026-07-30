"""
JOB_TYPE=prep — topic in, a validated renderable scene + narration track out.

The expensive thing in this pipeline is not compute, it is the model call. A
sharded 1440-frame render costs about $0.15; one Opus 5 authoring call costs
about $0.37. The bulky, unchanging part of the prompt is marked for caching
(cache reads bill at 0.1x), and every candidate is validated by actually
rendering three frames before 30 minutes of shard time is committed to it.

Authoring is expressed as a list of {find, replace} edits against the template,
not as a whole file. Emitting the full 45 KB piece.html would be ~12k output
tokens of harness the model would be copying verbatim, and every copy is a
chance to corrupt it. Edits are cheap, and a missing anchor fails loudly.

EVERY MODEL CALL HERE IS OPUS 5 — authoring, retries and the vision repair.
Gemini used to take the last authoring attempt as a provider hedge; on the two
scheduled runs where it was ever reached it failed both times with its own JSON
errors and both slots published nothing, so it is gone (it survives as the TTS
fallback in tts.py, which is a genuinely independent failure domain).

TWO LOOPS, and both matter more than the prompt does:
  1. AUTHORING, up to MAX_AUTHOR_ATTEMPTS, each retry fed the previous error —
     a parse failure, a rejected anchor, or the renderer's own stack trace.
  2. PREFLIGHT REPAIR, up to REPAIR_CYCLES, each cycle re-rendering a strided
     preflight, re-gating it and re-looking at a contact sheet. This is the
     loop a human runs with the motion-video skill, and it was single-shot
     until two published pieces came out of it completely unrepaired.

The bundled seed piece guarantees a MANUAL run always produces a video; the run
records which path it took in plan.json['authored_by'] so a silent downgrade is
visible. Scheduled runs disable it and skip the slot instead.
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
# How many render -> look -> fix cycles the preflight repair may run.
#
# 6, up from 3, and the number comes from the skill this pipeline automates:
# "one run took eight preflight cycles" with a human in the loop, on the piece
# everyone agreed was the best. Three was a cost compromise made before the loop
# had ever been shown to work; it now demonstrably does, and iteration is the
# only mechanism here that judges the PICTURE rather than the numbers.
#
# ~90 s and ~$0.27 a cycle, and the loop exits as soon as the model reports
# nothing left to fix — so a piece that comes out right first time still pays
# for one, and only the pieces that need the work pay for six.
REPAIR_CYCLES = int(os.environ.get("REPAIR_CYCLES", "6"))
# 4, up from 3. Every attempt is now Opus 5 fed the previous error, and the two
# largest causes of a wasted attempt (a JSON header and an over-strict anchor
# match) are gone — so an attempt is now much more likely to be a real second
# opinion than a repeat of the same parse failure. A skipped slot publishes
# nothing at all, which is far more expensive than one more authoring call.
MAX_AUTHOR_ATTEMPTS = 4
# Hard ceiling on the whole authoring + repair budget for one piece. Checked
# before each attempt and before each repair cycle, so it bounds the run rather
# than merely reporting on it.
#
# 3.60, funding 4 authoring attempts (~$1.48 at a MEASURED ~$0.37 each) plus 6
# repair cycles (~$1.62 at ~$0.27 each) with headroom.
#
# This deliberately breaks the old "$3 a video" rule, and the trade is explicit:
# cadence dropped from 5 videos a day to 3 at the same time, so the DAILY spend
# is roughly flat while each piece can afford to be iterated on six times. Our
# own analytics are what justify it — the top 3 reels carry 46% of all views, so
# a better piece is worth far more than an extra piece.
#
# Typical run: authors first time, needs two or three repair cycles, spends
# about $1.30. Only a piece that keeps failing spends the ceiling.
AUTHOR_COST_CEILING_USD = float(os.environ.get("AUTHOR_COST_CEILING_USD", "3.60"))

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

SIZE BUDGET — 5 TO 9 EDITS, AND THE WHOLE RESPONSE UNDER ~28,000 TOKENS.
There are five authorable regions (BEATS, SCENE, CAMKEYS, POSE, CAPTIONS), so
five to nine edits is the natural shape: one per region, plus a few for
materials or a helper. Replace WHOLE REGIONS rather than making many small
incisions inside them — one edit carrying a rewritten pose() is safer than six
edits inside pose(), cannot overlap itself, and costs the same tokens.

This is a hard constraint, not advice. MEASURED across recent runs: attempts
that finished used 12,000-15,000 output tokens, and attempts that ran to the
32,000 cap were TRUNCATED mid-list — losing the later anchors, which are
CAMKEYS, POSE and CAPTIONS. One such response shipped a piece whose captions
still read "REPLACE THIS LINE". A truncated response is rejected outright, so
going long does not buy you a bigger scene, it buys you nothing.

If the scene you have in mind does not fit, make the SCENE simpler, not the
edits smaller.

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

BUILD SEVERAL DISTINCT OBJECTS, NOT ONE. A scene is a place, not a specimen on a
white background, and this is the difference between the pieces that work and
the ones that do not. The best piece this pipeline has produced had, on screen
at once: a bee assembled from body segments, legs and translucent wings; a
flower with separate petals, stamens and a stem; a field of other flowers
receding into bokeh behind it; and drifting pollen. The worst had a thin line
and a caption.

Every scene needs at least THREE distinguishable elements:
  1. THE SUBJECT — the thing the narration is about, built properly, in
     several parts so it reads as an object rather than a shape.
  2. WHAT IT ACTS ON OR AGAINST — the raindrop the ray enters, the water the
     bubble collapses into, the flower the bee lands on. A mechanism has two
     sides; build both.
  3. CONTEXT THAT GIVES SCALE AND DEPTH — a receding field of the same object,
     a ground plane, a horizon, suspended particles, a cutaway of the
     surrounding medium. Something at a different distance from the camera, so
     depth of field has two planes to separate and the subject has a size.
Reuse geometry with InstancedMesh for the third one; a hundred instances of one
flower is cheap and turns a specimen into a place.

DO NOT let the subject be a single featureless sphere. A piece about a
cavitation bubble that renders one blue ball filling the frame for twenty
seconds has built nothing: give the bubble a surface that deforms, put the claw
that made it in shot, show the water around it, cut away to the collapse.

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

CONTRAST — AND THE FLOOR MATTERS AS MUCH AS THE CEILING. Aim for a dark scene
with BRIGHT SUBJECTS. Both halves are gated:
- Ceiling: the 1st percentile of luma must stay in low single digits. A
  full-frame pastel wash reads as flat, and bloom has nothing to bite on. If the
  subject is genuinely bright (a sky, a flame), keep something dark in frame for
  it to read against.
- FLOOR: whole-piece mean luma must exceed 18/255, and no single beat may sit
  below 10. "Dark scene" means dark BACKGROUND with a lit subject in front of
  it, never a dark screen. MEASURED failure: a piece about crepuscular rays
  rendered at mean luma 7.9 with beats as low as 4.0 — a black rectangle with
  white captions — and it published. For calibration, a good piece runs a mean
  near 40-80 with beats between 45 and 120.
- Practically: give the scene a real key light, put an emissive or strongly lit
  material on the subject, and check that the SUBJECT is what is bright. Light
  falling only on a backdrop reads as an empty room.

CAMERA. The camera is a third of the storytelling and CAMKEYS is where most
pieces under-use it. Rules that have held up:
- MOVE ON EVERY BEAT. A static camera for 40 seconds reads as a screenshot,
  however good the geometry. Push in on a reveal, orbit to show that a thing is
  three-dimensional, pull back to give scale at the end.
- MATCH THE MOVE TO THE BEAT. Naming the subject wants a slow push in. The turn
  wants a cut or a fast reframe. A mechanism wants an orbit or a track along the
  thing. The landing wants a pull back that puts the subject in its context.
- CHANGE SCALE ACROSS THE PIECE. If every shot is framed at the same distance
  the piece has no rhythm. Go close enough that the subject leaves frame at
  least once, and wide enough to see where it lives at least once.
- CUT RATHER THAN FLY between staging areas that are far apart (see cut:1
  below). A ten-second drift across empty space is ten seconds of nothing.
- Keep the subject inside x60-900, y200-1560. Content outside that box is
  reported by the gates and is usually a camera that drifted off its subject.

Hard rules, each learned from a real failure:
- CAPTION WINDOWS IN THE SAME SCREEN BAND MUST NOT OVERLAP. Every caption is
  `play(frame, inStart, inEnd, outStart, outEnd)` and is VISIBLE from inStart to
  outEnd. Two captions whose [inStart, outEnd] ranges overlap, and which sit at
  the same y, render on top of each other and produce unreadable mush. MEASURED:
  a published piece showed "THEYNARE PARALLEL" where two captions collided.
  Before you finish, list every caption's [inStart, outEnd] and check that any
  two that share a band are disjoint. A stacked pair (a title with a subtitle
  beneath it) is fine and expected — that is two different bands.
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
  makeCard, makeAxis, makeGlow, makeScrim, makeCaption, makeAnchoredLabel,
  setEnvironment, makeSkyDome, makeDepthField.
  Every make* returns a controller with .set() and .mesh — never reach past it.

THE THREE ENVIRONMENT HELPERS. These exist because a subject alone on black is
what a cheap render looks like, and all three are one line each.

- setEnvironment({sky, ground, key, rim, intensity}) — IMAGE-BASED LIGHTING.
  Already called once above the AUTHOR marker, so you always have it; CALL IT
  AGAIN with colours that suit your subject. Without an environment map a
  MeshStandardMaterial has nothing to reflect, so metalness renders near-black
  and roughness barely reads — glass, ice, water, wet surfaces and metal are all
  impossible. If your subject is any of those, tuning this matters more than
  anything else you will do to the material.
- makeSkyDome({top, bottom, glow, glowY}) — the far backdrop, in bgScene.
  A flat black background is the most common reason a piece reads as cheap.
  Even a very dark ramp with one warm band near the horizon gives the eye
  somewhere to sit. Re-call it with colours that place the scene: cold blue-black
  for space, brown-black for underground, deep teal for underwater.
- makeDepthField(geometry, material, {count, near, far, spread}) — N instances
  of a geometry scattered across a DEPTH RANGE in the main scene, so they get
  parallax as the camera moves and real depth-of-field bokeh. This is the single
  strongest "expensive-looking" trick available: reuse a geometry you already
  built for the subject, scatter 40-100 of them from z -30 to -260, and the shot
  goes from a specimen on a table to a place with weather in it.

  Note the split: makePointField/STARS go in bgScene BECAUSE points at infinity
  shred into aperture copies. makeDepthField goes in the MAIN scene precisely
  BECAUSE you want it to blur.
- A camera key may set cut:1 (10th element) to SNAP instead of interpolating.
  Use it between staging areas rather than flying the camera across the gap.
- The safe box is x 60-900, y 200-1560 of 1080x1920. It is NOT centred; compose
  on x 480.
- A single NaN in shading turns the WHOLE frame black, because the bloom mip
  chain spreads it. Guard any normalize() on a difference of two path points.

Return your answer in EXACTLY this format. NOTHING here is JSON. Not the header,
not the edits. Escaping every quote, newline and backslash of a multi-kilobyte
payload perfectly is a coin flip, and one slip discards the whole response —
MEASURED: a 30,505-character response thrown away over a single delimiter, and
three more attempts lost in one day to a header whose narration contained an
apostrophe.

===TITLE===
short title card text, one line
===NARRATION===
One segment per line, formatted as:
  id | one or two spoken sentences
The id is a short lowercase word (hook, turn, mechanism, land). Write the spoken
text literally: apostrophes, quotes and numbers all fine, nothing is escaped.

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


def _retention_digest():
    """
    What held viewers last month, or '' — cached per process.

    Deliberately OUTSIDE the cached system block: it changes as posts land, and
    putting it in the cached prefix would either bust the cache on every run or
    serve a stale digest for the life of the cache entry.
    """
    global _DIGEST
    if _DIGEST is None:
        try:
            import winners
            _DIGEST = winners.digest()
        except Exception as e:                              # noqa: BLE001
            log.warning("retention digest unavailable (%s) — authoring blind", e)
            _DIGEST = ""
    return _DIGEST


_DIGEST = None


def _user_prompt(topic, seconds, previous_error=None):
    anchor_help = "\n".join(f"  {n}: {a!r}" for n, a in ANCHORS)
    p = (f"Topic: {topic}\n"
         f"Target duration: {seconds} seconds at {FPS} fps.\n\n"
         f"Anchors you will most likely edit (exact substrings of the template):\n"
         f"{anchor_help}\n\n"
         "Make it beautiful and make every number on screen defensible. One clear "
         "idea per beat. Prefer one dense well-composed scene over many thin ones.")
    digest = _retention_digest()
    if digest:
        p += "\n" + digest
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
        # Name the real cause instead of letting the parser do it.
        raise RuntimeError(
            f"model returned no text (stop_reason={r.stop_reason}, blocks={kinds}, "
            f"output_tokens={usage.get('output_tokens')}) — "
            f"max_tokens likely exhausted by thinking")

    # A TRUNCATED RESPONSE IS A FAILED ATTEMPT, not a partial success.
    #
    # This is subtle and it published placeholder text before it was caught.
    # MEASURED on a scheduled run: `stop=max_tokens out=32000 text=69209 chars`.
    # The model was still emitting edits when the budget ran out, so the list
    # arrived with its EARLY edits intact and its later ones missing — and the
    # early ones are BEATS and SCENE while CAPTIONS comes last. Every edit that
    # did arrive applied cleanly, and probe_render passed because the piece still
    # renders perfectly: it renders the TEMPLATE. The scene was accepted with its
    # captions still reading "REPLACE THIS LINE / AND THIS ONE / TITLE".
    #
    # Nothing downstream can catch this. The gates see a lit scene with type on
    # it. Only the vision pass noticed, and only because it happened to run.
    if r.stop_reason == "max_tokens":
        raise RuntimeError(
            f"response was TRUNCATED at max_tokens ({usage.get('output_tokens')} "
            f"output tokens, {len(text)} chars). The edit list is incomplete, so "
            f"the later anchors — usually CAPTIONS — were never written. Send "
            f"FEWER, LARGER edits: one edit replacing a whole block beats six "
            f"inside it and costs the same.")
    return _parse_authored(text), _price(usage, True), "claude"


# author_gemini USED TO LIVE HERE and has been deleted rather than left dormant.
# It was the third authoring attempt, and on the two scheduled runs where it was
# ever actually reached it failed both times with its own JSON errors while
# burning the last attempt — so both slots published nothing. It also requested
# response_mime_type="application/json", which the block-delimited format above
# no longer produces, so it could not have worked again without being rewritten.
# Dead code that advertises itself as a fallback is worse than no fallback: the
# next person to read this would believe there was a hedge in place.
#
# Authoring is Opus 5 on every attempt. Gemini remains the TTS fallback in
# app/tts.py, which is a genuinely independent failure domain.


def _loose_span(haystack, needle):
    """
    Locate `needle` in `haystack` ignoring differences in RUNS OF WHITESPACE.

    Returns (start, end) of the single match, None for no match, and raises on
    an ambiguous one. Indentation and line wrapping are the only things allowed
    to differ; every non-space character must still match in order.

    This exists because the exact-match failures were overwhelmingly reflow, not
    invention. MEASURED across two scheduled runs, both of which were skipped
    entirely: two attempts died on the POSE anchor with "you invented the
    anchor" when the model had reproduced the region correctly and re-indented
    it. Whitespace is the one dimension of a code anchor that carries no meaning
    and that a model reliably perturbs.
    """
    pattern = re.compile(r"\s+".join(re.escape(tok) for tok in needle.split()))
    hits = list(pattern.finditer(haystack))
    if not hits:
        return None
    if len(hits) > 1:
        raise ValueError(f"anchor matches {len(hits)} places after whitespace "
                         f"normalisation, must be unique: {needle[:120]!r}")
    return hits[0].span()


# Strings that exist ONLY in the unedited template. If any survive into an
# authored piece, the CAPTIONS region was never really written.
PLACEHOLDERS = ("REPLACE THIS LINE", "AND THIS ONE", "makeCaption('TITLE'")


def assert_authored(piece, spec):
    """
    Refuse a piece that is still substantially the template.

    probe_render proves the JavaScript RUNS, and the unedited template runs
    beautifully — so "it rendered" was never evidence that anything had been
    authored. A truncated edit list produced exactly this: valid piece, valid
    render, captions reading "REPLACE THIS LINE".

    Raising here sends the attempt back round the authoring loop with a message
    that names the problem, which is the only place it can still be fixed
    cheaply.
    """
    left = [p for p in PLACEHOLDERS if p in piece]
    if left:
        raise ValueError(
            f"the piece still contains template placeholder text {left} — the "
            f"CAPTIONS region was never edited. Every caption must say something "
            f"about this topic. If your edit list was cut short, send fewer and "
            f"larger edits.")
    if not (spec.get("narration") or []):
        raise ValueError("no narration segments were returned; the piece has "
                         "nothing to say and nothing to time the beats against")
    if len(spec.get("edits") or []) < 3:
        # BEATS, SCENE, CAMKEYS, POSE and CAPTIONS are five distinct regions;
        # fewer than three edits cannot have touched enough of them to be a
        # piece about anything.
        raise ValueError(
            f"only {len(spec.get('edits') or [])} edit(s) returned — a real "
            f"piece rewrites BEATS, SCENE, CAMKEYS, POSE and CAPTIONS")


def apply_edits(template, edits):
    """
    Apply {find, replace} in order, failing loudly on a stale anchor.

    `find` must be UNIQUE: a prefix match is how a previous run silently
    prepended a whole function to line 1 of the document and produced a
    ReferenceError a thousand lines from the cause.

    Exact match first, then a whitespace-insensitive retry. The relaxation only
    ever forgives indentation, never content.
    """
    s = template
    for i, e in enumerate(edits):
        find, repl = e["find"], e["replace"]
        n = s.count(find)
        if n > 1:
            raise ValueError(f"edit {i}: anchor matches {n} places, must be "
                             f"unique: {find[:120]!r}")
        if n == 1:
            s = s.replace(find, repl, 1)
            continue

        span = _loose_span(s, find)
        if span:
            log.info("edit %d: anchor matched only after whitespace "
                     "normalisation — applied", i)
            s = s[:span[0]] + repl + s[span[1]:]
            continue

        # Distinguish "never existed" from "an earlier edit ate it" — the
        # second is by far the more common, and the model can only fix it if
        # the message says so. Both checks use the loose match too, so the
        # diagnosis is not itself defeated by re-indentation.
        overlapped = template.count(find) or _loose_span(template, find)
        why = ("it was still in the ORIGINAL template, so an EARLIER edit in "
               "this list replaced the region containing it — your edits "
               "overlap"
               if overlapped else
               "it is not in the template at all — you invented the anchor")
        raise ValueError(f"edit {i}: anchor not found. {why}. "
                         f"anchor was: {find[:200]!r}")
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
3. TOO DARK. If the gates say "scene is unlit" or a beat is below luma 10, the
   scene has no lit subject: a dark BACKGROUND is correct, a dark SCREEN is not.
   Add or raise a key light, make the subject's material emissive, and confirm
   the light lands on the SUBJECT rather than on a backdrop. A whole-piece mean
   luma under 18 is a failure; a good piece runs 40-80.
4. TOO EMPTY. One object alone in the void. A scene needs the subject, the thing
   it acts on, and something at another depth for scale — a receding field, a
   ground plane, suspended particles. InstancedMesh makes the third one cheap.
5. WASHED OUT. A flat pastel frame with no dark anywhere. The gates report the
   1st percentile of luma; low single digits is the target.
6. BLOWN OUT. Large white areas, or a clipped-pixel figure above ~2%.
7. STATIC CAMERA. If consecutive tiles are framed identically, the camera is not
   working. Add a push, an orbit or a pull back on that beat, and vary the
   framing distance across the piece.
8. UNREADABLE TYPE. Captions overlapping the subject, captions overlapping EACH
   OTHER (two whose [inStart, outEnd] windows overlap at the same y render as
   mush — a shipped piece read "THEYNARE PARALLEL"), or type too small to read
   at thumbnail size, which is how this will actually be watched.
9. MONOTONY. Six tiles that look identical mean six seconds where nothing
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
the original template.

NON-OVERLAPPING ANCHORS IS THE RULE THAT ACTUALLY BREAKS THIS. Edits are applied
IN ORDER to the evolving document. If edit 3 replaces a block, edit 9 cannot
anchor on text that was inside that block — it no longer exists, the whole list
is rejected, and NOTHING is changed. MEASURED: on two consecutive scheduled runs
every proposed repair was discarded exactly this way, and both pieces published
unrepaired. It is the single most common way this call is wasted.

So, before you send:
- For each edit, ask which earlier edit's replacement region contains its
  anchor. If any does, merge the two into ONE edit with a wider anchor.
- Prefer FEWER, LARGER edits. One edit replacing a whole function is safer than
  six edits inside it, and costs the same.
- Each `find` must appear EXACTLY ONCE in the current document.
- Anything you delete must not still be referenced by pose().

CLEAN GATES DO NOT MEAN A GOOD PIECE. The gates detect a BROKEN render — dead
frames, lifted blacks, blown highlights, an unlit scene. They cannot see a
sparse scene, a camera that never moves, a subject that is one grey sphere, or a
payoff that never arrives. If the gates pass and the sheet is still dull, the
dull sheet is the thing to fix. Judge the picture, not the numbers.

You may be asked again after your edits land, with a fresh sheet. That is normal
and it is how this is meant to work: fix the biggest problem each round rather
than trying to solve everything in one pass.

If the sheet genuinely looks good — a built subject, something at more than one
depth, visible camera movement, readable type, and a beat-to-beat progression —
return an assessment saying so and NO edit blocks. That is the signal to stop.
Do not invent work. A cosmetic tweak that risks a ReferenceError is worse than
leaving it alone."""


_EDIT_RE = re.compile(
    r"<<<<<<<+ *FIND\r?\n(.*?)\r?\n=======+\r?\n(.*?)\r?\n>>>>>>>+ *END",
    re.S)


def _parse_authored(text):
    """
    ===TITLE=== / ===NARRATION=== blocks + conflict-marker edits -> dict.

    THE HEADER USED TO BE JSON and it was the single largest source of lost
    authoring attempts. On 2026-07-29 alone, three of six attempts across two
    scheduled runs died here:
        Expecting property name enclosed in double quotes: line 1 column 2
        Extra data: line 1 column 3
        Expecting ',' delimiter: line 49 column 8
    Both scheduled slots were skipped as a result. The narration is PROSE — it
    contains apostrophes, quotes, degree signs and numbers — and the old regex
    `\\{.*?\\}` was non-greedy, so it also truncated at the first `}` that
    happened to fall inside a string. There is nothing here worth the escaping
    risk: a title is one line and narration is one line per segment.
    """
    blocks = _parse_edit_blocks(text)
    sections = _parse_sections(text)

    narration = []
    for line in (sections.get("NARRATION") or "").splitlines():
        line = re.sub(r"^\s*[-*]\s*", "", line.strip())
        if not line:
            continue
        seg_id, sep, spoken = line.partition("|")
        if not sep:
            # A line with no pipe is still speech; give it a positional id
            # rather than dropping a segment on a formatting slip.
            seg_id, spoken = f"seg{len(narration) + 1}", line
        seg_id = re.sub(r"[^a-z0-9_]", "", seg_id.strip().lower()) or \
            f"seg{len(narration) + 1}"
        spoken = spoken.strip()
        if spoken:
            narration.append({"id": seg_id, "text": spoken})

    return {"title": (sections.get("TITLE") or "").strip().splitlines()[0]
            if sections.get("TITLE") else "",
            "narration": narration,
            "edits": blocks["edits"]}


def _parse_sections(text):
    """===NAME=== delimited sections -> {name: body}. Same shape as postcopy."""
    out = {}
    parts = re.split(r"^={2,}\s*([A-Z][A-Z0-9_]*)\s*={2,}\s*$", text, flags=re.M)
    for i in range(1, len(parts) - 1, 2):
        body = parts[i + 1]
        # Stop a section at the first edit block: the edits follow the header
        # and must not be swallowed into NARRATION.
        body = re.split(r"^<<<<<<<+ *FIND", body, flags=re.M)[0]
        if body.strip():
            out[parts[i].strip().upper()] = body.strip()
    return out


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


def _beats_arg(piece_path):
    """
    The piece's own BEATS table as check.py's `name:a-b,name:a-b` argument.

    Read back out of the rendered document rather than threaded through as a
    parameter: inject_timing has already written the real, audio-measured
    frame ranges in there, so this is the one place guaranteed to agree with
    what actually rendered.
    """
    try:
        src = Path(piece_path).read_text()
    except Exception:                                       # noqa: BLE001
        return ""
    m = re.search(r"const BEATS = \[(.*?)\n\];", src, re.S)
    if not m:
        return ""
    rows = re.findall(r"id:\s*'([^']+)'\s*,\s*from:\s*(\d+)\s*,\s*to:\s*(\d+)",
                      m.group(1))
    return ",".join(f"{n}:{a}-{b}" for n, a, b in rows)


def _preflight(piece_path, wd, plan_frames, fps, tag):
    """Strided render + gates + contact sheet -> (n_frames, gates, png_b64)."""
    import base64

    # .resolve(): render.mjs resolves a RELATIVE --out against its own ROOT, not
    # against cwd, so a relative workdir silently writes the frames somewhere
    # else and the glob below finds nothing. Same trap that made probe_render
    # always report failure.
    frames = (Path(wd) / f"preflight{tag}").resolve()
    sheet = (Path(wd) / f"preflight_sheet{tag}.png").resolve()
    stride = max(1, plan_frames // 24)
    r = subprocess.run(
        ["node", str(APP / "render.mjs"), "--page", page_url_path(piece_path),
         "--out", str(frames), "--stride", str(stride), "--ss", "2"],
        cwd=wd, capture_output=True, text=True, timeout=1800, env=render_env())
    n = len(list(frames.glob("*.png")))
    if r.returncode != 0 or n < 8:
        log.warning("preflight render produced %d frames", n)
        return 0, "", None

    # --beats IS NOT OPTIONAL HERE. Without it check.py can only judge the piece
    # as a whole, and the failure this loop exists to catch is LOCAL: one dead
    # beat inside an otherwise lit piece. MEASURED on a real authored piece —
    # whole-piece mean luma 35.3 ("all gates passed"), and with the same frames
    # gated per beat: hook 6.5, turn 4.0, land 2.3, i.e. the opening eight
    # seconds and the entire closing shot were black. The beats are already
    # injected into piece.html by inject_timing, so they cost nothing to read.
    cmd = [sys.executable, str(APP / "check.py"), "--frames", str(frames),
           "--fps", str(fps)]
    beats_arg = _beats_arg(piece_path)
    if beats_arg:
        cmd += ["--beats", beats_arg]
    g = subprocess.run(cmd, capture_output=True, text=True)
    gates = (g.stdout + g.stderr).strip()

    # CAMERA CLEARANCE, which render.mjs has always computed on a strided run
    # and which this function used to throw away — it read the frame count out
    # of the render and ignored everything else it said.
    #
    # That report is the CAUSE behind the symptom check.py keeps flagging.
    # MEASURED on a real piece: check.py said "blacks lifted: p1 luma 94.8 at
    # f1140", and the frame turned out to be a flat beige wash between two dark
    # frames — the camera was INSIDE the geometry for exactly one frame while
    # crossing between two staging areas. The numeric gate can only see a bright
    # frame; the clearance report names the object being flown through, which is
    # what the model needs to move the camera key or make it a cut.
    clearance = [ln for ln in (r.stdout or "").splitlines()
                 if "camera clearance" in ln or "units from" in ln
                 or "more" == ln.strip()[-4:]]
    if clearance and "clear" not in clearance[0]:
        gates += ("\n\nCAMERA PATH:\n" + "\n".join(clearance)
                  + "\nA frame where the camera is inside geometry renders as a "
                    "flat full-screen wash. Move that camera key clear of the "
                    "object, or make it a cut (cut:1) so the camera never "
                    "interpolates through the gap.")
    log.info("preflight gates (cycle%s):\n%s", tag, gates)

    try:
        _contact_sheet(frames, sheet)
        return n, gates, base64.standard_b64encode(sheet.read_bytes()).decode()
    except Exception as e:                                  # noqa: BLE001
        log.warning("could not build contact sheet: %s", e)
        return n, gates, None


def preflight_repair(piece_path, wd, plan_frames, fps, attempt_cost,
                     max_cycles=None):
    """
    Render a strided preflight, gate it, LOOK at it, let the model fix it, and
    then LOOK AGAIN. Iterative, because one pass demonstrably is not enough.

    This is the loop a human runs with the motion-video skill. The skill's own
    notes put a number on it: "one run took EIGHT preflight cycles". This ran
    exactly one, single-shot, with no retry on failure -- and on 2026-07-29 both
    scheduled pieces that reached it came out of it completely unrepaired:

        repair edits did not apply (edit 17: anchor not found ... your edits
        overlap) - keeping original      -> repair pass: no change
        repair edits did not apply (edit 1: anchor not found ... your edits
        overlap) - keeping original      -> repair pass: no change

    Both then published. The vision pass had correctly identified that they
    needed work; the edits were simply thrown away, silently, and prep carried
    on. A repair that cannot survive its own most common failure mode is not a
    repair pass, it is a log line.

    Two changes:
      - An apply failure now FEEDS THE ERROR BACK and re-asks, exactly as the
        authoring loop has always done. Overlapping anchors are a fixable
        mistake and the model fixes them when told.
      - The whole thing loops while the gates still fail, re-rendering and
        re-looking each time, so a fix that helps but does not finish gets
        another turn.

    Returns (repaired: bool, cost_usd: float). Never raises -- a failed repair
    leaves the last piece that RENDERED in place, because that at least renders.
    """
    import anthropic

    cycles = max_cycles if max_cycles is not None else REPAIR_CYCLES
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    total_cost = 0.0
    repaired = False
    apply_error = None

    for cycle in range(cycles):
        if attempt_cost + total_cost > AUTHOR_COST_CEILING_USD:
            log.warning("repair stopping: spend $%.2f would exceed the $%.2f "
                        "ceiling", attempt_cost + total_cost,
                        AUTHOR_COST_CEILING_USD)
            break

        n, gates, png = _preflight(piece_path, wd, plan_frames, fps,
                                   f"{cycle}" if cycle else "")
        if not png:
            break

        # THERE IS DELIBERATELY NO "GATES ARE CLEAN, STOP" EXIT.
        #
        # Two earlier versions had one and both were wrong, for the same reason:
        # the gates detect a BROKEN render, never a dull one. They cannot see a
        # sparse scene, a static camera, or a payoff that never lands.
        #   v1: `if gates_clean and cycle: break` — cycle 0's fix was rejected by
        #       the probe render, and cycle 1 exited on clean gates before the
        #       retry could run. The piece shipped with defects the model had
        #       already written down.
        #   v2: also required `repaired` — better, but it still stopped after one
        #       successful fix on a piece whose own repair assessment had called
        #       the sky beats "nearly black ... captions floating on nothing".
        #       Gates said clean; the piece was mediocre.
        #
        # The honest terminator is the MODEL returning no edits, handled below.
        # Otherwise this runs its full budget, which is what the skill it
        # automates does — eight cycles, by hand, on the piece everyone liked.
        # Each cycle is ~90 s and ~$0.27, and reverts anything that regresses.
        gates_clean = "gates FAILED" not in gates and "FAIL:" not in gates
        log.info("repair cycle %d: gates %s", cycle,
                 "clean" if gates_clean else "FAILING")

        piece = piece_path.read_text()
        ask = (f"{n} frames, evenly spaced across the whole piece.\n\n"
               f"GATES:\n{gates}\n\nCURRENT piece.html:\n{piece}")
        if apply_error:
            ask = ("YOUR PREVIOUS EDITS WERE REJECTED AND NOTHING WAS CHANGED. "
                   f"The error was:\n{apply_error}\n\nRe-read the rules about "
                   "non-overlapping anchors, then send a corrected edit list "
                   "against the piece below, which is UNCHANGED from before.\n\n"
                   + ask)

        try:
            with client.messages.stream(
                # 24000, not 16000: MEASURED, a real repair emitted 16,679
                # output tokens (13 edits carrying whole replacement blocks) and
                # 16000 cut the response mid-string.
                model=CLAUDE_MODEL, max_tokens=24000,
                thinking={"type": "disabled"},
                system=REPAIR_SYSTEM,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64",
                                                 "media_type": "image/png",
                                                 "data": png}},
                    {"type": "text", "text": ask},
                ]}],
            ) as stream:
                resp = stream.get_final_message()
            text = "".join(b.text for b in resp.content if b.type == "text")
            usage = (resp.usage.model_dump() if hasattr(resp.usage, "model_dump")
                     else dict(resp.usage))
            total_cost += _price(usage, False)
            spec = _parse_edit_blocks(text)
        except Exception as e:                              # noqa: BLE001
            log.warning("repair call failed on cycle %d: %s", cycle, e)
            break

        log.info("repair cycle %d assessment: %s", cycle,
                 (spec.get("assessment") or "(none given)")[:400])
        edits = spec.get("edits") or []
        if not edits:
            log.info("model reports nothing to fix — stopping")
            break

        # Apply to a COPY. If the repaired piece does not render, the previous
        # one is still on disk and still works -- a repair must never be able to
        # make things worse than not repairing.
        backup = piece_path.read_text()
        try:
            piece_path.write_text(apply_edits(backup, edits))
        except Exception as e:                              # noqa: BLE001
            piece_path.write_text(backup)
            apply_error = str(e)
            log.warning("repair cycle %d: edits did not apply (%s) — "
                        "re-asking with the error", cycle, apply_error)
            continue

        ok, out = probe_render(piece_path, wd)
        if not ok:
            piece_path.write_text(backup)
            apply_error = f"the edited piece threw on render:\n{out[:1200]}"
            # The renderer's own error is LOGGED, not just fed back. Without it
            # the operator sees "failed its probe render" and has no way to tell
            # a ReferenceError from a timeout, which is exactly the position the
            # first run of this loop left us in.
            log.warning("repair cycle %d: repaired piece failed its probe "
                        "render — reverting and re-asking:\n%s",
                        cycle, out[:1200])
            continue

        apply_error = None
        repaired = True
        log.info("repair cycle %d applied: %d edits (running repair $%.3f)",
                 cycle, len(edits), total_cost)

    log.info("repair finished: repaired=%s cost $%.3f", repaired, total_cost)
    return repaired, total_cost


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
    else:
        log.info("FORCE_SEED set — skipping model authoring")

    # EVERY ATTEMPT IS OPUS 5. Gemini used to take the last one as a
    # provider-outage hedge, and MEASURED over the two scheduled runs it was
    # actually needed for, it failed BOTH times with its own JSON errors
    # (`Expecting ',' delimiter: line 49`, `Extra data: line 29`) while
    # producing nothing usable. It was not a hedge, it was a wasted attempt at
    # the point of maximum urgency — and it is not the model this pipeline is
    # supposed to be authoring with, so it has been deleted outright rather
    # than left dormant as a fallback that no longer parses.
    #
    # Each retry is fed the PREVIOUS error (a parse failure, a bad anchor, or
    # the renderer's own stack trace), which is what makes a second attempt
    # meaningfully different from a re-roll.
    attempts = providers[:1] * MAX_AUTHOR_ATTEMPTS if providers else []
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
            assert_authored(piece, cand)
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
