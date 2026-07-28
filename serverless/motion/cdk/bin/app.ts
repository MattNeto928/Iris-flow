#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { IrisMotionStack } from '../lib/iris-motion-stack';

const app = new cdk.App();

new IrisMotionStack(app, 'IrisMotionStack', {
  env: {
    // Pinned fallback, unlike IrisFlowStack: the S3 bucket name embeds the
    // account, and an env-agnostic synth turns that into an unresolved
    // ${AWS::AccountId} token. Fine for CloudFormation, but it means a plain
    // `cdk synth` with no credentials no longer prints the real bucket name --
    // which is the one thing you check before pushing an image to it.
    account: process.env.CDK_DEFAULT_ACCOUNT ?? '482625028438',
    region: 'us-east-1',
  },
  description: 'iris-motion: sharded headless-Chrome 3D video renderer (Batch + Step Functions)',
});
