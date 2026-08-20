# iris-motion

A second, parallel video pipeline alongside the existing Iris-flow STEM and story
pipelines. It renders **motion-video** pieces: a real Three.js scene drawn
frame-by-frame in headless Chrome, narrated with Gemini TTS, gated, and encoded
to MP4.

It shares nothing with `IrisFlowStack` except two read-only things — the
`iris-flow/api-keys` secret and the VPC. New bucket, new ECR repo, new Batch
compute environment, new state machine.

**Scheduled, 3× daily.** Three EventBridge rules fire the orchestrator Lambda at
13:00, 15:00 and 19:00 UTC (10am, 12pm, 4pm ET), and a fourth targets the
compile state machine on Thursdays at 17:00 UTC. Each rule carries the
companion-format flags, so the per-format daily cap lives on the rule rather
than in a counter someone has to reset — see `IrisMotionStack`. The orchestrator
pops one topic off the shared `iris-flow-topic-queue` and skips the slot
entirely if the queue is empty.

A manual run is still the way to test, and bypasses the queue:

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
Prep(Batch) → PlanShards(λ) → Map[ Render(Batch/GPU) ] → Stitch(Batch) → Postprocess(Batch) → Notify(λ→SES)
                                                                                                  ↑
                                                                a global catch also routes failures here
