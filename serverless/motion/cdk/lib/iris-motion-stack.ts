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
 * Nothing here is shared with IrisFlowStack except two read-only things:
 * the `iris-flow/api-keys` secret and SES. New bucket, new ECR repo, new VPC,
 * new compute environment, new job queue.
 *
 * Manually triggered only — there is deliberately NO EventBridge schedule.
 *
 *   aws stepfunctions start-execution \
 *     --state-machine-arn <StateMachineArn output> \
 *     --input '{"video_id":"aurora01","topic":"why auroras glow","target_duration":48}'
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

    const createJobDef = (
      logicalId: string,
      jobType: string,
      vcpu: number,
      memoryMiB: number,
      timeoutMinutes: number,
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
        },
        secrets: batchSecrets,
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
        retryAttempts: 3,
        retryStrategies: [
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

    const definition = prepJob
      .next(planShards)
      .next(renderMap)
      .next(stitchJob)
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

    // No EventBridge rule by design — iris-motion is triggered by hand.

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
  }
}
