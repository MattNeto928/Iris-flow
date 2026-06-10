#!/usr/bin/env python3
"""
Seed the story SQS queue (iris-flow-story-queue) with origin-story topics.

These are "how X came to be" stories — scientific discoveries, invention origins,
dark/forgotten histories, ideas once called impossible. Each is tagged with a hook
angle the story_client understands ([ACC]/[DARK]/[IMP]/[HIDDEN]/[WHY]/[NEAR]/[RIVAL]/
[FORBID]). The story orchestrator drains one per run; when the queue is empty it
generates a fresh topic via StoryTopicManager.

The angles + subjects below were chosen for completion-rate potential: surprising
contrast, a concrete anchor (name/date/number), and an everyday "and that's why..."
payoff. Curated from what reliably performs in the origin-story / "today-I-learned"
short-form niche.

Usage:
  python scripts/populate_story_topics.py                 # enqueue all
  python scripts/populate_story_topics.py --dry-run       # print only
  python scripts/populate_story_topics.py --limit 20      # first N
  STORY_QUEUE_URL=... python scripts/populate_story_topics.py
"""

import os
import json
import uuid
import argparse
import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
DEFAULT_QUEUE_NAME = "iris-flow-story-queue"

# (category, "[ANGLE] one-line story prompt")
TOPICS = [
    # --- accidental discoveries ---
    ("scientific_discovery", "[ACC] How Alexander Fleming's messy lab and a summer vacation let mold contaminate a petri dish and gave the world penicillin in 1928."),
    ("invention_origin", "[ACC] How radar engineer Percy Spencer noticed a chocolate bar melting in his pocket and accidentally invented the microwave oven."),
    ("invention_origin", "[ACC] How a 3M scientist trying to make a super-strong glue failed, made a weak one instead, and that failure became the Post-it Note."),
    ("scientific_discovery", "[ACC] How a graduate student left a dish out over a long weekend and stumbled onto vulcanized rubber, the reason your tires exist."),
    ("invention_origin", "[ACC] How a candy maker's broken machine spat out the first Coca-Cola, and how it was originally sold as a medicine."),
    ("scientific_discovery", "[ACC] How Wilhelm Roentgen noticed a mysterious glow in his darkened lab and discovered X-rays without meaning to, in 1895."),
    ("invention_origin", "[ACC] How burrs sticking to a hunter's dog on an alpine walk inspired Velcro after he looked at them under a microscope."),
    ("scientific_discovery", "[ACC] How a sloppy experiment with a forgotten Petri dish revealed the first antibiotic and changed human lifespan forever."),
    ("invention_origin", "[ACC] How a worker at a popsicle plant left a cup of soda with a stir stick on a freezing porch overnight and invented the popsicle, age eleven."),
    ("scientific_discovery", "[ACC] How saccharin, the first artificial sweetener, was discovered because a chemist forgot to wash his hands before dinner."),

    # --- dark / strange origins of everyday things ---
    ("dark_origin", "[DARK] How the cheerful breakfast cereal you eat was invented to suppress urges, by a man with very strange beliefs about health."),
    ("dark_origin", "[DARK] How the treadmill at your gym began as a brutal Victorian prison punishment device meant to break inmates."),
    ("dark_origin", "[DARK] How ketchup was once sold as a medicine, with doctors prescribing tomato pills to cure your stomach."),
    ("dark_origin", "[DARK] How high heels started as footwear for male Persian cavalry, not a fashion statement at all."),
    ("dark_origin", "[DARK] How the color mauve, and the entire fashion industry's obsession with it, came from a teenager trying to cure malaria."),
    ("dark_origin", "[DARK] How Listerine was marketed by inventing a scary-sounding disease, bad breath, to sell a product nobody knew they needed."),
    ("dark_origin", "[DARK] How graham crackers were invented by a preacher who believed bland food would calm the body's sinful impulses."),
    ("dark_origin", "[DARK] How the modern wedding ring on the left hand traces back to an ancient belief in a vein running straight to the heart."),

    # --- told it was impossible ---
    ("impossible_idea", "[IMP] How James Dyson built 5,127 failed vacuum prototypes over fifteen years before one finally worked."),
    ("impossible_idea", "[IMP] How everyone laughed at the idea of heavier-than-air flight weeks before two bicycle mechanics flew at Kitty Hawk."),
    ("impossible_idea", "[IMP] How a young patent clerk nobody took seriously rewrote our understanding of time and space in a single year."),
    ("impossible_idea", "[IMP] How doctors mocked a Hungarian physician for suggesting they wash their hands, and how he died before being proven right."),
    ("impossible_idea", "[IMP] How a self-taught Indian clerk mailed wild equations to Cambridge that turned out to be decades ahead of their time."),
    ("impossible_idea", "[IMP] How the inventor of the telephone was told it was a useless toy with no commercial value."),

    # --- forgotten / wrong-credit inventors ---
    ("forgotten_inventor", "[HIDDEN] How a Hollywood movie star co-invented the frequency-hopping technology that now powers your Wi-Fi and Bluetooth."),
    ("forgotten_inventor", "[HIDDEN] How a young woman's X-ray photograph cracked the structure of DNA, while two men took the Nobel Prize."),
    ("forgotten_inventor", "[HIDDEN] How the programmer who wrote the first algorithm lived a century before any computer existed to run it."),
    ("forgotten_inventor", "[HIDDEN] How the real inventor of the lightbulb's key component died poor while a famous name took the glory."),
    ("forgotten_inventor", "[HIDDEN] How a NASA mathematician's hand calculations put astronauts in orbit, uncredited for decades."),

    # --- everyday 'why' ---
    ("everyday_why", "[WHY] Why every clock in advertisements is set to 10:10, a tiny design conspiracy hiding in plain sight."),
    ("everyday_why", "[WHY] Why your keyboard's letters are scrambled into QWERTY instead of alphabetical order, and the jam it was built to prevent."),
    ("everyday_why", "[WHY] Why there's a tiny fifth pocket inside your jeans pocket, a holdover from a vanished pocket-watch era."),
    ("everyday_why", "[WHY] Why ambulances have the word AMBULANCE printed backwards across the front."),
    ("everyday_why", "[WHY] Why the QWERTY shape of a school bus is yellow, chosen by a committee for one specific reason about your eyes."),

    # --- near-misses ---
    ("scientific_discovery", "[NEAR] How one Soviet officer's refusal to follow protocol in 1983 quietly prevented a global nuclear war."),
    ("invention_origin", "[NEAR] How the man who invented the World Wide Web gave it away for free instead of becoming the richest person alive."),

    # --- rivalries ---
    ("scientific_discovery", "[RIVAL] How the bitter race between Edison and Tesla over electricity decided which current powers your home today."),
    ("invention_origin", "[RIVAL] How two men filed telephone patents on the very same day, and how hours decided who history remembers."),

    # --- forbidden / suppressed ---
    ("dark_origin", "[FORBID] How a lightbulb in a California firehouse has burned for over 120 years, and the secret pact to make bulbs die sooner."),
    ("dark_origin", "[FORBID] How the recipe for a vivid Renaissance paint color was guarded so jealously that its makers were sworn to secrecy."),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print topics, don't enqueue")
    ap.add_argument("--limit", type=int, default=None, help="only first N topics")
    ap.add_argument("--queue-url", default=os.environ.get("STORY_QUEUE_URL"))
    args = ap.parse_args()

    topics = TOPICS[: args.limit] if args.limit else TOPICS

    queue_url = args.queue_url
    if not queue_url and not args.dry_run:
        sqs = boto3.client("sqs", region_name=REGION)
        queue_url = sqs.get_queue_url(QueueName=DEFAULT_QUEUE_NAME)["QueueUrl"]

    print(f"{'DRY-RUN: ' if args.dry_run else ''}{len(topics)} story topics "
          f"{'(would target ' if args.dry_run else '→ '}{queue_url or DEFAULT_QUEUE_NAME}")

    if args.dry_run:
        for cat, prompt in topics:
            print(f"  [{cat}] {prompt}")
        return

    sqs = boto3.client("sqs", region_name=REGION)
    sent = 0
    for cat, prompt in topics:
        body = {
            "topic_id": str(uuid.uuid4())[:8],
            "prompt": prompt,
            "category": cat,
        }
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))
        sent += 1
    print(f"Enqueued {sent} story topics to {queue_url}")


if __name__ == "__main__":
    main()
