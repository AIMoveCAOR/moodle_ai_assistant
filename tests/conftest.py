"""Shared pytest configuration for all tests."""

import sys
import os
from unittest.mock import MagicMock, patch
from pathlib import Path

# Pre-patch pydantic_settings.DotEnvSettingsSource before any imports
# This prevents the .env file permission error
original_open = open

def patched_open_for_env(*args, **kwargs):
    """Patch open() to block .env file reads."""
    if args:
        filepath = str(args[0])
        if filepath.endswith('.env'):
            # Return an empty file-like object for .env
            from io import StringIO
            return StringIO("")
    return original_open(*args, **kwargs)

# Monkey-patch dotenv before chromadb loads
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: None
dotenv.dotenv_values = lambda *args, **kwargs: {}

# Also block the actual file open for .env files
builtins = __import__('builtins')
builtins.open = patched_open_for_env



import pytest


@pytest.fixture(autouse=True)
def no_real_backoff_sleeps(monkeypatch):
    """Retry backoff must never cost the suite wall-clock time.

    translate_to_french backs off exponentially (5s, 10s, 20s...) and the
    course backfill passes max_retries=5, so one test simulating a failing
    provider sat there for 155 real seconds — it took the whole suite from 9
    seconds to over 3 minutes. Nothing under test depends on that time
    actually passing; the tests that care about backoff assert call counts.

    Scoped to translation_service rather than patching the time module
    outright, because SiloService's cache-expiry test does depend on real
    time moving.
    """
    from services import translation_service

    class _NoSleepClock:
        sleep = staticmethod(lambda seconds: None)
        time = staticmethod(__import__("time").time)

    monkeypatch.setattr(translation_service, "time", _NoSleepClock)
