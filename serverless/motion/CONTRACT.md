# iris-motion — build contract

A second, parallel pipeline alongside the existing Iris-flow STEM/story pipelines.
It renders **motion-video** pieces: real 3D scenes drawn frame-by-frame in headless
Chrome (Three.js), with narration, then encoded to MP4.

**It must not touch `IrisFlowStack`.** New stack, new ECR repo, new bucket, new
Batch compute environment. The only shared resources are read-only:
`iris-flow/api-keys` (Secrets Manager) and SES.

## Measured facts that drive the design

| fact | value | consequence |
|---|---|---|
| WebGL under SwiftShader (no GPU on Fargate) | **37× slower** than ANGLE/Metal | rendering must be sharded |
| render cost per subsample | ~0.128 s/frame/subsample + 0.09 s | `ss=16` → 2.14 s/frame |
| 1440 frames @ ss16, one task | ~36 min | 8 shards → ~4.5 min each |
| Fargate 4 vCPU + 8 GB, on-demand | $0.04048/vCPU-hr, $0.004445/GB-hr | full render ≈ **$0.15** |
| Claude Opus 5 | $5/M in, $25/M out; cache read 0.1× | one cached call ≈ **$0.85** |

**Budget: < $3.00/video.** Target ≈ $1.05. The LLM call is the dominant term, so
it happens **once** with a cached prompt prefix, and retries are capped at 2.

## S3 layout — bucket `iris-motion-<account>`

```
jobs/<video_id>/
  plan.json           written by prep; read by plan-shards, stitch, notify
  piece.html          the authored scene, BEATS/FRAMES already injected
  narration.wav       full mixed narration track (24 kHz mono)
  beats.json          {fps, frames, beats:[{id,from,to,text,audio_start,duration}]}
  frames/f0000.png    one per frame, written by render shards
  out/video.mp4       final deliverable
  out/gates.txt       check.py output
```

Companion assets are NOT kept here. They are written straight into the public
bucket, because the only consumer is Metricool's fetcher and a private copy
would have to be copied out again to be of any use:

```
s3://iris-flow-videos-<account>/motion/
  <video_id>.mp4              the reel
  <video_id>/s1.jpg .. s6.jpg carousel slides, 1080x1350
  <video_id>/image.jpg        the single still
  <video_id>/story.mp4        15s story teaser
  compilations/<id>.mp4       the weekly YouTube long-form cut
```

`plan.json`:
```json
{"video_id":"...","topic":"...","fps":30,"frames":1440,"subsamples":16,
 "shards":8,"authored_by":"claude|gemini|fallback","cost":{"author_usd":0.0},
 "narration":[{"id":"hook","text":"..."}],"created_at":"..."}
```

## Jobs — all in ONE container, dispatched by `JOB_TYPE`

| JOB_TYPE | vCPU/MiB | does | env in |
|---|---|---|---|
| `prep` | 2 / 4096 | topic → narration + scene → TTS → beats → inject → **probe-render 3 frames to prove the JS runs** → upload | `VIDEO_ID`, `TOPIC`, `TARGET_DURATION` |
| `render` | 4 / 8192 | render frames `[FRAME_FROM, FRAME_TO]` → S3 | `VIDEO_ID`, `FRAME_FROM`, `FRAME_TO` |
| `stitch` | 2 / 8192 | pull frames → `check.py` gates → encode + mux audio → upload | `VIDEO_ID` |
| `postprocess` | 2 / 4096 | public copy → per-platform copy → carousel/story/still assets → up to 4 Metricool posts | `VIDEO_ID`, `SCHEDULE_TIME`, `INCLUDE_*`, `POST_*`, `DRY_RUN` |
| `compile` | 4 / 8192 | pick 4-6 published pieces → theme + bridges → TTS → letterbox to 1920x1080 → concat → post to YouTube | `VIDEO_ID`, `DRY_RUN` |

## Formats and where they go

One authored scene produces four assets and up to four posts. The per-format
daily caps live on the EventBridge rules, not in a counter: exactly one rule/day
sets `post_carousel`, one sets `post_image`, two set `post_story`.

| format | media | networks | when |
|---|---|---|---|
| reel | `video.mp4` | IG, TikTok, YouTube Short, FB | the slot's own time |
| story | `story.mp4` (15s) | IG | reel + 90 min |
| carousel | `s1..s6.jpg` | IG, TikTok photo post | next day 11:00 ET |
| image | `image.jpg` | IG, FB | next day 09:00 ET |
| longform | `compilations/*.mp4` | YouTube (`type=VIDEO`) | Thu, ~15:40 ET |

Carousel and still frames are chosen from the piece's OWN caption-free windows,
parsed out of `piece.html` (`.play(frame,a,b,c,d)` and `band(a,b,c,d)` both mean
"visible from a to d"). A slide draws its own headline, so a frame that still
has the piece's caption or data card on it is rejected. If fewer than 3 clean
frames exist the carousel is skipped rather than shipped unreadable.

`prep` is self-validating: if the authored scene throws a JS error, it retries the
model with the error text, max 2 retries, then falls back to the bundled seed piece.
A pipeline that emits a broken scene 20 minutes later is worse than one that
notices in 30 seconds.

## Step Functions — `iris-motion-pipeline`

```
Prep(Batch) → PlanShards(Lambda) → Map[Render(Batch)] x8 → Stitch(Batch) → Notify(Lambda)
                                                                              ↓
                                                              SES → mattneto928@gmail.com
```

- `Notify` also runs on the failure path (`.addCatch`) so a broken run still emails.
- `Map` `maxConcurrency: 8`.
- Every state has a retry on `Batch.AWS.Batch.TooManyRequestsException` and spot reclaim.

## Hard rules

1. **`ss=16`, `fps=30`.** 30 because Iris-flow normalises segments to 1080×1920@30;
   24 would judder on an uneven 5:4 pulldown.
2. **Render shards must not clear the output dir** — they write into a shared
   prefix. Use `--only` semantics, never a full-render clear.
3. **Frame numbers come from filenames**, never list position.
4. Encode with `-i frames/f%04d.png`, never a glob.
5. **Never print an API key.** Load from Secrets Manager into env, never log.
6. Chrome flags on Linux: `--use-gl=angle --use-angle=swiftshader
   --enable-unsafe-swiftshader --no-sandbox --disable-dev-shm-usage`.
   `--no-sandbox` is required in a container; `/dev/shm` is 64 MB by default and
   Chrome will crash without the second flag.
7. The final MP4 must be `h264 High / yuv420p / 1080×1920 / 30 fps` with AAC audio,
   so `concatenate_videos` in the existing pipeline accepts it unchanged.

## Email

SES (`mattneto928@gmail.com` is a verified identity, account is out of sandbox —
**do not use SNS**, its topic has zero confirmed subscriptions). Send a presigned
S3 URL, 7-day expiry, plus the gate output and the measured cost.
