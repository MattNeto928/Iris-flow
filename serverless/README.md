# Iris Flow - Serverless Video Automation

Automated video generation pipeline that creates educational STEM videos and schedules them to Instagram Reels, TikTok, YouTube Shorts, and Facebook Reels.

## Architecture

- **Compute**: ECS Fargate (Spot for cost savings)
- **Storage**: S3 for videos, DynamoDB for job/topic tracking
- **Queue**: SQS for user-provided topics
- **Scheduler**: EventBridge (4x daily: 9am, 12pm, 3pm, 7pm EST)
- **APIs**: Gemini (segments/Veo), Claude (PySim/Manim), Chirp 3 HD (TTS), Metricool

## How It Works

1. **EventBridge** triggers ECS task 4x daily
2. **Topic Manager** checks SQS queue for topics; if empty, generates one with Gemini
3. **Video Pipeline** generates segments (TTS + PySim/Veo/Manim visuals)
4. **FFmpeg** concatenates all segments into final video (9:16 vertical)
5. **S3** stores the video
6. **Metricool** schedules post for 24 hours later to all 3 platforms
7. **DynamoDB** records topic with 30-day TTL to prevent repeats

## Deployment

### 1. Deploy Infrastructure

```bash
chmod +x deploy.sh build-and-push.sh
./deploy.sh
```

### 2. Add API Keys to Secrets Manager

```bash
aws secretsmanager put-secret-value \
  --secret-id iris-flow/api-keys \
  --secret-string '{
    "GOOGLE_AI_API_KEY": "your-gemini-key",
    "ANTHROPIC_API_KEY": "your-anthropic-key",
    "GCP_SERVICE_ACCOUNT_KEY": "base64-encoded-service-account-json",
    "METRICOOL_API_KEY": "your-metricool-key",
    "METRICOOL_USER_ID": "your-user-id",
    "METRICOOL_BLOG_ID": "your-blog-id"
  }'
```

**Note:** The GCP service account key should be base64 encoded:
```bash
base64 -i your-gcp-key.json
```

### 3. Build & Push Docker Image

```bash
./build-and-push.sh
```

## Adding Topics to the Queue

Send a message to SQS to queue a specific topic:

```bash
aws sqs send-message \
  --queue-url "https://sqs.us-east-1.amazonaws.com/YOUR_ACCOUNT/iris-flow-topic-queue" \
  --message-body '{
    "prompt": "Visualize the Monty Hall problem step by step...",
    "category": "counterintuitive_phenomena"
  }'
```

If the queue is empty, the system auto-generates topics like gemini_manim.

## Directory Structure

```
serverless/
├── cdk/                      # CDK infrastructure
│   ├── bin/app.ts
│   ├── lib/iris-flow-stack.ts
│   └── package.json
├── docker/
│   └── Dockerfile            # Container with Manim, TTS, FFmpeg
├── src/
│   ├── handler.py            # Main entry point
│   ├── topic_manager.py      # SQS queue + Gemini topic generation
│   ├── video_pipeline.py     # Segment processing + S3 upload
│   ├── metricool_client.py   # Social media scheduling
│   └── services/
│       ├── tts_client.py     # Chirp 3 HD TTS
│       ├── gemini_client.py  # Segment generation
│       ├── pysim_service.py  # Python simulations
│       ├── veo_service.py    # Veo video generation
│       └── manim_service.py  # Manim animations
├── deploy.sh                 # Deploy CDK
├── build-and-push.sh         # Build Docker image
└── README.md
```

## Estimated Costs

| Service | Daily | Monthly |
|---------|-------|---------|
| AWS (Spot Fargate, S3, DynamoDB) | ~$0.80 | ~$24 |
| Gemini API | ~$1.00 | ~$30 |
| Anthropic API | ~$0.50 | ~$15 |
| GCP TTS (Chirp 3 HD) | ~$0.20 | ~$6 |
| **Total** | ~$2.50 | **~$75** |