```

VERIFIED on 2026-08-20, the six states an execution actually enters:
`PrepJob → PlanShards → RenderJob → StitchJob → PostprocessJob → NotifySuccess`.
`Postprocess` is the one that publishes — public S3 copy, per-platform copy,
companion assets, then up to four Metricool posts — so leaving it off this
diagram hid the entire posting half of the pipeline.

`prep` picks a topic, authors the scene, synthesises narration, fits it to the
beats, and **probe-renders three frames to prove the JS runs** before 24 shards
are committed to it. `plan_shards` splits the frame range. `stitch` gates with
`check.py`, encodes, and muxes audio. `notify` presigns the MP4 and emails it.

## The measurement that shapes everything

**Superseded by the GPU path — kept because it explains why sharding exists.**
Rendering now runs on a single g4dn GPU task (`GpuRenderJobDef`), so the numbers
below describe the Fargate/SwiftShader era, not what runs today. MEASURED on
2026-08-20: `fps 30, frames 1920, subsamples 24, shards 1` — one shard, and ss
went UP to 24 rather than down, because a real GPU makes the subsample count
cheap and the 24-way fan-out unnecessary.

Fargate has no GPU, so WebGL ran on SwiftShader. Measured, not assumed:

| | |
|---|---|
| 24 frames, ANGLE/Metal on an M-series Mac | **1.9 s** |
| same 24 frames, SwiftShader | **70.2 s** — 37× slower |
| **on a real 4-vCPU Fargate task, ss=16** | **18.9 s/frame** — another 9.2× |

That last row is the one that mattered and it was only knowable by running it on
Fargate. A 1440-frame piece at ss16 is **7.6 hours** in one container. So the
frame range was sharded 24 ways, which is nearly free: cost is total vCPU-seconds
and does not change with shard count, only wall-clock does.

That settled at **ss=12, 24 shards** → 14.2 s/frame, ~14 min per shard. The CPU
fan-out path and its job definition still exist; the state machine routes to the
GPU one.

## Cost per 60 s video

| | on-demand | spot (what runs) |
|---|---|---|
| render, 1440 frames @ ss12 | $1.12 | **$0.34** |
| authoring, one cached Opus 5 call | $0.85 | $0.85 |
| TTS (7 segments) | ~$0.02 | ~$0.02 |
| Step Functions, Lambda, S3 | ~$0.03 | ~$0.03 |
| **total** | $2.02 | **~$1.24** |

**That authoring row is the DESIGN figure, not the measured one.** It costs one
cached call; a real run pays for the preflight repair loop on top. MEASURED on
2026-08-20: `author_usd` **$2.09** + $0.05 captions, i.e. 2.5× the row above and
most of the $3.00 budget on its own. Two of that run's repair cycles returned
edits that left the piece unparseable (`SyntaxError`) and were reverted, paying
Opus 5 prices for nothing. Budget the loop, not the first call.

Budget is $3.00. The guards that keep it there:

- **One model call, cached.** The 45 KB template is a cached prompt prefix, so
  repeat calls read it at 0.1× input price. Note this describes the AUTHORING
  call; the repair loop adds up to 6 more cycles on top, which is where the
  spend above came from.
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

**Claude Opus 5 on every attempt**, then the bundled seed piece. Whichever ran
is recorded in `plan.json.authored_by`, so a silent downgrade is visible.

There is no Gemini authoring fallback. It used to take the third and last
attempt as a provider hedge and has been **deleted**, not disabled: on the two
scheduled runs where it was ever actually reached it failed both times with its
own JSON errors (`Expecting ',' delimiter`, `Extra data`) while burning the last
attempt, so both slots published nothing. It also asked for
`response_mime_type="application/json"` against a block-delimited format that no
longer produces JSON, so it could not have worked again without a rewrite. All
three attempts are now Opus 5, each one fed the PREVIOUS error — a parse
failure, a bad anchor, or the renderer's own stack trace — which is what makes a
retry meaningfully different from a re-roll. Gemini is still the TTS fallback in
`app/tts.py`, which is a genuinely independent failure domain.

Scheduled runs pin `force_seed` and `seed_fallback` both false, so a scheduled
slot is Opus 5-authored or it is skipped. The seed is one fixed aurora piece;
falling back to it would republish the same video under whatever topic came off
the queue, and an empty slot is cheaper than that.

The model returns a list of `{find, replace}` edits against the template, not a
whole file — emitting 45 KB would be ~12k output tokens of harness copied
verbatim, and every copy is a chance to corrupt it. Edits are applied with a
uniqueness assert, so a stale anchor fails loudly instead of writing to the
wrong place.

**`FORCE_SEED=true`** on the execution input skips authoring entirely. That is
how the infrastructure is tested independently of the models — otherwise a
render regression and a bad scene look identical from outside.

The Claude path is **live and verified** on `claude-opus-5`, most recently on
2026-08-20 (`authored_by: claude`, gates passed, post booked). It briefly
returned `credit balance is too low` during the build; credit was added and the
same key still authenticates and authors.

### Authoring cost is dominated by the repair loop, not the first call

The one cached authoring call is ~$0.85, but that is not what a run costs.
MEASURED on 2026-08-20: `author_usd` **$2.09** plus $0.05 of captions, against a
$3.00/video budget. The first call was not the expensive part — the preflight
repair loop was, and two of its cycles paid Opus 5 prices for nothing because
the edits they returned left the piece unparseable (`SyntaxError: missing )
after argument list`, `SyntaxError: Invalid or unexpected token`) and were
reverted. Both reverts followed `edit N SKIPPED: superseded` warnings, so the
suspect is a kept edit being applied to a region an earlier edit had already
rewritten. `AUTHOR_COST_CEILING_USD` is the hard stop that keeps this inside
budget; it is doing real work, not sitting idle.

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

## Verified on 2026-08-20 (after a 20-day outage)

The pipeline published nothing between **2026-07-31 and 2026-08-20**. Three
causes in sequence, each with its own fix, recorded here because every one of
them was invisible from outside:

| window | what happened |
|---|---|
| Jul 31 – Aug 1 | Runs rendered a finished MP4 and published nothing. The blacks-lifted gate was `max() > 24.0`, so ONE frame over the line blocked a whole piece; with `REQUIRE_GATES` on, postprocess set `blocked_gates_failed`. Jul 31 deserved it (9.13% of frames lifted, a 126-frame run — an empty scene). Aug 1 did not (0.32%, longest run 4 frames = 0.13 s). The gate now measures the FRACTION of affected frames. |
| Aug 2 – Aug 10 | `prep` exited 1 after ~28 s, 15 runs, no artifacts. Root cause **unrecoverable**: container log retention was 7 days and by the time anyone looked every group read `storedBytes 0`. Retention is now 30 days. |
| Aug 11 – Aug 20 | No executions at all. The ~99 topics queued on 07-27 hit SQS's **14-day retention ceiling** on 08-10: depth went 54 → 0 in a day with only 1 consumed, ~53 expired unread. The orchestrator correctly skips a slot on an empty queue. Refill in batches of ~40 (3/day × 14 days). |

None of it paged anyone. `notify` crashed with `AttributeError` on every run
whose `plan.json` was missing, so the failure mail was replaced by a bare
"notifier failed" note and a dead pipeline read as a broken notifier. And the
`iris-flow-topic-queue-low` alarm sat in ALARM for 9 days targeting an SNS topic
with **zero subscriptions** — CloudFormation reported the email subscription
`CREATE_COMPLETE`, but AWS had deleted it after 3 days because it was never
confirmed, and a redeploy will not recreate it.

Restored and verified end-to-end:

| | |
|---|---|
| execution | `iris-motion-20260820T162416Z-d6e86774`, **SUCCEEDED**, 64 min |
| states | Prep → PlanShards → Render → Stitch → Postprocess → NotifySuccess |
| prep | exit 0, 42.5 min, 0 retries, `authored_by: claude` |
| gates | **passed** — 0 of 1920 frames over 24, p1 median 2.2 / max 6.2 |
| post | booked 13:49 ET to Instagram, TikTok, YouTube, Facebook |
| image | `iris-motion-renderer:de9b013`, linux/amd64, SwiftShader confirmed via `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)` |

Note the repair loop fixed the bloom itself — preflight started at p1 max 41.7
and the final render came in at 6.2, so this piece would have passed the OLD
strict gate too. The gate change earns its keep on a piece with a brief
unavoidable flash, not this one.

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
