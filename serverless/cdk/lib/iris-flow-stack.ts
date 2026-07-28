import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as batch from 'aws-cdk-lib/aws-batch';
import * as lambda_ from 'aws-cdk-lib/aws-lambda';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cw_actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import { Construct } from 'constructs';

export class IrisFlowStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // =====================
    // S3 Bucket for videos and assets
    // =====================
    const videoBucket = new s3.Bucket(this, 'VideoBucket', {
      bucketName: `iris-flow-videos-${this.account}`,
      publicReadAccess: true,
      blockPublicAccess: new s3.BlockPublicAccess({
        blockPublicAcls: false,
        blockPublicPolicy: false,
        ignorePublicAcls: false,
        restrictPublicBuckets: false,
      }),
      cors: [
        {
          allowedMethods: [s3.HttpMethods.GET],
          allowedOrigins: ['*'],
          allowedHeaders: ['*'],
        },
      ],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          // iris-motion copies every finished MP4 here under motion/ because
          // Metricool has to fetch it over an unauthenticated GET. MEASURED at
          // ~87 MB per video (not the ~15 MB first assumed); at 5/day that is
          // ~13 GB/month accruing forever, since nothing else ever deletes it.
          // 60 days is well past any Metricool re-read — it re-reads the media
          // when the post publishes, at most ~90 minutes after upload.
          // Scoped to the motion/ prefix ONLY: the STEM pipeline's own objects
          // live at other prefixes and are deliberately untouched.
          id: 'expire-motion-mp4s',
          enabled: true,
          prefix: 'motion/',
          expiration: cdk.Duration.days(60),
        },
      ],
    });

    // =====================
    // S3 Bucket for Music (Manually populated)
    // =====================
    const musicBucket = new s3.Bucket(this, 'MusicBucket', {
      bucketName: `iris-flow-music-${this.account}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // =====================
    // DynamoDB Tables
    // =====================

    const jobsTable = new dynamodb.Table(this, 'JobsTable', {
      tableName: 'iris-flow-jobs',
      partitionKey: { name: 'job_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'ttl',
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const topicsTable = new dynamodb.Table(this, 'TopicsTable', {
      tableName: 'iris-flow-topics',
      partitionKey: { name: 'topic_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'created_at', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'ttl',
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    topicsTable.addGlobalSecondaryIndex({
      indexName: 'category-index',
      partitionKey: { name: 'category', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'created_at', type: dynamodb.AttributeType.STRING },
    });

    // =====================
    // SQS Queue for topic input
    // =====================
    const topicQueue = new sqs.Queue(this, 'TopicQueue', {
      queueName: 'iris-flow-topic-queue',
      visibilityTimeout: cdk.Duration.minutes(30),
      retentionPeriod: cdk.Duration.days(14),
    });

    // Separate queue for the storytelling pipeline (origin stories). Same shape
    // of messages ({prompt, category, ...}); kept distinct so the two pipelines
    // never drain each other's topics.
    const storyQueue = new sqs.Queue(this, 'StoryQueue', {
      queueName: 'iris-flow-story-queue',
      visibilityTimeout: cdk.Duration.minutes(30),
      retentionPeriod: cdk.Duration.days(14),
    });

    // =====================
    // SNS alerts + low-queue alarm
    // =====================
    // Operational alerts (queue running low/empty, etc.) email mattneto928.
    const alertsTopic = new sns.Topic(this, 'AlertsTopic', {
      topicName: 'iris-flow-alerts',
      displayName: 'Iris-flow alerts',
    });
    alertsTopic.addSubscription(
      new subscriptions.EmailSubscription('mattneto928@gmail.com')
    );

    // Warn when the STEM topic queue runs low (<=5) or empties, so it can be
    // refilled (python scripts/populate_mega_topics.py). One email per state
    // change (OK -> ALARM), not per evaluation. treatMissingData=BREACHING so
    // a fully-drained, idle queue (which stops emitting the metric) still alerts.
    const topicQueueLowAlarm = new cloudwatch.Alarm(this, 'TopicQueueLowAlarm', {
      alarmName: 'iris-flow-topic-queue-low',
      alarmDescription:
        'STEM topic queue is low/empty — refill via scripts/populate_mega_topics.py',
      metric: topicQueue.metricApproximateNumberOfMessagesVisible({
        period: cdk.Duration.minutes(5),
        statistic: 'Maximum',
      }),
      threshold: 5,
      comparisonOperator:
        cloudwatch.ComparisonOperator.LESS_THAN_OR_EQUAL_TO_THRESHOLD,
      evaluationPeriods: 1,
      treatMissingData: cloudwatch.TreatMissingData.BREACHING,
    });
    topicQueueLowAlarm.addAlarmAction(new cw_actions.SnsAction(alertsTopic));

    // =====================
    // Secrets Manager
    // =====================
    const apiSecrets = secretsmanager.Secret.fromSecretNameV2(
      this, 'ApiSecrets', 'iris-flow/api-keys'
    );

    // =====================
    // VPC (public subnets only — no NAT Gateway)
    // =====================
    const vpc = new ec2.Vpc(this, 'IrisFlowVpc', {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: 'Public',
          subnetType: ec2.SubnetType.PUBLIC,
        },
      ],
    });

    // =====================
    // ECR Repository - import existing
    // =====================
    const ecrRepo = ecr.Repository.fromRepositoryName(
      this, 'IrisFlowRepo', 'iris-flow-generator'
    );

    // =====================
    // Security Group for Batch / ECS tasks
    // =====================
    const taskSecurityGroup = new ec2.SecurityGroup(this, 'TaskSecurityGroup', {
      vpc,
      description: 'Security group for Iris Flow Batch jobs',
      allowAllOutbound: true,
    });

    // =====================
    // EXISTING ECS (kept for rollback — remove in follow-up)
    // =====================
    const cluster = new ecs.Cluster(this, 'IrisFlowCluster', {
      clusterName: 'iris-flow-cluster',
      vpc,
      containerInsights: true,
      enableFargateCapacityProviders: true,
    });

    const ecsTaskRole = new iam.Role(this, 'TaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });
    videoBucket.grantReadWrite(ecsTaskRole);
    musicBucket.grantRead(ecsTaskRole);
    jobsTable.grantReadWriteData(ecsTaskRole);
    topicsTable.grantReadWriteData(ecsTaskRole);
    topicQueue.grantConsumeMessages(ecsTaskRole);
    apiSecrets.grantRead(ecsTaskRole);

    const executionRole = new iam.Role(this, 'ExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });
    ecrRepo.grantPull(executionRole);
    apiSecrets.grantRead(executionRole);

    const taskDefinition = new ecs.FargateTaskDefinition(this, 'IrisFlowTask', {
      memoryLimitMiB: 8192,
      cpu: 2048,
      taskRole: ecsTaskRole,
      executionRole,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.X86_64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });

    taskDefinition.addContainer('IrisFlowGenerator', {
      image: ecs.ContainerImage.fromEcrRepository(ecrRepo, 'latest'),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'iris-flow',
        logRetention: logs.RetentionDays.ONE_WEEK,
      }),
      environment: {
        VIDEO_BUCKET_NAME: videoBucket.bucketName,
        MUSIC_BUCKET_NAME: musicBucket.bucketName,
        JOBS_TABLE: jobsTable.tableName,
        TOPICS_TABLE: topicsTable.tableName,
        TOPIC_QUEUE_URL: topicQueue.queueUrl,
        AWS_REGION: this.region,
        // Audio attachment knobs read by serverless/src/metricool_client.py
        METRICOOL_DEFAULT_AUDIO_NAME: 'Scientific-Nipsey',
        METRICOOL_TIKTOK_AUTO_ADD_MUSIC: 'false',  // Metricool rejects this for video posts
        METRICOOL_SHOW_REEL_ON_FEED: 'true',
        METRICOOL_INSTAGRAM_MANUAL_FOR_AUDIO: 'false',
      },
      secrets: {
        GOOGLE_AI_API_KEY: ecs.Secret.fromSecretsManager(apiSecrets, 'GOOGLE_AI_API_KEY'),
        ANTHROPIC_API_KEY: ecs.Secret.fromSecretsManager(apiSecrets, 'ANTHROPIC_API_KEY'),
        GCP_SERVICE_ACCOUNT_KEY: ecs.Secret.fromSecretsManager(apiSecrets, 'GCP_SERVICE_ACCOUNT_KEY'),
        METRICOOL_API_KEY: ecs.Secret.fromSecretsManager(apiSecrets, 'METRICOOL_API_KEY'),
        METRICOOL_USER_ID: ecs.Secret.fromSecretsManager(apiSecrets, 'METRICOOL_USER_ID'),
        METRICOOL_BLOG_ID: ecs.Secret.fromSecretsManager(apiSecrets, 'METRICOOL_BLOG_ID'),
        FAL_KEY: ecs.Secret.fromSecretsManager(apiSecrets, 'FAL_KEY'),
      },
    });

    // =============================================
    // NEW: AWS Batch Infrastructure
    // =============================================

    // Batch Job Role (same permissions as ECS task role)
    const batchJobRole = new iam.Role(this, 'BatchJobRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });
    videoBucket.grantReadWrite(batchJobRole);
    musicBucket.grantRead(batchJobRole);
    jobsTable.grantReadWriteData(batchJobRole);
    topicsTable.grantReadWriteData(batchJobRole);
    topicQueue.grantConsumeMessages(batchJobRole);
    storyQueue.grantConsumeMessages(batchJobRole);
    apiSecrets.grantRead(batchJobRole);

    // Batch Execution Role
    const batchExecRole = new iam.Role(this, 'BatchExecRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });
    ecrRepo.grantPull(batchExecRole);
    apiSecrets.grantRead(batchExecRole);

    // Batch Fargate Compute Environment (Spot)
    const computeEnv = new batch.FargateComputeEnvironment(this, 'BatchComputeEnv', {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      securityGroups: [taskSecurityGroup],
      spot: true,
      maxvCpus: 32,
    });

    // Batch Job Queue
    const jobQueue = new batch.JobQueue(this, 'BatchJobQueue', {
      jobQueueName: 'iris-flow-job-queue',
      priority: 1,
      computeEnvironments: [
        { computeEnvironment: computeEnv, order: 1 },
      ],
    });

    // Shared environment variables for all Batch jobs
    const batchEnvVars: { [key: string]: string } = {
      VIDEO_BUCKET_NAME: videoBucket.bucketName,
      MUSIC_BUCKET_NAME: musicBucket.bucketName,
      JOBS_TABLE: jobsTable.tableName,
      TOPICS_TABLE: topicsTable.tableName,
      TOPIC_QUEUE_URL: topicQueue.queueUrl,
      STORY_QUEUE_URL: storyQueue.queueUrl,
      AWS_REGION: this.region,
      // Audio attachment knobs read by serverless/src/metricool_client.py
      METRICOOL_DEFAULT_AUDIO_NAME: 'Scientific-Nipsey',
      METRICOOL_TIKTOK_AUTO_ADD_MUSIC: 'false',  // Metricool rejects this for video posts
      METRICOOL_SHOW_REEL_ON_FEED: 'true',
      METRICOOL_INSTAGRAM_MANUAL_FOR_AUDIO: 'false',
    };

    // Shared secrets for Batch jobs
    const batchSecrets: { [key: string]: batch.Secret } = {
      GOOGLE_AI_API_KEY: batch.Secret.fromSecretsManager(apiSecrets, 'GOOGLE_AI_API_KEY'),
      ANTHROPIC_API_KEY: batch.Secret.fromSecretsManager(apiSecrets, 'ANTHROPIC_API_KEY'),
      GCP_SERVICE_ACCOUNT_KEY: batch.Secret.fromSecretsManager(apiSecrets, 'GCP_SERVICE_ACCOUNT_KEY'),
      METRICOOL_API_KEY: batch.Secret.fromSecretsManager(apiSecrets, 'METRICOOL_API_KEY'),
      METRICOOL_USER_ID: batch.Secret.fromSecretsManager(apiSecrets, 'METRICOOL_USER_ID'),
      METRICOOL_BLOG_ID: batch.Secret.fromSecretsManager(apiSecrets, 'METRICOOL_BLOG_ID'),
      FAL_KEY: batch.Secret.fromSecretsManager(apiSecrets, 'FAL_KEY'),
    };

    // Helper to create Batch job definitions
    const createJobDef = (
      logicalId: string,
      jobType: string,
      vcpu: number,
      memoryMiB: number,
      timeoutMinutes: number,
      jobDefName: string = `iris-flow-${jobType}`,
      extraEnv: { [key: string]: string } = {},
    ): batch.EcsJobDefinition => {
      const container = new batch.EcsFargateContainerDefinition(this, `${logicalId}Container`, {
        image: ecs.ContainerImage.fromEcrRepository(ecrRepo, 'latest'),
        cpu: vcpu,
        memory: cdk.Size.mebibytes(memoryMiB),
        jobRole: batchJobRole,
        executionRole: batchExecRole,
        environment: {
          ...batchEnvVars,
          JOB_TYPE: jobType,
          ...extraEnv,
        },
        secrets: batchSecrets,
        logging: ecs.LogDrivers.awsLogs({
          streamPrefix: jobDefName,
          logRetention: logs.RetentionDays.ONE_WEEK,
        }),
        assignPublicIp: true,
        fargatePlatformVersion: ecs.FargatePlatformVersion.LATEST,
      });

      return new batch.EcsJobDefinition(this, logicalId, {
        jobDefinitionName: jobDefName,
        container,
        timeout: cdk.Duration.minutes(timeoutMinutes),
        retryAttempts: 3,
        retryStrategies: [
          {
            action: batch.Action.RETRY,
            on: batch.Reason.SPOT_INSTANCE_RECLAIMED,
          },
          {
            action: batch.Action.RETRY,
            on: batch.Reason.CANNOT_PULL_CONTAINER,
          },
        ],
      });
    };

    // 4 STEM Batch Job Definitions (transition removed — title_cards handled inline in job_visual)
    const prepJobDef = createJobDef('PrepJobDef', 'prep', 2, 4096, 15);
    const visualJobDef = createJobDef('VisualJobDef', 'visual', 4, 16384, 30);
    const concatJobDef = createJobDef('ConcatJobDef', 'concatenate', 4, 8192, 15);
    const postprocessJobDef = createJobDef('PostprocessJobDef', 'postprocess', 1, 2048, 10);

    // 4 STORY Batch Job Definitions (PIPELINE=story selects the image-sequence path).
    // story-prep needs a longer timeout: it renders every illustration SEQUENTIALLY
    // (reference-chained for continuity) before the parallel compose Map runs.
    // story-visual is pure ffmpeg (compose a still + voiceover) so it is light.
    const STORY_ENV = { PIPELINE: 'story' };
    const storyPrepJobDef = createJobDef('StoryPrepJobDef', 'prep', 2, 4096, 25, 'iris-story-prep', STORY_ENV);
    // 2 vCPU (not 4): a full 10-clip Map at 4 vCPU each would need 40 vCPU against
    // the 32 maxvCpus cap and could not fully fan out. 8 GB is for the 4x-supersample
    // zoompan buffer in compose_story_clip, not for CPU.
    const storyVisualJobDef = createJobDef('StoryVisualJobDef', 'visual', 2, 8192, 15, 'iris-story-visual', STORY_ENV);
    // 16 GB (vs STEM concat's 8 GB): story videos have more beats (10-13), and the
    // all-at-once xfade+acrossfade filtergraph in concatenate_videos decodes every
    // 1080x1920 input simultaneously — 11 inputs OOM-killed an 8 GB container.
    const storyConcatJobDef = createJobDef('StoryConcatJobDef', 'concatenate', 4, 16384, 15, 'iris-story-concatenate', STORY_ENV);
    const storyPostprocessJobDef = createJobDef('StoryPostprocessJobDef', 'postprocess', 1, 2048, 10, 'iris-story-postprocess', STORY_ENV);

    // =============================================
    // NEW: Lambda Functions
    // =============================================

    // Orchestrator Lambda (pure boto3)
    const orchestratorFn = new lambda_.Function(this, 'OrchestratorFn', {
      functionName: 'iris-flow-orchestrator',
      runtime: lambda_.Runtime.PYTHON_3_12,
      handler: 'orchestrator.handler',
      code: lambda_.Code.fromAsset('../src/lambdas'),
      timeout: cdk.Duration.minutes(2),
      memorySize: 256,
      environment: {
        TOPIC_QUEUE_URL: topicQueue.queueUrl,
        // 60-75s target: measured watch-through falls sharply past ~90s
        // (videos over 120s retain ~11% of runtime vs ~19% median).
        TARGET_DURATION: '70',
        // AWS_REGION is set automatically by Lambda runtime
      },
    });
    topicQueue.grantConsumeMessages(orchestratorFn);

    // Read Manifest Lambda (pure boto3)
    const readManifestFn = new lambda_.Function(this, 'ReadManifestFn', {
      functionName: 'iris-flow-read-manifest',
      runtime: lambda_.Runtime.PYTHON_3_12,
      handler: 'read_manifest.handler',
      code: lambda_.Code.fromAsset('../src/lambdas'),
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      environment: {
        VIDEO_BUCKET_NAME: videoBucket.bucketName,
      },
    });
    videoBucket.grantRead(readManifestFn);

    // =============================================
    // NEW: Step Functions State Machine(s)
    //
    // The pipeline shape is IDENTICAL for both content styles:
    //   prep → read manifest → parallel visual Map → concatenate → postprocess
    // Only the Batch job definitions differ (STEM segments vs. story images).
    // buildVideoPipeline factors this so STEM and story stay byte-for-byte in sync.
    // idPrefix='' preserves the original STEM logical IDs (no resource churn).
    // =============================================
    interface PipelineJobDefs {
      prep: batch.EcsJobDefinition;
      visual: batch.EcsJobDefinition;
      concat: batch.EcsJobDefinition;
      postprocess: batch.EcsJobDefinition;
    }

    const buildVideoPipeline = (
      idPrefix: string,
      stateMachineName: string,
      logGroupName: string,
      jobDefs: PipelineJobDefs,
    ): sfn.StateMachine => {
      // Step 1: Prep Batch Job
      const prepJob = new tasks.BatchSubmitJob(this, `${idPrefix}PrepJob`, {
        jobDefinitionArn: jobDefs.prep.jobDefinitionArn,
        jobName: sfn.JsonPath.format('prep-{}', sfn.JsonPath.stringAt('$.video_id')),
        jobQueueArn: jobQueue.jobQueueArn,
        containerOverrides: {
          environment: {
            VIDEO_ID: sfn.JsonPath.stringAt('$.video_id'),
            TARGET_DURATION: sfn.JsonPath.stringAt('States.Format(\'{}\', $.target_duration)'),
            TOPIC: sfn.JsonPath.stringAt('$.topic'),
          },
        },
        resultPath: '$.prepResult',
      });

      // Step 2: Read Manifest Lambda (pipeline-agnostic — returns all segment indexes)
      const readManifest = new tasks.LambdaInvoke(this, `${idPrefix}ReadManifest`, {
        lambdaFunction: readManifestFn,
        payloadResponseOnly: true,
        resultPath: '$.manifestResult',
      });

      // Step 3: Visual Map (parallel Batch jobs)
      const visualJob = new tasks.BatchSubmitJob(this, `${idPrefix}VisualJob`, {
        jobDefinitionArn: jobDefs.visual.jobDefinitionArn,
        jobName: sfn.JsonPath.format('visual-{}-{}',
          sfn.JsonPath.stringAt('$.video_id'),
          sfn.JsonPath.stringAt('States.Format(\'{}\', $.segment_index)')
        ),
        jobQueueArn: jobQueue.jobQueueArn,
        containerOverrides: {
          environment: {
            VIDEO_ID: sfn.JsonPath.stringAt('$.video_id'),
            SEGMENT_INDEX: sfn.JsonPath.stringAt('States.Format(\'{}\', $.segment_index)'),
          },
        },
      });

      // Catch errors on individual visual jobs so one failure doesn't kill the pipeline
      const visualJobWithCatch = visualJob.addCatch(new sfn.Pass(this, `${idPrefix}VisualJobFailed`, {
        result: sfn.Result.fromObject({ status: 'FAILED' }),
      }), { resultPath: '$.error' });

      const visualMap = new sfn.Map(this, `${idPrefix}VisualMap`, {
        itemsPath: '$.manifestResult.visualSegments',
        maxConcurrency: 10,
        resultPath: '$.visualResults',
      });
      visualMap.itemProcessor(visualJobWithCatch);

      // Step 4: Concatenate Batch Job
      const concatJob = new tasks.BatchSubmitJob(this, `${idPrefix}ConcatJob`, {
        jobDefinitionArn: jobDefs.concat.jobDefinitionArn,
        jobName: sfn.JsonPath.format('concat-{}', sfn.JsonPath.stringAt('$.video_id')),
        jobQueueArn: jobQueue.jobQueueArn,
        containerOverrides: {
          environment: {
            VIDEO_ID: sfn.JsonPath.stringAt('$.video_id'),
          },
        },
        resultPath: '$.concatResult',
      });

      // Step 5: Postprocess Batch Job
      // The orchestrator Lambda always sets schedule_time, include_youtube AND
      // include_tiktok on the execution input, so all three paths are guaranteed
      // present. include_youtube caps YouTube at 2 posts/day; include_tiktok caps
      // TikTok at 3 posts/day: postprocess passes them to Metricool, which drops
      // the network when false. States.Format stringifies the bools for env vars.
      const postprocessJob = new tasks.BatchSubmitJob(this, `${idPrefix}PostprocessJob`, {
        jobDefinitionArn: jobDefs.postprocess.jobDefinitionArn,
        jobName: sfn.JsonPath.format('postprocess-{}', sfn.JsonPath.stringAt('$.video_id')),
        jobQueueArn: jobQueue.jobQueueArn,
        containerOverrides: {
          environment: {
            VIDEO_ID: sfn.JsonPath.stringAt('$.video_id'),
            SCHEDULE_TIME: sfn.JsonPath.stringAt('$.schedule_time'),
            INCLUDE_YOUTUBE: sfn.JsonPath.stringAt("States.Format('{}', $.include_youtube)"),
            INCLUDE_TIKTOK: sfn.JsonPath.stringAt("States.Format('{}', $.include_tiktok)"),
          },
        },
        resultPath: '$.postprocessResult',
      });

      const definition = prepJob
        .next(readManifest)
        .next(visualMap)
        .next(concatJob)
        .next(postprocessJob);

      return new sfn.StateMachine(this, `${idPrefix}VideoStateMachine`, {
        stateMachineName,
        definitionBody: sfn.DefinitionBody.fromChainable(definition),
        timeout: cdk.Duration.hours(2),
        logs: {
          destination: new logs.LogGroup(this, `${idPrefix}SfnLogGroup`, {
            logGroupName,
            retention: logs.RetentionDays.ONE_WEEK,
            removalPolicy: cdk.RemovalPolicy.DESTROY,
          }),
          level: sfn.LogLevel.ERROR,
        },
      });
    };

    // STEM pipeline (idPrefix='' keeps the original logical IDs → no replacement)
    const stateMachine = buildVideoPipeline(
      '', 'iris-flow-video-pipeline', '/iris-flow/state-machine',
      { prep: prepJobDef, visual: visualJobDef, concat: concatJobDef, postprocess: postprocessJobDef },
    );
    stateMachine.grantStartExecution(orchestratorFn);
    orchestratorFn.addEnvironment('STATE_MACHINE_ARN', stateMachine.stateMachineArn);

    // STORY pipeline
    const storyStateMachine = buildVideoPipeline(
      'Story', 'iris-story-pipeline', '/iris-flow/story-state-machine',
      { prep: storyPrepJobDef, visual: storyVisualJobDef, concat: storyConcatJobDef, postprocess: storyPostprocessJobDef },
    );

    // Story orchestrator Lambda — same code as the STEM orchestrator, different env.
    const storyOrchestratorFn = new lambda_.Function(this, 'StoryOrchestratorFn', {
      functionName: 'iris-story-orchestrator',
      runtime: lambda_.Runtime.PYTHON_3_12,
      handler: 'orchestrator.handler',
      code: lambda_.Code.fromAsset('../src/lambdas'),
      timeout: cdk.Duration.minutes(2),
      memorySize: 256,
      environment: {
        QUEUE_URL: storyQueue.queueUrl,
        STATE_MACHINE_ARN: storyStateMachine.stateMachineArn,
        TARGET_DURATION: '75',     // story videos target 60-90s
        EXEC_PREFIX: 'iris-story',
      },
    });
    storyQueue.grantConsumeMessages(storyOrchestratorFn);
    storyStateMachine.grantStartExecution(storyOrchestratorFn);

    // =============================================
    // EventBridge: STEM orchestrator trigger — PAUSED.
    //
    // All three rules below are DISABLED. The STEM pipeline itself stays fully
    // deployed (state machine, orchestrator, Batch job defs, queue), it is only
    // no longer triggered: iris-motion has taken over these five daily slots and
    // drains the SAME iris-flow-topic-queue, so leaving these enabled would put
    // two pipelines in a race for every topic and double the daily post volume.
    //
    // TO RESUME: set enabled back to true on the rules you want (they are
    // independent) and `cdk deploy` this stack — and disable the matching
    // iris-motion-daily-* rule in motion/cdk/lib/iris-motion-stack.ts first,
    // since the two schedules are hour-for-hour identical.
    //
    // The hours and flags are preserved exactly as they were, and are mirrored
    // by iris-motion's rules: YouTube 2 posts/day, TikTok 3 posts/day (its
    // For-You distribution collapsed under the 5×/day identical-crosspost
    // cadence), IG/Facebook all 5. The `include_youtube` / `include_tiktok`
    // constants thread onto the execution input → postprocess → Metricool,
    // which drops a network when its flag is false.
    // =============================================

    // PAUSED — 2× daily with YouTube + TikTok. 18:00 UTC = 1pm EST, 00:00 = 7pm.
    const scheduleRuleYouTube = new events.Rule(this, 'DailyScheduleYouTube', {
      ruleName: 'iris-flow-daily-youtube',
      description:
        'PAUSED — STEM orchestrator 2× daily WITH YouTube + TikTok (1pm, 7pm EST); ' +
        'superseded by iris-motion-daily-youtube. Set enabled=true here and disable ' +
        'that rule to resume.',
      enabled: false,
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '18,0', // 2× daily, UTC (only fires when enabled)
      }),
    });
    scheduleRuleYouTube.addTarget(new targets.LambdaFunction(orchestratorFn, {
      event: events.RuleTargetInput.fromObject({ include_youtube: true, include_tiktok: true }),
    }));

    // PAUSED — 1× daily with TikTok (no YouTube). 15:00 UTC = 10am EST.
    const scheduleRuleTikTok = new events.Rule(this, 'DailyScheduleTikTok', {
      ruleName: 'iris-flow-daily-tiktok',
      description:
        'PAUSED — STEM orchestrator 1× daily WITH TikTok, no YouTube (10am EST); ' +
        'superseded by iris-motion-daily-tiktok. Set enabled=true here and disable ' +
        'that rule to resume.',
      enabled: false,
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '15', // 1× daily, UTC (only fires when enabled)
      }),
    });
    scheduleRuleTikTok.addTarget(new targets.LambdaFunction(orchestratorFn, {
      event: events.RuleTargetInput.fromObject({ include_youtube: false, include_tiktok: true }),
    }));

    // PAUSED — 2× daily IG/Facebook only. 11:00 UTC = 6am, 21:00 = 4pm EST.
    const scheduleRuleIgFb = new events.Rule(this, 'DailyScheduleNoYouTube', {
      ruleName: 'iris-flow-daily-no-youtube',
      description:
        'PAUSED — STEM orchestrator 2× daily IG/Facebook only (6am, 4pm EST); ' +
        'superseded by iris-motion-daily-no-youtube. Set enabled=true here and disable ' +
        'that rule to resume.',
      enabled: false,
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '11,21', // 2× daily, UTC (only fires when enabled)
      }),
    });
    scheduleRuleIgFb.addTarget(new targets.LambdaFunction(orchestratorFn, {
      event: events.RuleTargetInput.fromObject({ include_youtube: false, include_tiktok: false }),
    }));

    // =============================================
    // Weekly retention-KPI report — the content mix is steered by measured
    // watch-through, so surface it every Monday instead of waiting for a
    // manual deep-dive. Pulls IG Reels analytics from Metricool, joins S3
    // manifests for per-category medians, emails via the alerts topic.
    // =============================================
    const retentionReportFn = new lambda_.Function(this, 'RetentionReportFn', {
      functionName: 'iris-flow-retention-report',
      runtime: lambda_.Runtime.PYTHON_3_12,
      handler: 'retention_report.handler',
      code: lambda_.Code.fromAsset('../src/lambdas'),
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
      environment: {
        ALERTS_TOPIC_ARN: alertsTopic.topicArn,
        VIDEO_BUCKET_NAME: videoBucket.bucketName,
        API_SECRET_ID: 'iris-flow/api-keys',
      },
    });
    videoBucket.grantRead(retentionReportFn);
    alertsTopic.grantPublish(retentionReportFn);
    apiSecrets.grantRead(retentionReportFn);

    const retentionReportRule = new events.Rule(this, 'WeeklyRetentionReport', {
      ruleName: 'iris-flow-weekly-retention-report',
      description: 'Weekly IG watch-through report (Mondays 13:00 UTC = 8/9am ET)',
      enabled: true,
      schedule: events.Schedule.cron({ minute: '0', hour: '13', weekDay: 'MON' }),
    });
    retentionReportRule.addTarget(new targets.LambdaFunction(retentionReportFn));

    // Story schedule — PAUSED. The story pipeline (state machine, orchestrator,
    // queue, and Batch job defs) stays fully deployed, but this EventBridge rule
    // is DISABLED so no new story executions are triggered. Flip `enabled` back
    // to true to resume. When enabled it fires 4× daily at 02/13/18/22 UTC,
    // offset ~2h from the STEM triggers so the two pipelines don't hit the
    // Gemini / Anthropic APIs at the same instant.
    const storyScheduleRule = new events.Rule(this, 'StoryDailySchedule', {
      ruleName: 'iris-story-daily',
      description: 'PAUSED — story orchestrator trigger (disabled; set enabled=true to resume)',
      enabled: false,
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '2,13,18,22', // 4× daily, UTC (only fires when enabled)
      }),
    });
    storyScheduleRule.addTarget(new targets.LambdaFunction(storyOrchestratorFn));

    // =====================
    // Outputs
    // =====================
    new cdk.CfnOutput(this, 'StoryQueueUrl', {
      value: storyQueue.queueUrl,
      description: 'SQS queue URL for story topic input',
    });

    new cdk.CfnOutput(this, 'StoryStateMachineArn', {
      value: storyStateMachine.stateMachineArn,
      description: 'Story Step Functions state machine ARN',
    });

    new cdk.CfnOutput(this, 'VideoBucketName', {
      value: videoBucket.bucketName,
      description: 'S3 bucket for video assets',
    });

    new cdk.CfnOutput(this, 'MusicBucketName', {
      value: musicBucket.bucketName,
      description: 'S3 bucket for background music',
    });

    new cdk.CfnOutput(this, 'JobsTableName', {
      value: jobsTable.tableName,
      description: 'DynamoDB table for job tracking',
    });

    new cdk.CfnOutput(this, 'TopicsTableName', {
      value: topicsTable.tableName,
      description: 'DynamoDB table for topic tracking',
    });

    new cdk.CfnOutput(this, 'TopicQueueUrl', {
      value: topicQueue.queueUrl,
      description: 'SQS queue URL for topic input',
    });

    new cdk.CfnOutput(this, 'EcrRepoUri', {
      value: ecrRepo.repositoryUri,
      description: 'ECR repository URI for Docker images',
    });

    new cdk.CfnOutput(this, 'ClusterArn', {
      value: cluster.clusterArn,
      description: 'ECS cluster ARN (legacy — kept for rollback)',
    });

    new cdk.CfnOutput(this, 'SecretsArn', {
      value: apiSecrets.secretArn,
      description: 'Secrets Manager ARN',
    });

    new cdk.CfnOutput(this, 'StateMachineArn', {
      value: stateMachine.stateMachineArn,
      description: 'Step Functions state machine ARN',
    });

    new cdk.CfnOutput(this, 'OrchestratorFnArn', {
      value: orchestratorFn.functionArn,
      description: 'Orchestrator Lambda ARN',
    });

    new cdk.CfnOutput(this, 'BatchJobQueueArn', {
      value: jobQueue.jobQueueArn,
      description: 'Batch job queue ARN',
    });
  }
}
