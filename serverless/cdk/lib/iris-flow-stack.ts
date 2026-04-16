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
      AWS_REGION: this.region,
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
        },
        secrets: batchSecrets,
        logging: ecs.LogDrivers.awsLogs({
          streamPrefix: `iris-flow-${jobType}`,
          logRetention: logs.RetentionDays.ONE_WEEK,
        }),
        assignPublicIp: true,
        fargatePlatformVersion: ecs.FargatePlatformVersion.LATEST,
      });

      return new batch.EcsJobDefinition(this, logicalId, {
        jobDefinitionName: `iris-flow-${jobType}`,
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

    // 5 Batch Job Definitions
    const prepJobDef = createJobDef('PrepJobDef', 'prep', 2, 4096, 15);
    const visualJobDef = createJobDef('VisualJobDef', 'visual', 4, 16384, 30);
    const transitionJobDef = createJobDef('TransitionJobDef', 'transition', 2, 4096, 10);
    const concatJobDef = createJobDef('ConcatJobDef', 'concatenate', 4, 8192, 15);
    const postprocessJobDef = createJobDef('PostprocessJobDef', 'postprocess', 1, 2048, 10);

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
    // NEW: Step Functions State Machine
    // =============================================

    // Step 1: Prep Batch Job
    const prepJob = new tasks.BatchSubmitJob(this, 'PrepJob', {
      jobDefinitionArn: prepJobDef.jobDefinitionArn,
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

    // Step 2: Read Manifest Lambda
    const readManifest = new tasks.LambdaInvoke(this, 'ReadManifest', {
      lambdaFunction: readManifestFn,
      payloadResponseOnly: true,
      resultPath: '$.manifestResult',
    });

    // Step 3: Visual Map (parallel Batch jobs)
    const visualJob = new tasks.BatchSubmitJob(this, 'VisualJob', {
      jobDefinitionArn: visualJobDef.jobDefinitionArn,
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
    const visualJobWithCatch = visualJob.addCatch(new sfn.Pass(this, 'VisualJobFailed', {
      result: sfn.Result.fromObject({ status: 'FAILED' }),
    }), { resultPath: '$.error' });

    const visualMap = new sfn.Map(this, 'VisualMap', {
      itemsPath: '$.manifestResult.visualSegments',
      maxConcurrency: 10,
      resultPath: '$.visualResults',
    });
    visualMap.itemProcessor(visualJobWithCatch);

    // Step 4: Transition Map (parallel Batch jobs)
    const transitionJob = new tasks.BatchSubmitJob(this, 'TransitionJob', {
      jobDefinitionArn: transitionJobDef.jobDefinitionArn,
      jobName: sfn.JsonPath.format('transition-{}-{}',
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

    // Catch errors on individual transition jobs
    const transitionJobWithCatch = transitionJob.addCatch(new sfn.Pass(this, 'TransitionJobFailed', {
      result: sfn.Result.fromObject({ status: 'FAILED' }),
    }), { resultPath: '$.error' });

    const transitionMap = new sfn.Map(this, 'TransitionMap', {
      itemsPath: '$.manifestResult.transitionSegments',
      maxConcurrency: 10,
      resultPath: '$.transitionResults',
    });
    transitionMap.itemProcessor(transitionJobWithCatch);

    // Step 5: Concatenate Batch Job
    const concatJob = new tasks.BatchSubmitJob(this, 'ConcatJob', {
      jobDefinitionArn: concatJobDef.jobDefinitionArn,
      jobName: sfn.JsonPath.format('concat-{}', sfn.JsonPath.stringAt('$.video_id')),
      jobQueueArn: jobQueue.jobQueueArn,
      containerOverrides: {
        environment: {
          VIDEO_ID: sfn.JsonPath.stringAt('$.video_id'),
        },
      },
      resultPath: '$.concatResult',
    });

    // Step 6: Postprocess Batch Job
    const postprocessJob = new tasks.BatchSubmitJob(this, 'PostprocessJob', {
      jobDefinitionArn: postprocessJobDef.jobDefinitionArn,
      jobName: sfn.JsonPath.format('postprocess-{}', sfn.JsonPath.stringAt('$.video_id')),
      jobQueueArn: jobQueue.jobQueueArn,
      containerOverrides: {
        environment: {
          VIDEO_ID: sfn.JsonPath.stringAt('$.video_id'),
          SCHEDULE_TIME: sfn.JsonPath.stringAt('$.schedule_time'),
        },
      },
      resultPath: '$.postprocessResult',
    });

    // Chain the state machine
    const definition = prepJob
      .next(readManifest)
      .next(visualMap)
      .next(transitionMap)
      .next(concatJob)
      .next(postprocessJob);

    const stateMachine = new sfn.StateMachine(this, 'VideoStateMachine', {
      stateMachineName: 'iris-flow-video-pipeline',
      definitionBody: sfn.DefinitionBody.fromChainable(definition),
      timeout: cdk.Duration.hours(2),
      logs: {
        destination: new logs.LogGroup(this, 'SfnLogGroup', {
          logGroupName: '/iris-flow/state-machine',
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
        level: sfn.LogLevel.ERROR,
      },
    });

    // Grant orchestrator Lambda permission to start executions
    stateMachine.grantStartExecution(orchestratorFn);
    orchestratorFn.addEnvironment('STATE_MACHINE_ARN', stateMachine.stateMachineArn);

    // =============================================
    // EventBridge: target Orchestrator Lambda (not ECS)
    // =============================================
    const scheduleRule = new events.Rule(this, 'DailySchedule', {
      ruleName: 'iris-flow-daily-morning',
      description: 'Trigger orchestrator Lambda at 6am EST daily',
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '11', // 6am EST = 11:00 UTC
      }),
    });

    scheduleRule.addTarget(new targets.LambdaFunction(orchestratorFn));

    // =====================
    // Outputs
    // =====================
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
