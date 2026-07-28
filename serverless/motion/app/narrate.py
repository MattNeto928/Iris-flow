#!/usr/bin/env python3
"""
Narration -> beat table. The piece is cut to the voice, not the other way round.

Without voiceover you pick beat lengths and they are right by definition. With
voiceover the narration has a real, measured duration and the picture has to
match it, so the ordering inverts:

    write narration -> synthesise -> MEASURE -> derive BEATS -> author -> render -> mux

Guessing beat lengths from a word count and fixing them later means re-timing
every caption and camera key after the audio exists. Deriving them costs one
command.

    # dry run -- no API calls, exercises the timing math with known durations
    python3 narrate.py --script narration.json --dry-run --fps 30

    # real synthesis through the Iris-flow TTS client
    python3 narrate.py --script narration.json --fps 30 --out data/

narration.json is a list of segments:

    [{"id": "hook",  "text": "Nothing up there is burning."},
     {"id": "cause", "text": "It starts at the sun.", "speed": 1.05}]

Writes beats.json (frame ranges + the text that owns them), narration.wav (the
segments concatenated in order), and prints the BEATS literal to paste into
piece.html.
"""

import argparse
import json
import os
import subprocess
import sys


def beats_from_durations(segments, fps, lead=0.0, gap=0.0, tail=0.0):
    """
    Map measured segment durations onto integer frame ranges.

    Pure and testable -- this is the part that is easy to get subtly wrong.

    Boundaries are computed from CUMULATIVE time and rounded once, never by
    accumulating per-beat frame counts: rounding each beat independently drifts,
    and by the tenth beat the picture is a third of a second off the voice.

    Ranges are inclusive and tile with no gap and no overlap: beat N ends at the
    frame before beat N+1 starts, which is what beatAt() in the template expects.
    """
    beats, t = [], lead
    for i, seg in enumerate(segments):
        # The first beat owns the lead-in silence rather than starting after it.
        # Frame 0 is the thumbnail and must carry content, and beatAt() has to
        # find an owner for every frame -- a gap at the head breaks both.
        start = 0 if i == 0 else round(t * fps)
        t += seg["duration"] + (gap if i < len(segments) - 1 else 0.0)
        end = round(t * fps) - 1
        if end < start:                      # a segment shorter than one frame
            end = start
        beats.append({"id": seg["id"], "from": start, "to": end,
                      "text": seg.get("text", ""),
                      "audio_start": None, "duration": seg["duration"]})
    total_frames = beats[-1]["to"] + 1 + round(tail * fps) if beats else 0
    # audio_start is where this segment's WAV sits in the concatenated track --
    # lead-in silence and inter-segment gaps are part of the track, not offsets
    # you apply later.
    at = lead
    for i, b in enumerate(beats):
        b["audio_start"] = round(at, 4)
        at += b["duration"] + (gap if i < len(beats) - 1 else 0.0)
    return beats, total_frames


def synthesise(segments, voice, outdir):
    """
    Call the Iris-flow TTS client. Kept behind one function so the timing math
    above stays runnable without an API key.

    generate_voiceover(text, voice, speed) -> (path, duration_seconds)
    """
    root = os.environ.get("IRIS_ROOT", os.path.expanduser(
        "~/Documents/SoftwareApplications/Iris-flow"))
    sys.path.insert(0, os.path.join(root, "serverless"))
    try:
        import asyncio
        from src.services.tts_client import generate_voiceover
    except ImportError as e:
        sys.exit(f"could not import the Iris-flow TTS client from {root}: {e}\n"
                 f"Set IRIS_ROOT, or use --dry-run to work on timing first.")

    async def run():
        out = []
        for i, seg in enumerate(segments):
            path, dur = await generate_voiceover(
                seg["text"], voice=voice, speed=seg.get("speed", 1.0),
                output_filename=f"vo_{i:02d}_{seg['id']}.wav")
            print(f"  {seg['id']:<14} {dur:6.2f}s  {path}")
            out.append((path, dur))
        return out
    return asyncio.run(run())


def concat_wavs(paths, gap, lead, dest):
    """Concatenate with silence padding, via ffmpeg. 24 kHz mono, as Gemini emits."""
    parts, filt = [], []
    for i, p in enumerate(paths):
        parts += ["-i", p]
    pre = f"aevalsrc=0:d={lead}:s=24000:c=mono[lead];" if lead > 0 else ""
    chain = "[lead]" if lead > 0 else ""
    for i in range(len(paths)):
        filt.append(f"[{i}:a]aresample=24000,aformat=sample_fmts=s16:channel_layouts=mono[a{i}]")
        chain += f"[a{i}]"
        if gap > 0 and i < len(paths) - 1:
            filt.append(f"aevalsrc=0:d={gap}:s=24000:c=mono[g{i}]")
            chain += f"[g{i}]"
    n = chain.count("[")
    graph = pre + ";".join(filt) + f";{chain}concat=n={n}:v=0:a=1[out]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *parts,
                    "-filter_complex", graph, "-map", "[out]", dest], check=True)
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True, help="narration JSON")
    ap.add_argument("--fps", type=int, default=30, help="30 for Iris-flow, 24 standalone")
    ap.add_argument("--voice", default="Algenib")
    ap.add_argument("--out", default="data")
    ap.add_argument("--lead", type=float, default=0.4, help="silence before the first word")
    ap.add_argument("--gap", type=float, default=0.25, help="silence between segments")
    ap.add_argument("--tail", type=float, default=0.8, help="frames held after the last word")
    ap.add_argument("--dry-run", action="store_true",
                    help="skip TTS; use a 'duration' field already in the script")
    args = ap.parse_args()

    segments = json.load(open(args.script))
    os.makedirs(args.out, exist_ok=True)

    if args.dry_run:
        for s in segments:
            if "duration" not in s:
                # ~2.6 words/second is Algenib at the pipeline's default atempo.
                s["duration"] = round(len(s["text"].split()) / 2.6, 2)
    else:
        results = synthesise(segments, args.voice, args.out)
        for s, (path, dur) in zip(segments, results):
            s["duration"], s["path"] = dur, path
        concat_wavs([s["path"] for s in segments], args.gap, args.lead,
                    os.path.join(args.out, "narration.wav"))

    beats, frames = beats_from_durations(segments, args.fps, args.lead, args.gap, args.tail)
    json.dump({"fps": args.fps, "frames": frames, "beats": beats},
              open(os.path.join(args.out, "beats.json"), "w"), indent=2)

    print(f"\nconst FPS = {args.fps};")
    print(f"const FRAMES = {frames};        // {frames/args.fps:.2f}s")
    print("const BEATS = [")
    for b in beats:
        # Commas belong to each field BEFORE padding -- padding first produces
        # `from: 0     to: 145` which looks aligned and is a syntax error.
        ident, fr, to = repr(b["id"]) + ",", f"{b['from']},", f"{b['to']},"
        print(f"  {{ id: {ident:<16} from: {fr:<6} to: {to:<6} "
              f"bloom: 1.00 }},   // {b['text'][:46]}")
    print("];")
    if frames / args.fps > 62:
        print(f"\nWARNING: {frames/args.fps:.1f}s. Cut narration, do not speed it up -- "
              f"atempo past 1.15 lands in the pitch-artifact zone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
