# iris-motion

A second, parallel video pipeline alongside the existing Iris-flow STEM and story
pipelines. It renders **motion-video** pieces: a real Three.js scene drawn
frame-by-frame in headless Chrome, narrated with Gemini TTS, gated, and encoded
to MP4.

It shares nothing with `IrisFlowStack` except two read-only things — the
`iris-flow/api-keys` secret and the VPC. New bucket, new ECR repo, new Batch
compute environment, new state machine. **Manually triggered; no EventBridge
schedule.**

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:482625028438:stateMachine:iris-motion-pipeline \
  --name run-$(date +%s) \
  --input '{"video_id":"demo01","topic":"why the sky is blue","target_duration":60,
            "force_seed":false,"seed_fallback":true,
            "schedule_time":"2026-07-29T15:00:00+00:00",
            "include_youtube":false,"include_tiktok":false,
            "post_carousel":false,"post_story":false,"post_image":false}'
```

## Shape

```
Prep(Batch) → PlanShards(λ) → Map×24[ Render(Batch) ] → Stitch(Batch) → Notify(λ→SES)
                                                                            ↑
                                              a global catch also routes failures here
```

`prep` picks a topic, authors the scene, synthesises narration, fits it to the
beats, and **probe-renders three frames to prove the JS runs** before 24 shards
are committed to it. `plan_shards` splits the frame range. `stitch` gates with
`check.py`, encodes, and muxes audio. `notify` presigns the MP4 and emails it.

## The measurement that shapes everything

Fargate has no GPU, so WebGL runs on SwiftShader. Measured, not assumed:

| | |
|---|---|
| 24 frames, ANGLE/Metal on an M-series Mac | **1.9 s** |
| same 24 frames, SwiftShader | **70.2 s** — 37× slower |
| **on a real 4-vCPU Fargate task, ss=16** | **18.9 s/frame** — another 9.2× |

That last row is the one that matters and it is only knowable by running it on
Fargate. A 1440-frame piece at ss16 is **7.6 hours** in one container. So the
frame range is sharded 24 ways, which is nearly free: cost is total
vCPU-seconds and does not change with shard count, only wall-clock does.

Settled at **ss=12, 24 shards** → 14.2 s/frame, ~14 min per shard.

## Cost per 60 s video

| | on-demand | spot (what runs) |
|---|---|---|
| render, 1440 frames @ ss12 | $1.12 | **$0.34** |
| authoring, one cached Opus 5 call | $0.85 | $0.85 |
| TTS (7 segments) | ~$0.02 | ~$0.02 |
| Step Functions, Lambda, S3 | ~$0.03 | ~$0.03 |
| **total** | $2.02 | **~$1.24** |

Budget is $3.00. The guards that keep it there:

- **One model call, cached.** The 45 KB template is a cached prompt prefix, so
  repeat calls read it at 0.1× input price.
- **Authoring attempts are a TOTAL budget** (3 across all providers), not
  per-provider — that was a 6× multiplier before it was capped, and
  `AUTHOR_COST_CEILING_USD` is a hard stop on top.
- **A terminal `EXIT` retry rule** on every Batch job definition. Batch's
  `evaluateOnExit` can only *add* retries: with only RETRY rules listed, a
  deterministic application failure is still retried 3×. That was another 3×
  on the largest cost term.
- **Frames expire after 3 days** via an object-tag lifecycle rule (~1.4 GB per
  video otherwise retained forever). A prefix filter cannot express
  `jobs/*/frames/`, so the shards tag their uploads.

## Authoring

Claude Opus 5 primary → Gemini fallback → bundled seed piece. Whichever ran is
recorded in `plan.json.authored_by`, so a silent downgrade is visible.

The model returns a list of `{find, replace}` edits against the template, not a
whole file — emitting 45 KB would be ~12k output tokens of harness copied
verbatim, and every copy is a chance to corrupt it. Edits are applied with a
uniqueness assert, so a stale anchor fails loudly instead of writing to the
wrong place.

**`FORCE_SEED=true`** on the execution input skips authoring entirely. That is
how the infrastructure is tested independently of the models — otherwise a
render regression and a bad scene look identical from outside.

The Claude path is **live and verified** on `claude-opus-5`. (It briefly
returned `credit balance is too low` during the build; credit was added and the
same key now authenticates and authors.)

## Narration

With a voice, the picture is cut to the audio, not the reverse — except for the
seed, whose `pose()` is keyed to fixed frame numbers, so there the audio is
fitted into the beats instead (`picture_locked: true`).

Measured: Algenib reads at **~1.25 words/s** with this style preamble, far
slower than the ~2.2 w/s of documentary narration. Gemini has no speed control,
so pacing is post-hoc `atempo`, clamped to [0.85, 1.15] — past that the pitch
artefacts are audible. A segment that still overruns after clamping is **logged
as a script that is too long**, not silently mangled. The first seed script ran
175 s of speech into a 60 s picture; every segment overlapped the next.

## Operating notes

- **The compute environment cannot be updated in place.** Batch rejects an
  in-place change to a Fargate CE even for `maxvCpus`. Changing the fan-out
  means bumping the version suffix on its logical id (`MotionComputeEnvV2`) so
  CloudFormation replaces it. Only do that with no jobs running.
- **The ECR repo is imported, not created**, because the image has to be pushed
  before the first execution and CloudFormation cannot wait for a push.
- **The VPC is imported** from `IrisFlowStack`. This account is at its VPC limit
  (5/5) and at the internet-gateway limit; creating one fails with
  `ServiceLimitExceeded`.
- Deploy order: `docker/build_and_push.sh` → `cdk deploy` → start an execution.

## Layout

```
app/          prep.py render_shard.py stitch.py worker.py common.py tts.py
              render.mjs serve.mjs check.py narrate.py   (the motion-video toolchain)
              piece_template.html seed_aurora.html seed_narration.json data/
              lambdas/plan_shards.py lambdas/notify.py
docker/       Dockerfile package.json build_and_push.sh
cdk/          lib/iris-motion-stack.ts bin/app.ts
CONTRACT.md   the build contract these were written against
```

## Verified on 2026-07-27

| | |
|---|---|
| stack | `IrisMotionStack`, 27 resources, us-east-1 |
| image | `iris-motion-renderer:latest`, **543 MB** (vs 5+ GB for the sibling image) |
| end-to-end runs | 3 (1 seed, 1 Spot-interrupted, 1 resumed to success) |
| final MP4 | h264 High / yuv420p / 1080×1920 / 24 fps / 1440 frames / 60.000 s / AAC mono |
| gates | all passed on the full 1440-frame pass |
| emails | 3 delivered via SES |
| measured compute | 51.95 vCPU-hr total → **$0.77 on Spot** for everything above |
| **per video** | **~$0.27 compute + $0.85 authoring ≈ $1.17** |

### Cost after the multi-format change

The companion formats are close to free because they consume a video that
already exists — the expensive terms (one Opus 5 authoring call, one T4 render)
are unchanged and are paid once per scene, not once per post.

| item | per run | note |
|---|---|---|
| authoring + render + stitch | ~$1.17 | unchanged |
| per-platform copy call | ~$0.05 | measured: 1440 output tokens on Opus 5 |
| carousel + story + still assets | ~$0.01 | ffmpeg + Pillow inside postprocess |
| **per scene, now 1-4 posts** | **~$1.23** | vs ~$1.17 for a single post |
| weekly compilation | ~$0.45 | one Claude call, ~90 s of TTS, one encode |

At 5 scenes/day that is about **$6.20/day**, against $5.85 before, for roughly
9 posts a day instead of 5. The per-POST cost drops from ~$1.17 to ~$0.69.

Known deviations from CONTRACT.md, deliberate:

- **The seed renders at 24 fps, not 30.** Its `pose()` is keyed to fixed frame
  numbers, so re-timing it means rescaling every beat and camera key. The
  authored path is 30 fps; `concatenate_videos` normalises either way.
- **`hook` overruns its 6.0 s slot by 0.9 s** even at maximum atempo. Logged as
  "the script is too long for this beat" rather than pitch-shifted further.
