"""Runs before any test module imports the app: isolated storage, no API key (mock mode)."""
import os
import tempfile

os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="slidesmith-test-")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["SOFFICE_BIN"] = ""
