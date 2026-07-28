"""
Companion assets — carousel slides, a story teaser, a still, a cover timestamp.

All four are cut from out/video.mp4, which by this point already exists. That is
the whole economic argument for doing it here: the scene was authored once and
rendered once on a T4, and every asset below is ffmpeg seconds and Pillow
milliseconds against a file we already paid for. A separate "carousel pipeline"
would re-author and re-render the same physics for a second time.

Outputs, all under out/ in the motion bucket:
  slides/s1.jpg .. s6.jpg   1080x1350  Instagram's 4:5, the tallest ratio the
                                       feed will show without cropping
  image.jpg                 1080x1350  the single still post
  story.mp4                 1080x1920  15s teaser, audio faded out
  (cover timestamp is returned, not written -- Metricool takes
   videoCoverMilliseconds and picks the frame itself)

FRAME CHOICE IS NOT EVENLY SPACED. Frames are scored and the blown-out and dead
ones are rejected, because the last ice piece ENDED on a frame that was 5.36%
pure white and an evenly-spaced sampler would have made it slide 6.
"""

import json
import math
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import common
from common import logger

SLIDE_W, SLIDE_H = 1080, 1350
STORY_SECONDS = 15
N_SLIDES = 6
# Below this the deck is not a carousel, it is a post with a stray second
# image, so the format is skipped instead.
MIN_SLIDES = 3
# One candidate every 2s. A 75s piece gives ~37 to choose 6 from, which is
# enough slack to skip a bad stretch without paying for a dense decode.
CANDIDATE_EVERY_S = 2.0
# Scoring thresholds, same units as check.py's gates so the two agree about what
# "blank" and "blown" mean.
DEAD_PEAK = 24          # peak channel below this => nothing is on screen
BLOWN_FRACTION = 0.025  # >2.5% of pixels at luminance 248+ => a white-out.
                        # Calibrated, not guessed: the ice piece's final frame
                        # measures 4.28% and every other candidate in that video
                        # measures 0.02% or less, so anything in between is
                        # comfortably on the right side of both.
# A caption-free gap shorter than this is not worth aiming at: the fade in/out
# ramps live at its edges and a 30fps grab lands somewhere inside them.
MIN_FREE_FRAMES = 12
# Added to a caption-free candidate's score. MEASURED score range on the ice
# piece is roughly 68-110 (std of luminance + 0.35 * mean saturation), so 20 is
# a firm preference that a genuinely much better picture can still overturn.
CLEAN_BONUS = 20.0

# Liberation is metric-compatible with Helvetica/Arial, which is what the pieces
# themselves draw captions in, so the carousel reads as the same brand as the
# video. DejaVu is the glyph fallback for the Greek, arrows, °, ± and µ a
# science slide will absolutely contain. macOS paths are last so this module can
# be exercised on a laptop.
FONT_CANDIDATES = {
    'bold': [
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
    ],
    'regular': [
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/System/Library/Fonts/Supplemental/Arial.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
    ],
}


# ============================================================
# fonts
# ============================================================
def _font(weight: str, size: int):
    for path in FONT_CANDIDATES[weight]:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    # Never fatal. A carousel in the default bitmap font is ugly; a run that
    # dies at the last stage because a font moved is worse.
    logger.warning('slides: no %s font found, falling back to PIL default', weight)
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_w: int) -> list:
    """Greedy word wrap against real measured widths."""
    words, lines, cur = (text or '').split(), [], ''
    for w in words:
        trial = f'{cur} {w}'.strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ============================================================
# frame selection
# ============================================================
def _probe_duration(video: Path) -> float:
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'json', str(video)],
        capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)['format']['duration'])


