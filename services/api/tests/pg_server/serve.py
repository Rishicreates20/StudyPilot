"""Start a throwaway PostgreSQL and keep it running until stdin closes.

Prints ``URI <connection string>`` once the server accepts connections. The server and its data
directory are removed when stdin closes (the test run finished or crashed), so nothing is left
behind.
"""

import sys
import tempfile

import pgserver

with tempfile.TemporaryDirectory(prefix="studypilot-pg-", ignore_cleanup_errors=True) as data_dir:
    server = pgserver.get_server(data_dir, cleanup_mode="stop")
    try:
        print(f"URI {server.get_uri()}", flush=True)
        sys.stdin.read()  # blocks until the parent closes the pipe
    finally:
        server.cleanup()
