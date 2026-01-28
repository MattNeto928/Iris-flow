#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { IrisFlowStack } from '../lib/iris-flow-stack';

const app = new cdk.App();

new IrisFlowStack(app, 'IrisFlowStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: 'us-east-1',
  },
});
