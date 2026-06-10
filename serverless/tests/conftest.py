"""Shared pytest setup.

The service modules build a module-level anthropic.Anthropic() client at import
time, which requires *some* API key to be present (no network call is made).
Set a dummy key before any service module is imported.
"""
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
