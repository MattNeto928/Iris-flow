# Iris Flow Serverless - Services Package
#
# Intentionally does NOT eagerly re-export the service classes. Every caller
# imports the submodule it needs directly (e.g.
# `from src.services.pysim_service import PysimService`), so eagerly importing
# all ~14 service modules here only added cold-start cost and coupled the live
# engines (matplotlib/manim/plotly) to optional/dead ones — importing PysimService
# would drag in tts_client (google.genai), veo_service (fal_client), etc. Keep this
# file thin so each engine pulls in only its own dependencies.
