import os
from google import genai
from google.genai import types

api_key = os.environ.get("GOOGLE_AI_API_KEY")
if not api_key:
    # Try to load from .env if not in env vars
    try:
        with open(".env", "r") as f:
            for line in f:
                if line.startswith("GOOGLE_AI_API_KEY="):
                    api_key = line.strip().split("=", 1)[1]
                    break
    except:
        pass

print(f"API Key found: {bool(api_key)}")
client = genai.Client(api_key=api_key)

def test_duration(seconds):
    print(f"\nTesting duration: {seconds} (type: {type(seconds)})")
    try:
        config = types.GenerateVideosConfig(
            aspect_ratio="16:9",
            resolution="720p",
            duration_seconds=seconds,
        )
        print("Config created successfully.")
        
        operation = client.models.generate_videos(
            model="veo-2.0-generate-preview",
            prompt="A test video",
            config=config,
        )
        print("Operation started successfully (ID: " + str(operation.name if hasattr(operation, 'name') else 'unknown') + ")")
    except Exception as e:
        print(f"Error: {e}")

# Test cases
print("--- RETEST 5 ---")
test_duration(5)

print("\n--- TEST 6 ---")
test_duration(6)

print("\n--- TEST 7 ---")
test_duration(7)

