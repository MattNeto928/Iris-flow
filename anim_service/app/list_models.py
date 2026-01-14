import os
from google import genai

# Configure client exactly as in veo_client.py
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "gen-lang-client-0142432606")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
API_KEY = os.environ.get("GOOGLE_AI_API_KEY")

print(f"Checking models for:")
print(f"  Project: {PROJECT_ID}")
print(f"  Location: {LOCATION}")
print(f"  Auth: Vertex AI (Service Account)")

try:
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    
    print("\nListing available models:")
    for model in client.models.list(config={"page_size": 200}):
        if "veo" in model.name.lower():
            print(f"  - {model.name} (Display: {model.display_name})")
            
except Exception as e:
    print(f"\nERROR listing Vertex AI models: {e}")

print("\n--------------------------------------------------")
print("Now checking with standard Gemini API (API Key mode):")
try:
    client_api = genai.Client(api_key=API_KEY)
    for model in client_api.models.list():
        if "veo" in model.name.lower():
            print(f"  - {model.name} (Display: {model.display_name})")

except Exception as e:
    print(f"\nERROR listing API Key models: {e}")
