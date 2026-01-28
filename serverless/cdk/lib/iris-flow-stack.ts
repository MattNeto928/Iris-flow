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
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, // Private bucket, only app needs access
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // =====================
    // DynamoDB Tables
    // =====================
    
    // Jobs table - tracks generation jobs
    const jobsTable = new dynamodb.Table(this, 'JobsTable', {
      tableName: 'iris-flow-jobs',
      partitionKey: { name: 'job_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'ttl',
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // Topics table - tracks generated topics (from queue or auto-generated)
    const topicsTable = new dynamodb.Table(this, 'TopicsTable', {
      tableName: 'iris-flow-topics',
      partitionKey: { name: 'topic_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'created_at', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'ttl',
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // GSI for querying topics by category
    topicsTable.addGlobalSecondaryIndex({
      indexName: 'category-index',
      partitionKey: { name: 'category', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'created_at', type: dynamodb.AttributeType.STRING },
    });

    // =====================
    // SQS Queue for topic input
    // User can populate this with topics; if empty, auto-generate
    // =====================
    const topicQueue = new sqs.Queue(this, 'TopicQueue', {
      queueName: 'iris-flow-topic-queue',
      visibilityTimeout: cdk.Duration.minutes(30), // Long enough for video generation
      retentionPeriod: cdk.Duration.days(14),
    });

    // =====================
    // Secrets Manager for API keys
    // Import existing secret (created separately to avoid secrets in CDK)
    // =====================
    const apiSecrets = secretsmanager.Secret.fromSecretNameV2(
      this, 'ApiSecrets', 'iris-flow/api-keys'
    );

    // =====================
    // VPC for ECS (no NAT Gateway - use public subnets for cost savings)
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
    // ECS Cluster with Spot Capacity
    // =====================
    const cluster = new ecs.Cluster(this, 'IrisFlowCluster', {
      clusterName: 'iris-flow-cluster',
      vpc,
      containerInsights: true,
      enableFargateCapacityProviders: true,
    });

    // =====================
    // Task Role - what the container can access
    // =====================
    const taskRole = new iam.Role(this, 'TaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });

    // Grant permissions
    videoBucket.grantReadWrite(taskRole);
    musicBucket.grantRead(taskRole);
    jobsTable.grantReadWriteData(taskRole);
    topicsTable.grantReadWriteData(taskRole);
    topicQueue.grantConsumeMessages(taskRole);
    apiSecrets.grantRead(taskRole);

    // =====================
    // Task Execution Role - what ECS needs to run the container
    // =====================
    const executionRole = new iam.Role(this, 'ExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    ecrRepo.grantPull(executionRole);
    apiSecrets.grantRead(executionRole);

    // =====================
    // ECS Task Definition (Fargate Spot)
    // 8 GB RAM, 2 vCPU for video rendering
    // =====================
    const taskDefinition = new ecs.FargateTaskDefinition(this, 'IrisFlowTask', {
      memoryLimitMiB: 8192,
      cpu: 2048,
      taskRole,
      executionRole,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.X86_64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });

    // Container definition
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
      },
    });

    // =====================
    // Security Group for ECS Tasks
    // =====================
    const taskSecurityGroup = new ec2.SecurityGroup(this, 'TaskSecurityGroup', {
      vpc,
      description: 'Security group for Iris Flow video generation tasks',
      allowAllOutbound: true,
    });

    // =====================
    // EventBridge Rule: 4 times daily (9am, 12pm, 3pm, 7pm EST)
    // EST = UTC-5 (standard) or UTC-4 (daylight saving)
    // Using UTC times: 14:00, 17:00, 20:00, 00:00
    // =====================
    // EventBridge Scheduled Rule - Daily at 6am EST
    // At 6am, generates 2-5 random videos scheduled throughout the day
    // =====================
    const scheduleRule = new events.Rule(this, 'DailySchedule', {
      ruleName: 'iris-flow-daily-morning',
      description: 'Trigger video generation at 6am EST daily - generates 2-5 random posts',
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '11',  // 6am EST = 11:00 UTC (during EST, 10:00 UTC during EDT)
      }),
    });

    // ECS Task target
    scheduleRule.addTarget(
      new targets.EcsTask({
        cluster,
        taskDefinition,
        taskCount: 1,
        subnetSelection: { subnetType: ec2.SubnetType.PUBLIC },
        assignPublicIp: true,
        securityGroups: [taskSecurityGroup],
        platformVersion: ecs.FargatePlatformVersion.LATEST,
        enableExecuteCommand: true,
      })
    );

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
      description: 'ECS cluster ARN',
    });

    new cdk.CfnOutput(this, 'SecretsArn', {
      value: apiSecrets.secretArn,
      description: 'Secrets Manager ARN - update with API keys',
    });
  }
}
