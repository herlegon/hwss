#!/usr/bin/env python3
"""
Simple test to verify CLIENT_* messages behavior
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from logger import slog, set_debug_mode

print("=" * 60)
print("Testing CLIENT_* message visibility")
print("=" * 60)

print("\n=== Test 1: Debug mode DISABLED ===")
set_debug_mode(False)
slog.client_debug("CLIENT_DEBUG message (should NOT appear in console)")
slog.client_info("CLIENT_INFO message (should NOT appear in console)")
slog.client_warning("CLIENT_WARNING message (should NOT appear in console)")
slog.info("Regular INFO message (should appear in console)")
slog.warning("Regular WARNING message (should appear in console)")

print("\n=== Test 2: Debug mode ENABLED ===")
set_debug_mode(True)
slog.client_debug("CLIENT_DEBUG message (should appear in console)")
slog.client_info("CLIENT_INFO message (should appear in console)")
slog.client_warning("CLIENT_WARNING message (should appear in console)")
slog.debug("Regular DEBUG message (should appear in console)")
slog.info("Regular INFO message (should appear in console)")

print("\n=== Test 3: Debug mode DISABLED again ===")
set_debug_mode(False)
slog.client_info("CLIENT_INFO message (should NOT appear in console)")
slog.info("Regular INFO message (should appear in console)")

print("\n" + "=" * 60)
print("Test complete!")
print("=" * 60)
