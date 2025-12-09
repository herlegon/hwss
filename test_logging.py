#!/usr/bin/env python3
"""
Test script to verify the logging system works correctly.
Tests both client-level and standard logging with and without debug mode.
"""

import multiprocessing as mp
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from logger import slog, set_debug_mode, set_client_queue
from api import EventMessage


def test_worker_logging(result_queue: mp.Queue):
    """Simulate a worker process using the logging system"""
    # Set up the client queue in the worker process
    set_client_queue(result_queue)
    
    print("\n=== Worker Process Testing ===")
    
    # Test client-level messages (should go to both queue and stdout)
    slog.client_info("This is a client info message")
    slog.client_warning("This is a client warning message")
    slog.client_error("This is a client error message")
    slog.client_critical("This is a client critical message")
    
    # Test standard messages (should only go to stdout)
    slog.debug("This is a debug message (only visible with --debug)")
    slog.info("This is a standard info message (stdout only)")
    slog.warning("This is a standard warning message (stdout only)")
    slog.error("This is a standard error message (stdout only)")
    slog.critical("This is a standard critical message (stdout only)")
    
    # Signal completion
    result_queue.put("DONE")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Test the logging system")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()
    
    # Configure debug mode
    set_debug_mode(args.debug)
    
    print("=" * 60)
    print("LOGGING SYSTEM TEST")
    print("=" * 60)
    print(f"Debug mode: {'ENABLED' if args.debug else 'DISABLED'}")
    print("=" * 60)
    
    # Test main process logging
    print("\n=== Main Process Testing ===")
    slog.debug("Main process debug message (only visible with --debug)")
    slog.info("Main process info message")
    slog.warning("Main process warning message")
    slog.error("Main process error message")
    slog.critical("Main process critical message")
    
    # Test worker process with queue
    result_queue = mp.Queue()
    worker = mp.Process(target=test_worker_logging, args=(result_queue,))
    worker.start()
    
    # Collect messages from the queue
    print("\n=== Messages Received from Worker Queue ===")
    messages_received = []
    timeout = time.time() + 5  # 5 second timeout
    
    while time.time() < timeout:
        try:
            msg = result_queue.get(timeout=0.5)
            if msg == "DONE":
                break
            messages_received.append(msg)
            
            if isinstance(msg, EventMessage):
                print(f"[Queue] {msg.type}: {msg.payload}")
            else:
                print(f"[Queue] {msg}")
                
        except Exception:
            continue
    
    worker.join(timeout=2)
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Worker process completed: {not worker.is_alive()}")
    print(f"Messages received from queue: {len(messages_received)}")
    print(f"Expected client messages: 4 (info, warning, error, critical)")
    
    if len(messages_received) == 4:
        print("✅ All client messages received correctly!")
    else:
        print(f"⚠️  Expected 4 messages, got {len(messages_received)}")
    
    print("\nNOTE: Debug messages are only visible when --debug flag is used")
    print("      Client messages appear in BOTH stdout and the queue")
    print("      Standard messages only appear in stdout")
    print("=" * 60)


if __name__ == "__main__":
    mp.set_start_method('spawn', force=True)
    main()
