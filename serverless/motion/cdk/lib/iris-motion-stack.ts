import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as batch from 'aws-cdk-lib/aws-batch';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as lambda_ from 'aws-cdk-lib/aws-lambda';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import { Construct } from 'constructs';

/**
 * iris-motion — a second, parallel pipeline alongside IrisFlowStack.
 *
 * Renders motion-video pieces: a Three.js scene drawn frame-by-frame in headless
 * Chrome, narrated, gated, then encoded to MP4. Under SwiftShader (there is no
 * GPU on Fargate) rendering is ~37x slower than on a real GPU, so the frame
 * range is SHARDED across parallel Batch jobs — that fan-out is the whole reason
 * this stack exists rather than a single container.
 *
 * Shared with IrisFlowStack, all of it read-only except the last: the
 * `iris-flow/api-keys` secret, SES, the VPC, the `iris-flow-topic-queue` SQS
 * queue (motion now drains the same topic backlog the STEM pipeline did), and
 * the PUBLIC `iris-flow-videos-<account>` bucket, which motion writes the
 * finished MP4 into because Metricool has to fetch it over plain HTTPS.
 * Everything else is its own: bucket, ECR repo, compute environments, queues.
 *
 * Scheduled 5x daily by the three EventBridge rules at the bottom of this file,
 * which fire `iris-motion-orchestrator` — the same cadence and the same
 * per-network caps the STEM pipeline used before it was paused.
 *
 * EXECUTION INPUT. Every field below is read by a JsonPath in the state
 * machine, and a JsonPath to a missing field FAILS the state rather than
 * defaulting — so all eight are mandatory on every execution, hand-started or
 * not. The orchestrator always sets them.
 *
 *   aws stepfunctions start-execution \
 *     --state-machine-arn <StateMachineArn output> \
 *     --input '{"video_id":"aurora01","topic":"why auroras glow",
 *               "target_duration":48,
 *               "force_seed":true,"seed_fallback":true,
 *               "schedule_time":"2026-07-28T18:40:00+00:00",
 *               "include_youtube":false,"include_tiktok":false}'
 *
 * The two seed flags are what separate a manual run from a scheduled one.
 * Scheduled runs pin BOTH false: authoring is Claude-only and a slot that
 * cannot be authored is skipped, not filled with the same aurora piece for the
 * fifth time. Manual runs leave the fallback on, or force the seed outright, to
 * exercise the infrastructure without spending on a model call.
 */