def _score(img: Image.Image) -> tuple:
    """
    (usable, score) for one candidate frame.

    score rewards CONTRAST, because a slide's job is to be legible as a
    thumbnail: a flat mid-grey frame and a frame with a lit subject against dark
    space have the same mean and completely different value here.

    The BLOWN test is on luminance, not on all-three-channels-at-250, and that
    distinction is the whole reason it works. MEASURED on the ice piece's final
    frame, the one that shipped: 2.59% of pixels were 250+ in R, G AND B, but
    4.28% were at luminance 248+. A blue-white flare clips in luminance long
    before it clips in every channel, so the all-channel test let it through and
    the contrast score then ranked it the BEST frame in the video.
    """
    small = img.convert('RGB').resize((160, 284))
    px = list(small.getdata())
    n = len(px)
    peak = max(max(p) for p in px)
    lum = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in px]
    blown = sum(1 for v in lum if v >= 248) / n
    mean = sum(lum) / n
    var = sum((v - mean) ** 2 for v in lum) / n
    sat = sum(max(p) - min(p) for p in px) / n

    usable = peak >= DEAD_PEAK and blown <= BLOWN_FRACTION
    return usable, math.sqrt(var) + 0.35 * sat


def caption_free_windows(piece_html: str, total_frames: int) -> list:
    """
    Frame intervals where the piece is drawing NO caption of its own.

    Pieces put things on screen through TWO template conventions, and both are
    (inStart, inEnd, outStart, outEnd) with the thing visible across
    [inStart, outEnd]:

      CAP.a.play(frame, 16, 42, 230, 256)      captions and rules
      CARD.set(0.95 * band(880, 950, 1180, 1216), 0)   cards, panels, scrims

    Parsing only the first one is not enough, and this is not hypothetical: the
    ice piece holds its data card up from frame 880 to 1216 via `band`, the
    play() calls in that stretch stop at 984, so a play()-only parse reported
    frame 999 as clean and put a slide title straight through the middle of a
    table reading "O-O spacing 0.276 nm".

    This matters because a carousel slide draws its OWN headline: a frame that
    still has "IT SWELLS" or a stats card on it ends up with two sets of
    typography fighting each other. The gaps also tend to fall about one per
    beat, right after one overlay clears and before the next arrives, which is
    when the visual is both fully built and unobstructed.

    Returns [] when the file has neither call, the signal to fall back to plain
    time slicing.
    """
    spans = []
    for pattern in (
        # The helper is declared as `const band = (a, b, c, d) => ...`, whose
        # arguments are letters, so a digits-only pattern cannot match the
        # definition and mistake it for a use.
        r'\.play\(\s*frame\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        r'\bband\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
    ):
        for m in re.finditer(pattern, piece_html or ''):
            start, _, _, end = (int(g) for g in m.groups())
            if end > start:
                spans.append((start, end))
    if not spans:
        return []

    spans.sort()
    merged = [list(spans[0])]
    for a, b in spans[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    free, cursor = [], 0
    for a, b in merged:
        if a - cursor >= MIN_FREE_FRAMES:
            free.append((cursor, a))
        cursor = max(cursor, b)
    if total_frames - cursor >= MIN_FREE_FRAMES:
        free.append((cursor, total_frames))
    return free


def _candidate_times(video: Path, wd: Path, piece_html: str, fps: float) -> tuple:
    """
    [(seconds, is_caption_free)], duration.

    BOTH sets, always: the caption-free windows AND a plain time slice. The
    windows are preferred (via CLEAN_BONUS in the scoring) but they are not the
    only candidates, because there are usually about one per beat and a deck
    wants exactly as many as there are slides. With no slack, one unusable
    window forces a bad frame into the deck -- which is precisely what happened
    on the first run of this file: the ice piece has 6 windows, the last one is
    the white-out, and a 6-slide deck had nowhere else to go.

    A frame with the piece's own caption on it is a cosmetic problem. A frame
    that is 4% pure white is a broken-looking post. Given only those two, take
    the caption.
    """
    dur = _probe_duration(video)
    times = []

    windows = caption_free_windows(piece_html, int(dur * fps))
    if windows:
        # Land 60% into each gap: past the fade-out of the caption that just
        # left, before the fade-in of the next.
        for a, b in windows:
            t = (a + (b - a) * 0.6) / fps
            if 0 <= t <= dur - 0.1:
                times.append((t, True))
        logger.info('slides: %d caption-free windows from piece.html', len(times))
    else:
        logger.info('slides: no play() calls in piece.html - time slicing only')

    clean_ts = [t for t, _ in times]
    t = 0.0
    while t <= dur - 0.5:
        # Skip a sliced candidate that all but duplicates a clean one; decoding
        # both would cost an ffmpeg invocation to learn nothing.
        if all(abs(t - c) > 1.0 for c in clean_ts):
            times.append((t, False))
        t += CANDIDATE_EVERY_S

    times.sort()
    return times, dur


def pick_frames(video: Path, wd: Path, n: int, piece_html: str = '',
                fps: float = 30.0, require_clean: bool = False) -> list:
    """
    Choose up to n well-spread, legible frames. Returns [(seconds, Path), ...].

    Two passes: decode cheap small candidates to score them, then re-extract
    only the winners at full resolution. Scoring on the small copies is ~40x
    less pixel work and the verdicts agree - contrast and clipping both survive
    a downscale.

    require_clean=True returns ONLY frames with no overlay of the piece's own,
    and returns FEWER THAN n rather than filling the gap with a frame that has
    a caption or a stats card on it. Callers that draw their own typography
    want this: the ice piece has 6 caption-free windows, one of them is the
    white-out at the end, so a 6-slide deck that insists on 6 frames ends up
    printing "Why it matters" straight across a table of densities. A 4-slide
    carousel is a normal carousel; a 6-slide one with two unreadable slides is
    not. The caller shortens the deck to fit.
    """
    times, dur = _candidate_times(video, wd, piece_html, fps)
    scan = wd / 'scan'
    scan.mkdir(parents=True, exist_ok=True)

    scored = []
    for i, (t, clean) in enumerate(times):
        p = scan / f'c{i:03d}.jpg'
        common.run_logged(
            ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{t:.2f}', '-i', str(video),
             '-frames:v', '1', '-vf', 'scale=304:540', '-q:v', '4', str(p)],
            tag=f'slides.scan{i}')
        if not p.exists():
            continue
        with Image.open(p) as im:
            usable, s = _score(im)
        scored.append({'t': t, 'usable': usable, 'clean': clean,
                       'score': s + (CLEAN_BONUS if clean else 0.0)})

    if not scored:
        raise RuntimeError(f'no candidate frames decoded from {video}')

    usable = [c for c in scored if c['usable']]
    if require_clean:
        clean = [c for c in usable if c['clean']]
        logger.info('slides: %d/%d usable candidates are overlay-free',
                    len(clean), len(usable))
        usable = clean
        n = min(n, len(usable))
    elif len(usable) < n:
        # Not clean-required, so a frame with a caption on it beats a frame
        # that is dead or blown out.
        logger.warning('slides: only %d/%d candidates are usable '
                       '(dead or blown out) - relaxing to best-effort',
                       len(usable), len(scored))
        usable = sorted(scored, key=lambda c: -c['score'])[:max(n, 1)]
        usable.sort(key=lambda c: c['t'])
    if not usable or n <= 0:
        return []

    # Spread: split the usable candidates into n contiguous buckets by time and
    # take the highest-scoring frame in each. This keeps the deck in narrative
    # ORDER (a carousel that jumps backwards through the argument reads as
    # nonsense) while still refusing the bad frames inside each bucket.
    picks, size = [], len(usable) / n
    for i in range(n):
        bucket = usable[int(i * size):max(int((i + 1) * size), int(i * size) + 1)]
        if bucket:
            picks.append(max(bucket, key=lambda c: c['score']))

    out = []
    full = wd / 'full'
    full.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(picks, 1):
        dst = full / f'f{i}.png'
        # -ss BEFORE -i is the fast seek; accurate enough at 30fps and it does
        # not decode the whole file up to the timestamp for every frame.
        common.run_logged(
            ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{min(c["t"], max(dur - 0.1, 0)):.2f}',
             '-i', str(video), '-frames:v', '1', str(dst)],
            tag=f'slides.grab{i}')
        if dst.exists():
            out.append((c['t'], dst))

    logger.info('slides: picked %d frames at %s (of %d candidates, %d usable)',
                len(out), [f'{t:.1f}s' for t, _ in out], len(scored),
                sum(1 for c in scored if c['usable']))
    return out