export class IrisMotionStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // S3 lifecycle filters match a LITERAL prefix — there is no wildcard, so
    // `jobs/*/frames/` is not expressible, and a plain `jobs/` prefix would take
    // out/video.mp4 with it. The only filter that isolates frames is an object
    // tag, so the render shards have to tag their PNG uploads. The value below
    // is handed to the container in exactly the form S3 wants, so the frame
    // upload in app/common.py needs one more entry:
    //     ExtraArgs={'ContentType': ..., 'Tagging': os.environ['FRAME_OBJECT_TAGGING']}
    // Until that lands the rule is inert — frames are kept, never wrongly
    // deleted, which is the right way round for this to fail.
    const FRAME_TAG_KEY = 'iris-motion-role';
    const FRAME_TAG_VALUE = 'frame';

    // =====================
    // S3 bucket — private, frames disposable, everything else retained
    // =====================
    const motionBucket = new s3.Bucket(this, 'MotionBucket', {
      bucketName: `iris-motion-${this.account}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          // A 1440-frame render is ~1440 PNGs at 1080x1920 — a few GB per video,
          // and worthless the moment out/video.mp4 exists. out/ and plan.json
          // carry no tag and are never touched by this rule.
          id: 'expire-frames',
          enabled: true,
          prefix: 'jobs/',
          tagFilters: { [FRAME_TAG_KEY]: FRAME_TAG_VALUE },
          expiration: cdk.Duration.days(3),
        },
        {
          // A Spot-reclaimed stitch job can die mid-multipart-upload; the parts
          // are invisible in the console and billed until aborted.
          id: 'abort-stuck-multipart',
          enabled: true,
          abortIncompleteMultipartUploadAfter: cdk.Duration.days(1),
        },
      ],
    });

    // =====================
    // Public delivery bucket — IMPORTED from IrisFlowStack, never redeclared
    // =====================
    // MotionBucket above is BLOCK_ALL private, which is right for frames and
    // plan.json but useless for posting: Metricool fetches the video over an
    // unauthenticated GET, and a presigned URL is not an option — it expires,
    // and Metricool re-reads the media when the post actually publishes, up to
    // 90 minutes after the pipeline finished. So postprocess copies
    // out/video.mp4 into IrisFlowStack's public bucket and posts THAT url,
    // exactly as the STEM pipeline does.
    //
    // fromBucketName, not a new s3.Bucket: this bucket belongs to IrisFlowStack
    // (publicReadAccess + CORS + RETAIN, all set there). Declaring it here would
    // be a second CloudFormation resource fighting for the same name.
    const publicVideoBucket = s3.Bucket.fromBucketName(
      this, 'PublicVideoBucket', `iris-flow-videos-${this.account}`,
    );

    // =====================
    // ECR repository — IMPORTED, not created
    // =====================
    // The repo is created out of band (docker/build_and_push.sh, or the aws CLI)
    // and the image is pushed BEFORE this stack deploys, so that the very first
    // execution has something to pull. Declaring it here instead would make
    // `cdk deploy` fail with "already exists" against a repo that has to
    // pre-date it — the image push and the stack cannot both go first, and the
    // push has to win because Batch has no way to wait for it.
    // Same import pattern IrisFlowStack uses for iris-flow-generator.
    const rendererRepo = ecr.Repository.fromRepositoryName(
      this, 'RendererRepo', 'iris-motion-renderer',
    );

    // =====================
    // Secrets Manager — imported, read-only, shared with IrisFlowStack
    // =====================
    const apiSecrets = secretsmanager.Secret.fromSecretNameV2(
      this, 'ApiSecrets', 'iris-flow/api-keys'
    );

    // =====================
    // VPC — IMPORTED from IrisFlowStack, read-only
    // =====================
    // This stack originally created its own VPC. It cannot: the account is at
    // the regional VPC limit (5/5) and at the internet-gateway limit, so
    // `cdk deploy` failed with ServiceLimitExceeded and rolled back.
    //
    // Importing IrisFlowStack's VPC is a READ of that stack's outputs; it adds
    // no dependency in the CloudFormation sense and cannot modify it. The shape
    // is already exactly what this workload wants — public subnets, no NAT
    // Gateway (~$32/mo of standing cost against a ~$1/video pipeline), outbound
    // only to S3 and the model APIs.
    //
    // fromLookup resolves at synth time and caches into cdk.context.json, so
    // the subnet ids are pinned in the repo rather than re-queried per deploy.
    const vpc = ec2.Vpc.fromLookup(this, 'SharedVpc', {
      vpcId: 'vpc-009f7e9cebcd73dd7',   // IrisFlowStack/IrisFlowVpc
    });

    const taskSecurityGroup = new ec2.SecurityGroup(this, 'TaskSecurityGroup', {
      vpc,
      description: 'Security group for iris-motion Batch jobs',
      allowAllOutbound: true,
    });

    // =====================
    // IAM roles for Batch
    // =====================
    const batchJobRole = new iam.Role(this, 'BatchJobRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });
    // grantReadWrite includes s3:PutObjectTagging, which the render shards need
    // to apply the frames lifecycle tag.
    motionBucket.grantReadWrite(batchJobRole);
    // Write-only on the public bucket, and only for postprocess's copy of the
    // finished MP4. Deliberately NOT grantReadWrite: the STEM pipeline's own
    // manifests and segments live in there and nothing in iris-motion has any
    // business reading or overwriting them. grantPut also carries s3:Abort*,
    // which a multipart PUT of a ~15 MB video needs to clean up after itself.
    publicVideoBucket.grantPut(batchJobRole);
    // Already present before postprocess existed; postprocess relies on it for
    // the METRICOOL_* keys injected below.
    apiSecrets.grantRead(batchJobRole);

    const batchExecRole = new iam.Role(this, 'BatchExecRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });
    rendererRepo.grantPull(batchExecRole);
    apiSecrets.grantRead(batchExecRole);

    // =====================
    // Batch — own Fargate Spot compute environment
    // =====================
    // 128 maxvCpus: the render Map runs 24 shards x 4 vCPU = 96 concurrently
    // (the account's Fargate quota is 140), and the headroom lets a
    // Spot-reclaimed shard restart while the others still hold their vCPUs.
    // 24 shards is set by MEASURED Fargate speed: 14.2 s/frame at ss12 means a
    // 1440-frame piece is 5.7 vCPU-hours however it is sliced, and slicing it
    // 24 ways is what brings wall-clock to ~14 min. Sharding is nearly free --
    // cost is total vCPU-seconds, which does not change with shard count.
    // Logical id carries a version suffix ON PURPOSE. Batch refuses an in-place
    // update to a Fargate compute environment ("The following parameters can't be
    // updated: ... type, updatePolicy ..."), even for maxvCpus, so changing the
    // fan-out means REPLACING the CE. Bumping this suffix is how you do that
    // safely: CloudFormation creates the new one, repoints the queue, deletes the
    // old. Do it only when no jobs are running.
    const computeEnv = new batch.FargateComputeEnvironment(this, 'MotionComputeEnvV2', {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      securityGroups: [taskSecurityGroup],
      spot: true,
      maxvCpus: 128,
    });

    const jobQueue = new batch.JobQueue(this, 'MotionJobQueue', {
      jobQueueName: 'iris-motion-job-queue',
      priority: 1,
      computeEnvironments: [
        { computeEnvironment: computeEnv, order: 1 },
      ],
    });

    // Shared environment for every iris-motion Batch job. Deliberately short:
    // fps / subsamples / shards are module constants in app/prep.py and land in
    // plan.json, so setting them here would create a second source of truth that
    // nothing reads. CHROME_PATH is likewise NOT set — the image points it at
    // its own SwiftShader wrapper script, and overriding it from the job
    // definition would send render.mjs at a binary that has no Linux GL flags.
    const batchEnvVars: { [key: string]: string } = {
      MOTION_BUCKET: motionBucket.bucketName,
      AWS_REGION: this.region,
      // Consumed by the frame upload in app/common.py as the PutObject
      // `Tagging` value; without the tag the expire-frames lifecycle rule above
      // matches nothing and frames accumulate forever.
      FRAME_OBJECT_TAGGING: `${FRAME_TAG_KEY}=${FRAME_TAG_VALUE}`,
    };

    // Only the two keys this pipeline actually uses. Injected by the ECS agent
    // straight into the task's env from Secrets Manager — the values never
    // appear in the task definition, the logs, or CloudFormation.
    const batchSecrets: { [key: string]: batch.Secret } = {
      ANTHROPIC_API_KEY: batch.Secret.fromSecretsManager(apiSecrets, 'ANTHROPIC_API_KEY'),
      GOOGLE_AI_API_KEY: batch.Secret.fromSecretsManager(apiSecrets, 'GOOGLE_AI_API_KEY'),
    };

    // extraEnv / extraSecrets exist for postprocess: it is the only job that
    // talks to Metricool, and there is no reason for a render shard's task
    // definition to carry publishing credentials it will never read.
    const createJobDef = (
      logicalId: string,
      jobType: string,
      vcpu: number,
      memoryMiB: number,
      timeoutMinutes: number,
      extraEnv: { [key: string]: string } = {},
      extraSecrets: { [key: string]: batch.Secret } = {},
      // AT-MOST-ONCE. Any job whose side effect is visible OUTSIDE this account
      // must pass true. See the postprocess call site.
      atMostOnce: boolean = false,
    ): batch.EcsJobDefinition => {
      const jobDefName = `iris-motion-${jobType}`;
      const container = new batch.EcsFargateContainerDefinition(this, `${logicalId}Container`, {
        image: ecs.ContainerImage.fromEcrRepository(rendererRepo, 'latest'),
        cpu: vcpu,
        memory: cdk.Size.mebibytes(memoryMiB),
        jobRole: batchJobRole,
        executionRole: batchExecRole,
        environment: {
          ...batchEnvVars,
          JOB_TYPE: jobType,
          ...extraEnv,
        },
        secrets: { ...batchSecrets, ...extraSecrets },
        logging: ecs.LogDrivers.awsLogs({
          streamPrefix: jobDefName,
          logRetention: logs.RetentionDays.ONE_WEEK,
        }),
        // No NAT Gateway in this VPC, so a task with no public IP has no route
        // to ECR, S3 or the model APIs and hangs until the timeout.
        assignPublicIp: true,
        fargatePlatformVersion: ecs.FargatePlatformVersion.LATEST,
      });

      return new batch.EcsJobDefinition(this, logicalId, {
        jobDefinitionName: jobDefName,
        container,
        timeout: cdk.Duration.minutes(timeoutMinutes),
        // A retry is safe for prep/render/stitch: they are idempotent, they
        // write to S3 keys derived from the frame number, and re-running one
        // costs compute. It is NOT safe for anything that posts.
        retryAttempts: atMostOnce ? 1 : 3,
        retryStrategies: atMostOnce ? [] : [
          // Spot reclaim is retried HERE, inside Batch, not in Step Functions:
          // a reclaimed attempt is not a task failure the state machine ever
          // sees, and re-running one shard is far cheaper than re-running the
          // Map branch.
          {
            action: batch.Action.RETRY,
            on: batch.Reason.SPOT_INSTANCE_RECLAIMED,
          },
          // Covers the window between `cdk deploy` and the first image push,
          // and transient ECR pull throttling when 8 shards start at once.
          {
            action: batch.Action.RETRY,
            on: batch.Reason.CANNOT_PULL_CONTAINER,
          },
          // FARGATE Spot reclaim. batch.Reason.SPOT_INSTANCE_RECLAIMED expands to
          // OnStatusReason 'Host EC2*', which is the EC2-backed Batch message and
          // does NOT match Fargate's. Fargate says exactly "Your Spot Task was
          // interrupted." — without this rule the reclaim falls through to the
          // terminal EXIT below and the shard is never retried, which failed a
          // whole 1440-frame run at 1020 frames.
          {
            action: batch.Action.RETRY,
            on: batch.Reason.custom({ onStatusReason: 'Your Spot Task was interrupted*' }),
          },
          // TERMINAL CATCH-ALL. Batch's evaluateOnExit can only ADD retries:
          // when no condition matches, the job is retried anyway up to
          // retryAttempts. Without this a DETERMINISTIC application failure --
          // a scene that always throws, a bad anchor -- is run 3 times, and
          // each prep attempt is worth up to 6 model calls. This makes anything
          // that is not a known-transient infrastructure fault fail on attempt 1.
          {
            action: batch.Action.EXIT,
            on: batch.Reason.custom({ onReason: '*' }),
          },
        ],
      });
    };

    // One container, three shapes — dispatched by JOB_TYPE, same convention as
    // serverless/src/worker.py.
    const prepJobDef = createJobDef('PrepJobDef', 'prep', 2, 4096, 20);
    // 4 vCPU: SwiftShader rasterises on the CPU, so shard wall-clock scales
    // almost linearly with cores. 8 GiB holds the 1080x1920 canvas at ss=16.
    const renderJobDef = createJobDef('RenderJobDef', 'render', 4, 8192, 30);
    // 2 vCPU but still 8 GiB: stitch is ffmpeg-bound, not CPU-bound, and the
    // memory is for decoding the frame sequence, not for parallelism.
    const stitchJobDef = createJobDef('StitchJobDef', 'stitch', 2, 8192, 20);
    // postprocess: caption + copy the MP4 to the public bucket + schedule to
    // Metricool. It is HTTP-bound, not CPU-bound — 1 vCPU / 2 GiB, the same
    // shape IrisFlowStack gives its own postprocess job. It runs on the FARGATE
    // queue, never the GPU one: a g4dn.xlarge spun up to make four API calls
    // would cost more than the render it follows.
    // 15 min: Metricool's scheduler endpoint is called once per brand and has
    // been seen to take ~30 s under load, and the S3 copy is a few seconds.
    // atMostOnce=true on the LAST argument. This is the one job in the stack
    // whose side effect leaves the account: it books a post on real Instagram /
    // TikTok / YouTube / Facebook accounts. Batch's evaluateOnExit can only ADD
    // retries, so with the shared strategy a Fargate Spot reclaim ten seconds
    // after schedule_post() returns would run the whole job again and book the
    // post TWICE, with no idempotency key to stop it. A reclaimed post must
    // fail the run and email, never repeat.
    const postprocessJobDef = createJobDef(
      'PostprocessJobDef', 'postprocess', 1, 2048, 15,
      {
        // The PUBLIC bucket, NOT MOTION_BUCKET — this is the one Metricool
        // fetches from. app/postprocess.py defaults it to the same name, but
        // set it here anyway: the default is a literal account id in Python
        // source, and this is the only place that number should come from.
        PUBLIC_BUCKET_NAME: publicVideoBucket.bucketName,
        // Carried over verbatim from IrisFlowStack's batchEnvVars so a motion
        // post lands exactly the way the STEM posts it replaces did. The
        // TikTok one is not cosmetic: Metricool rejects autoAddMusic outright
        // on video posts (HTTP 400), and every motion piece is a video.
        METRICOOL_DEFAULT_AUDIO_NAME: 'Scientific-Nipsey',
        METRICOOL_TIKTOK_AUTO_ADD_MUSIC: 'false',
        METRICOOL_SHOW_REEL_ON_FEED: 'true',
        METRICOOL_INSTAGRAM_MANUAL_FOR_AUDIO: 'false',
      },
      {
        METRICOOL_API_KEY: batch.Secret.fromSecretsManager(apiSecrets, 'METRICOOL_API_KEY'),
        METRICOOL_USER_ID: batch.Secret.fromSecretsManager(apiSecrets, 'METRICOOL_USER_ID'),
        METRICOOL_BLOG_ID: batch.Secret.fromSecretsManager(apiSecrets, 'METRICOOL_BLOG_ID'),
      },
      true,      // atMostOnce: never retry a job that posts
    );

    // =====================
    // GPU render path — EC2-backed Batch, NOT Fargate
    // =====================
    // Fargate cannot attach a GPU at all, which is why the software renderer
    // costs 14.2 s/frame. A g4dn.xlarge carries a T4.
    //
    // Three account limits shape every choice here, all checked:
    //   - "All G and VT Spot Instance Requests" quota is 0  -> ON-DEMAND ONLY.
    //   - "Running On-Demand G and VT instances" is 8 vCPU  -> maxvCpus 8,
    //     i.e. exactly two g4dn.xlarge at once.
    //   - g4dn is NOT offered in us-east-1a. The shared VPC has 1a and 1b, so
    //     this CE is pinned to the 1b subnet; leaving both in makes Batch
    //     intermittently fail to place instances with no useful error.
    const GPU_SUBNET_ID = 'subnet-0462166899bb0f76c';   // us-east-1b

    const gpuComputeEnv = new batch.ManagedEc2EcsComputeEnvironment(this, 'GpuComputeEnvV1', {
      vpc,
      vpcSubnets: {
        subnets: [ec2.Subnet.fromSubnetId(this, 'GpuSubnet', GPU_SUBNET_ID)],
      },
      securityGroups: [taskSecurityGroup],
      instanceTypes: [ec2.InstanceType.of(ec2.InstanceClass.G4DN, ec2.InstanceSize.XLARGE)],
      // Without this Batch adds the C/M/R "optimal" families, which have no GPU
      // and would happily accept a GPU job and then never satisfy it.
      useOptimalInstanceClasses: false,
      // The NVIDIA-flavoured ECS AMI. The stock image has no driver and the
      // container would silently fall back to SwiftShader — the exact failure
      // this whole path exists to avoid. Must be the AL2023 variant: Batch now
      // rejects ECS_AL2_NVIDIA outright with "Amazon Linux 2 is end-of-life".
      images: [{ imageType: batch.EcsMachineImageType.ECS_AL2023_NVIDIA }],
      spot: false,
      minvCpus: 0,
      maxvCpus: 8,
      // Instances are billed by the second with a 1-minute floor; a short idle
      // window lets consecutive shards reuse a warm instance instead of paying
      // ~3 min of boot + 600 MB image pull each time.
      updateTimeout: cdk.Duration.minutes(30),
    });

    const gpuJobQueue = new batch.JobQueue(this, 'GpuJobQueue', {
      jobQueueName: 'iris-motion-gpu-queue',
      priority: 1,
      computeEnvironments: [{ computeEnvironment: gpuComputeEnv, order: 1 }],
    });

    const gpuRenderContainer = new batch.EcsEc2ContainerDefinition(this, 'GpuRenderContainer', {
      image: ecs.ContainerImage.fromEcrRepository(rendererRepo, 'gpu'),
      cpu: 4,
      // g4dn.xlarge has 16 GiB; leave headroom for the ECS agent or the job is
      // never placeable.
      memory: cdk.Size.mebibytes(14000),
      gpu: 1,
      jobRole: batchJobRole,
      executionRole: batchExecRole,
      environment: { ...batchEnvVars, JOB_TYPE: 'render' },
      secrets: batchSecrets,
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'iris-motion-gpu-render',
        logRetention: logs.RetentionDays.ONE_WEEK,
      }),
    });

    const gpuRenderJobDef = new batch.EcsJobDefinition(this, 'GpuRenderJobDef', {
      jobDefinitionName: 'iris-motion-gpu-render',
      container: gpuRenderContainer,
      timeout: cdk.Duration.minutes(60),
      retryAttempts: 2,
      retryStrategies: [
        { action: batch.Action.RETRY, on: batch.Reason.CANNOT_PULL_CONTAINER },
        { action: batch.Action.EXIT, on: batch.Reason.custom({ onReason: '*' }) },
      ],
    });

    // =====================
    // Lambdas
    // =====================
    const planShardsFn = new lambda_.Function(this, 'PlanShardsFn', {
      functionName: 'iris-motion-plan-shards',
      runtime: lambda_.Runtime.PYTHON_3_12,
      handler: 'plan_shards.handler',
      code: lambda_.Code.fromAsset('../app/lambdas'),
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      environment: {
        MOTION_BUCKET: motionBucket.bucketName,
      },
    });
    motionBucket.grantRead(planShardsFn);

    const notifyFn = new lambda_.Function(this, 'NotifyFn', {
      functionName: 'iris-motion-notify',
      runtime: lambda_.Runtime.PYTHON_3_12,
      handler: 'notify.handler',
      code: lambda_.Code.fromAsset('../app/lambdas'),
      timeout: cdk.Duration.minutes(1),
      memorySize: 256,
      environment: {
        MOTION_BUCKET: motionBucket.bucketName,
        MAIL_FROM: 'mattneto928@gmail.com',
        MAIL_TO: 'mattneto928@gmail.com',
      },
    });
    // grantRead is what makes the presigned URL work: a presigned GET carries
    // the signer's permissions, so without s3:GetObject the link 403s.
    motionBucket.grantRead(notifyFn);
    // SES has no resource ARN to scope SendEmail to on the v1 API, so the send
    // is fenced by the From address instead — this role can only ever mail as
    // the one verified identity.
    notifyFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ses:SendEmail', 'ses:SendRawEmail'],
      resources: ['*'],
      conditions: {
        StringEquals: { 'ses:FromAddress': 'mattneto928@gmail.com' },
      },
    }));

    // =====================
    // Step Functions — iris-motion-pipeline
    // =====================
    // Execution input:
    //   {"video_id": "...", "topic": "...", "target_duration": 48}
    //
    // Batch throttles SubmitJob when the Map fans out; these are Step Functions
    // service-level errors, distinct from the job itself failing, so they are
    // retried here rather than by the job definition's retryStrategies.
    const batchRetry: sfn.RetryProps = {
      errors: [
        'Batch.AWS.Batch.TooManyRequestsException',
        'Batch.ServerException',
        'Batch.SdkClientException',
      ],
      interval: cdk.Duration.seconds(15),
      maxAttempts: 5,
      backoffRate: 2,
    };

    const prepJob = new tasks.BatchSubmitJob(this, 'PrepJob', {
      jobDefinitionArn: prepJobDef.jobDefinitionArn,
      jobName: sfn.JsonPath.format('motion-prep-{}', sfn.JsonPath.stringAt('$.video_id')),
      jobQueueArn: jobQueue.jobQueueArn,
      containerOverrides: {
        environment: {
          VIDEO_ID: sfn.JsonPath.stringAt('$.video_id'),
          TOPIC: sfn.JsonPath.stringAt('$.topic'),
          // Batch environment values must be strings; target_duration arrives
          // as a JSON number.
          TARGET_DURATION: sfn.JsonPath.stringAt('States.Format(\'{}\', $.target_duration)'),
          // Selects the bundled seed piece over the model authoring path, so
          // the infrastructure can be exercised without spending on a model
          // call and without a bad scene masquerading as a pipeline bug.
          // Always present on the execution input (the CLI examples pass it),
          // because a JsonPath to a missing field fails the state, not the field.
          FORCE_SEED: sfn.JsonPath.stringAt("States.Format('{}', $.force_seed)"),
          // Whether the seed is allowed as a FALLBACK when authoring fails,
          // which is a different question from FORCE_SEED asking for it.
          // Scheduled runs set it false: they publish unconditionally, and the
          // seed is one fixed aurora piece, so a fallback there posts that same
          // video again under whatever topic came off the queue. Better to fail
          // the run, skip the slot, and send the failure email.
          // app/prep.py defaults it TRUE on a blank value, so this override is
          // the ONLY thing that makes a scheduled run authored-only — dropping
          // it does not break a deploy, it quietly starts republishing the seed.
          SEED_FALLBACK: sfn.JsonPath.stringAt("States.Format('{}', $.seed_fallback)"),
        },
      },
      resultPath: '$.prepResult',
    });
    prepJob.addRetry(batchRetry);

    const planShards = new tasks.LambdaInvoke(this, 'PlanShards', {
      lambdaFunction: planShardsFn,
      payloadResponseOnly: true,
      resultPath: '$.planResult',
    });

    const renderJob = new tasks.BatchSubmitJob(this, 'RenderJob', {
      // GPU path. The Fargate renderJobDef is kept deployed as a fallback (the
      // G-family on-demand quota is only 8 vCPU, so a quota problem or a
      // capacity shortfall in us-east-1b has somewhere to go), but the state
      // machine points at the T4: 0.133 s/frame vs 14.2 measured.
      jobDefinitionArn: gpuRenderJobDef.jobDefinitionArn,
      jobName: sfn.JsonPath.format('motion-render-{}-{}',
        sfn.JsonPath.stringAt('$.video_id'),
        sfn.JsonPath.stringAt('States.Format(\'{}\', $.shard)')
      ),
      jobQueueArn: gpuJobQueue.jobQueueArn,
      containerOverrides: {
        environment: {
          VIDEO_ID: sfn.JsonPath.stringAt('$.video_id'),
          // No SHARD var: app/render_shard.py works purely from the inclusive
          // [FRAME_FROM, FRAME_TO] range, and the shard index is already in the
          // job name, which is what DescribeJobs and the log stream show.
          FRAME_FROM: sfn.JsonPath.stringAt('States.Format(\'{}\', $.frame_from)'),
          FRAME_TO: sfn.JsonPath.stringAt('States.Format(\'{}\', $.frame_to)'),
        },
      },
    });
    renderJob.addRetry(batchRetry);

    // Deliberately NO per-shard catch, unlike IrisFlowStack's visual Map. There
    // a dropped segment costs one clip; here a dropped shard is a hole in the
    // frame sequence, and ffmpeg reading frames/f%04d.png stops dead at the
    // first missing number — a silently truncated video. Fail the whole run.
    const renderMap = new sfn.Map(this, 'RenderMap', {
      itemsPath: '$.planResult.shards',
      maxConcurrency: 24,
      resultPath: '$.renderResults',
    });
    renderMap.itemProcessor(renderJob);

    const stitchJob = new tasks.BatchSubmitJob(this, 'StitchJob', {
      jobDefinitionArn: stitchJobDef.jobDefinitionArn,
      jobName: sfn.JsonPath.format('motion-stitch-{}', sfn.JsonPath.stringAt('$.video_id')),
      jobQueueArn: jobQueue.jobQueueArn,
      containerOverrides: {
        environment: {
          VIDEO_ID: sfn.JsonPath.stringAt('$.video_id'),
        },
      },
      resultPath: '$.stitchResult',
    });
    stitchJob.addRetry(batchRetry);

    // Publishing. Runs AFTER stitch and BEFORE notify, unconditionally: there is
    // no Choice on $.stitchResult and none on the gates. stitch already treats a
    // gate failure as informational (it writes out/gates.txt and encodes
    // anyway), and notify reports the result by email — so a soft gate FAIL is
    // something you read about, not something that silently drops the slot.
    //
    // SCHEDULE_TIME / INCLUDE_YOUTUBE / INCLUDE_TIKTOK come off the execution
    // input, set by the orchestrator from the constant on the triggering
    // EventBridge rule; they are what cap YouTube at 2 posts/day and TikTok at
    // 3. Batch environment values must be strings, hence States.Format on the
    // two booleans — the same pattern IrisFlowStack's PostprocessJob uses.
    const postprocessJob = new tasks.BatchSubmitJob(this, 'PostprocessJob', {
      jobDefinitionArn: postprocessJobDef.jobDefinitionArn,
      jobName: sfn.JsonPath.format('motion-postprocess-{}', sfn.JsonPath.stringAt('$.video_id')),
      jobQueueArn: jobQueue.jobQueueArn,
      containerOverrides: {
        environment: {
          VIDEO_ID: sfn.JsonPath.stringAt('$.video_id'),
          SCHEDULE_TIME: sfn.JsonPath.stringAt('$.schedule_time'),
          INCLUDE_YOUTUBE: sfn.JsonPath.stringAt("States.Format('{}', $.include_youtube)"),
          INCLUDE_TIKTOK: sfn.JsonPath.stringAt("States.Format('{}', $.include_tiktok)"),
          // DRY_RUN=true does everything except the Metricool call: copies the MP4
          // public, writes the caption, logs what it WOULD book. Without this on the
          // execution input there is no way to rehearse posting — the first cron
          // fire after a deploy would be the first live post.
          DRY_RUN: sfn.JsonPath.stringAt("States.Format('{}', $.dry_run)"),
        },
      },
      resultPath: '$.postprocessResult',
    });
    postprocessJob.addRetry(batchRetry);

    const notifySuccess = new tasks.LambdaInvoke(this, 'NotifySuccess', {
      lambdaFunction: notifyFn,
      payloadResponseOnly: true,
      resultPath: '$.notifyResult',
    });

    // Failure path. A separate LambdaInvoke construct (a state cannot appear
    // twice in one graph) invoking the SAME function — notify.py branches on
    // the `error` key that addCatch writes into the state.
    const notifyFailure = new tasks.LambdaInvoke(this, 'NotifyFailure', {
      lambdaFunction: notifyFn,
      payloadResponseOnly: true,
      resultPath: '$.notifyResult',
    });

    const pipelineFailed = new sfn.Fail(this, 'PipelineFailed', {
      error: 'IrisMotionPipelineFailed',
      cause: 'A pipeline stage failed. See $.error and the failure email.',
    });

    notifyFailure.next(pipelineFailed);
    // Belt and braces: if notify itself throws, still land on Fail rather than
    // leaving the execution in a half-caught state.
    notifyFailure.addCatch(pipelineFailed, { resultPath: sfn.JsonPath.DISCARD });

    // Global catch. resultPath '$.error' preserves the rest of the state, so
    // the failure email still has video_id and topic to report.
    const toNotifyOnFailure: sfn.CatchProps = {
      errors: [sfn.Errors.ALL],
      resultPath: '$.error',
    };
    prepJob.addCatch(notifyFailure, toNotifyOnFailure);
    planShards.addCatch(notifyFailure, toNotifyOnFailure);
    renderMap.addCatch(notifyFailure, toNotifyOnFailure);
    stitchJob.addCatch(notifyFailure, toNotifyOnFailure);
    // Posting is the one stage whose failure leaves a finished, unpublished
    // video sitting in S3, so it especially needs to reach the email.
    postprocessJob.addCatch(notifyFailure, toNotifyOnFailure);

    const definition = prepJob
      .next(planShards)
      .next(renderMap)
      .next(stitchJob)
      .next(postprocessJob)
      .next(notifySuccess);

    const stateMachine = new sfn.StateMachine(this, 'MotionStateMachine', {
      stateMachineName: 'iris-motion-pipeline',
      definitionBody: sfn.DefinitionBody.fromChainable(definition),
      timeout: cdk.Duration.hours(2),
      logs: {
        destination: new logs.LogGroup(this, 'MotionSfnLogGroup', {
          logGroupName: '/iris-motion/state-machine',
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
        level: sfn.LogLevel.ERROR,
      },
    });

    // =====================
    // Orchestrator Lambda — one execution per scheduled slot
    // =====================
    // Drains the SAME queue the STEM pipeline drained. Imported by name rather
    // than redeclared: `iris-flow-topic-queue` is IrisFlowStack's resource, and
    // the point of importing it is that the topic backlog already sitting in it
    // carries over to motion instead of being stranded. Nothing contends for a
    // message — the three STEM rules that used to drive the other consumer are
    // disabled in iris-flow-stack.ts as part of this changeover.
    //
    // Region and account are concrete (bin/app.ts pins them), so this parses to
    // a real ARN and `queueUrl` resolves to the real URL rather than a stack of
    // CloudFormation intrinsics.
    const topicQueue = sqs.Queue.fromQueueArn(
      this, 'TopicQueue',
      `arn:aws:sqs:${this.region}:${this.account}:iris-flow-topic-queue`,
    );

    const orchestratorFn = new lambda_.Function(this, 'OrchestratorFn', {
      functionName: 'iris-motion-orchestrator',
      runtime: lambda_.Runtime.PYTHON_3_12,
      handler: 'orchestrator.handler',
      code: lambda_.Code.fromAsset('../app/lambdas'),
      // 2 minutes is all it needs — one SQS receive, one StartExecution — but
      // StartExecution is the throttled call in this account and a retry inside
      // the handler is cheaper than a lost slot.
      timeout: cdk.Duration.minutes(2),
      memorySize: 256,
      environment: {
        // Flip to 'true' to rehearse: every scheduled run then renders and
        // publishes the MP4 but books nothing on Metricool. Change it with
        // `aws lambda update-function-configuration` -- no redeploy needed.
        MOTION_DRY_RUN: 'false',
        TOPIC_QUEUE_URL: topicQueue.queueUrl,
        STATE_MACHINE_ARN: stateMachine.stateMachineArn,
        // AWS_REGION is set by the Lambda runtime.
      },
    });
    // receive + delete: the orchestrator takes one topic per slot and removes
    // it, so a topic is never rendered twice.
    topicQueue.grantConsumeMessages(orchestratorFn);
    stateMachine.grantStartExecution(orchestratorFn);

    // =====================
    // EventBridge — 5x daily, the cadence taken over from the STEM pipeline
    // =====================
    // Three rules, one Lambda, differing only in the constant network flags
    // they pass. Hours and flags are reproduced EXACTLY from IrisFlowStack's
    // DailySchedule* rules (now disabled), because this is a handover, not a
    // new schedule: the posting rhythm the accounts are used to should not
    // change on the day the content pipeline behind it does.
    //
    // Per-network caps come out of the split: YouTube 2 posts/day, TikTok
    // 3 posts/day (its For-You distribution collapsed under a 5x/day identical
    // crosspost cadence). IG/Facebook get all 5. The flags ride the execution
    // input into postprocess, which hands them to Metricool.

    // 2x daily with YouTube + TikTok — prime US engagement windows.
    // 18:00 UTC = 1pm EST, 00:00 UTC = 7pm EST.
    const motionScheduleYouTube = new events.Rule(this, 'MotionDailyScheduleYouTube', {
      ruleName: 'iris-motion-daily-youtube',
      description: 'Motion orchestrator 2× daily WITH YouTube + TikTok (1pm, 7pm EST)',
      // SHIPPED DISABLED, deliberately. The three iris-flow-daily-* rules are
      // still ENABLED in the live account and these use byte-identical crons,
      // so if IrisMotionStack deploys first every slot fires TWICE — ten posts
      // a day to real accounts. Enable only after IrisFlowStack is deployed and
      // `aws events describe-rule` shows the STEM rules DISABLED:
      //   aws events enable-rule --name iris-motion-daily-youtube
      enabled: false,
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '18,0', // 2× daily, UTC
      }),
    });
    motionScheduleYouTube.addTarget(new targets.LambdaFunction(orchestratorFn, {
      event: events.RuleTargetInput.fromObject({ include_youtube: true, include_tiktok: true }),
    }));

    // 1× daily with TikTok (no YouTube) — midday slot.
    // 15:00 UTC = 10am EST.
    const motionScheduleTikTok = new events.Rule(this, 'MotionDailyScheduleTikTok', {
      ruleName: 'iris-motion-daily-tiktok',
      description: 'Motion orchestrator 1× daily WITH TikTok, no YouTube (10am EST)',
      // SHIPPED DISABLED, deliberately. The three iris-flow-daily-* rules are
      // still ENABLED in the live account and these use byte-identical crons,
      // so if IrisMotionStack deploys first every slot fires TWICE — ten posts
      // a day to real accounts. Enable only after IrisFlowStack is deployed and
      // `aws events describe-rule` shows the STEM rules DISABLED:
      //   aws events enable-rule --name iris-motion-daily-youtube
      enabled: false,
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '15', // 1× daily, UTC
      }),
    });
    motionScheduleTikTok.addTarget(new targets.LambdaFunction(orchestratorFn, {
      event: events.RuleTargetInput.fromObject({ include_youtube: false, include_tiktok: true }),
    }));

    // 2× daily IG/Facebook only — early morning + late afternoon.
    // 11:00 UTC = 6am, 21:00 = 4pm EST.
    const motionScheduleIgFb = new events.Rule(this, 'MotionDailyScheduleNoYouTube', {
      ruleName: 'iris-motion-daily-no-youtube',
      description: 'Motion orchestrator 2× daily IG/Facebook only (6am, 4pm EST)',
      // SHIPPED DISABLED, deliberately. The three iris-flow-daily-* rules are
      // still ENABLED in the live account and these use byte-identical crons,
      // so if IrisMotionStack deploys first every slot fires TWICE — ten posts
      // a day to real accounts. Enable only after IrisFlowStack is deployed and
      // `aws events describe-rule` shows the STEM rules DISABLED:
      //   aws events enable-rule --name iris-motion-daily-youtube
      enabled: false,
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '11,21', // 2× daily, UTC
      }),
    });
    motionScheduleIgFb.addTarget(new targets.LambdaFunction(orchestratorFn, {
      event: events.RuleTargetInput.fromObject({ include_youtube: false, include_tiktok: false }),
    }));

    // =====================
    // Outputs
    // =====================
    new cdk.CfnOutput(this, 'MotionBucketName', {
      value: motionBucket.bucketName,
      description: 'S3 bucket for iris-motion jobs, frames and output',
    });

    new cdk.CfnOutput(this, 'RendererRepoUri', {
      value: rendererRepo.repositoryUri,
      description: 'ECR repository URI for the iris-motion renderer image',
    });

    new cdk.CfnOutput(this, 'GpuJobQueueArn', {
      value: gpuJobQueue.jobQueueArn,
      description: 'EC2/GPU Batch job queue (g4dn.xlarge, on-demand, max 2)',
    });

    new cdk.CfnOutput(this, 'StateMachineArn', {
      value: stateMachine.stateMachineArn,
      description: 'iris-motion-pipeline state machine ARN (start executions here)',
    });

    new cdk.CfnOutput(this, 'JobQueueArn', {
      value: jobQueue.jobQueueArn,
      description: 'Batch job queue ARN',
    });

    new cdk.CfnOutput(this, 'OrchestratorFnArn', {
      value: orchestratorFn.functionArn,
      description: 'iris-motion-orchestrator Lambda ARN (invoke to fire a slot by hand)',
    });
  }
}