def best_cover_ms(video: Path, wd: Path, piece_html: str = '',
                  fps: float = 30.0) -> int:
    """
    Timestamp of the single most legible frame, for videoCoverMilliseconds.

    The cover IS the thumbnail, so it gets the best frame in the piece rather
    than frame 0 - and Metricool takes a millisecond offset, so nothing has to
    be uploaded for it.
    """
    picks = pick_frames(video, wd, 1, piece_html, fps)
    return int(picks[0][0] * 1000) if picks else 0


# ============================================================
# composition
# ============================================================
def _slide(frame: Path, title: str, body: str, index: int, total: int,
           dst: Path) -> Path:
    """
    One 1080x1350 slide: the render, darkened, with the copy over the bottom.

    Full-bleed rather than a frame-in-a-box because the pieces are lit against
    near-black space, so a letterboxed layout would put grey bars either side of
    something that already reads as edge-to-edge.
    """
    with Image.open(frame) as src:
        img = src.convert('RGB')
        # Cover-crop 1080x1920 -> 1080x1350, biased ABOVE centre: the pieces put
        # their subject in the upper two thirds and their own captions at the
        # bottom, and a centred crop would keep the caption and lose the subject.
        scale = max(SLIDE_W / img.width, SLIDE_H / img.height)
        img = img.resize((round(img.width * scale), round(img.height * scale)),
                         Image.LANCZOS)
        top = max(0, round((img.height - SLIDE_H) * 0.34))
        img = img.crop((max(0, (img.width - SLIDE_W) // 2), top,
                        max(0, (img.width - SLIDE_W) // 2) + SLIDE_W,
                        top + SLIDE_H))

    draw = ImageDraw.Draw(img, 'RGBA')
    f_title = _font('bold', 62)
    f_body = _font('regular', 38)
    f_num = _font('bold', 28)

    margin = 72
    max_w = SLIDE_W - 2 * margin
    t_lines = _wrap(draw, title, f_title, max_w) if title else []
    b_lines = _wrap(draw, body, f_body, max_w) if body else []

    t_h, b_h = 74, 50
    block_h = len(t_lines) * t_h + (18 if t_lines and b_lines else 0) + len(b_lines) * b_h
    block_top = SLIDE_H - margin - block_h

    # Scrim. A linear ramp rather than a flat box so the image is not visibly
    # cut in half; it starts well above the text so ascenders never sit on the
    # boundary.
    ramp_top = max(0, block_top - 200)
    for y in range(ramp_top, SLIDE_H):
        a = (y - ramp_top) / max(SLIDE_H - ramp_top, 1)
        draw.line([(0, y), (SLIDE_W, y)], fill=(0, 0, 0, int(232 * a ** 1.4)))

    y = block_top
    for ln in t_lines:
        draw.text((margin, y), ln, font=f_title, fill=(255, 255, 255))
        y += t_h
    if t_lines and b_lines:
        y += 18
    for ln in b_lines:
        draw.text((margin, y), ln, font=f_body, fill=(226, 232, 240))
        y += b_h

    # Slide counter, so a viewer knows there is more to swipe to.
    if total > 1:
        label = f'{index}/{total}'
        w = draw.textlength(label, font=f_num)
        draw.rounded_rectangle(
            [SLIDE_W - margin - w - 26, margin - 6,
             SLIDE_W - margin + 10, margin + 42],
            radius=18, fill=(0, 0, 0, 150))
        draw.text((SLIDE_W - margin - w - 8, margin + 2), label,
                  font=f_num, fill=(255, 255, 255))

    # quality=88 lands a 1080x1350 render around 250-400 KB. Instagram
    # re-encodes anyway; what matters is not handing it artefacts to amplify.
    img.save(dst, 'JPEG', quality=88, optimize=True, progressive=True)
    return dst


def build_slides(video: Path, wd: Path, deck: list, piece_html: str = '',
                 fps: float = 30.0) -> list:
    """deck = [{title, body}] -> [Path]. Returns [] when there is no copy."""
    if not deck:
        logger.warning('slides: no slide copy in the bundle - skipping carousel')
        return []
    deck = deck[:N_SLIDES]
    frames = pick_frames(video, wd, len(deck), piece_html, fps, require_clean=True)
    if len(frames) < MIN_SLIDES:
        # Better no carousel than a carousel of unreadable slides. The reel,
        # story and still are unaffected; only this format drops.
        logger.warning('slides: only %d overlay-free frames (need %d) - '
                       'skipping the carousel for this piece',
                       len(frames), MIN_SLIDES)
        return []
    if len(frames) < len(deck):
        # The deck is written so slide 1 is the hook and the LAST slide is the
        # payoff, so a short deck keeps the front and the end and drops from the
        # middle, where the slides are interchangeable build steps.
        keep = [deck[0]] + deck[1 + len(deck) - len(frames):]
        logger.warning('slides: %d frames for %d slides - dropping %d middle '
                       'slide(s), keeping the hook and the payoff',
                       len(frames), len(deck), len(deck) - len(frames))
        deck = keep

    out_dir = wd / 'slides'
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, (spec, (_, frame)) in enumerate(zip(deck, frames), 1):
        paths.append(_slide(frame, spec.get('title', ''), spec.get('body', ''),
                            i, len(deck), out_dir / f's{i}.jpg'))
    logger.info('slides: built %d slides', len(paths))
    return paths


def build_image(video: Path, wd: Path, deck: list, piece_html: str = '',
                fps: float = 30.0) -> Path:
    """
    The single still post. Slide 1's copy on the best frame in the piece.

    Slide 1 is used because it is the only line in the deck written to work with
    no context, which is exactly the requirement for a post that stands alone.
    """
    spec = (deck or [{}])[0]
    # Clean-required for the same reason as the carousel: this draws its own
    # headline over the frame.
    frames = (pick_frames(video, wd, 1, piece_html, fps, require_clean=True)
              or pick_frames(video, wd, 1, piece_html, fps))
    if not frames:
        return None
    dst = wd / 'image.jpg'
    return _slide(frames[0][1], spec.get('title', ''), spec.get('body', ''),
                  1, 1, dst)


def build_story(video: Path, wd: Path) -> Path:
    """
    First STORY_SECONDS of the piece, 1080x1920, audio faded out at the end.

    The opening is used rather than a highlight because the hook is written to
    be the first thing said, and a story is a teaser for the reel, not a
    substitute for it. The fade is what stops it ending on a hard cut mid-word.
    """
    dst = wd / 'story.mp4'
    dur = _probe_duration(video)
    n = min(STORY_SECONDS, max(dur - 0.2, 1.0))
    common.run_logged(
        ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(video), '-t', f'{n:.2f}',
         '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,'
                'pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black',
         '-af', f'afade=t=out:st={max(n - 1.2, 0):.2f}:d=1.2',
         '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21',
         '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
         '-movflags', '+faststart', str(dst)],
        tag='slides.story')
    if not dst.exists() or dst.stat().st_size == 0:
        raise RuntimeError(f'story encode produced nothing at {dst}')
    logger.info('slides: story %.1fs %.1f MB', n, dst.stat().st_size / 1e6)
    return dst
