import os
import sys
import threading
import time

from flask import Flask, jsonify

FAILURE_MODE = os.environ.get("FAILURE_MODE", "none")

if FAILURE_MODE == "missing_env":
    # Crash immediately at startup if DATABASE_URL isn't set -- simulates a
    # classic misconfiguration outage. Deliberately not caught.
    DATABASE_URL = os.environ["DATABASE_URL"]

app = Flask(__name__)


def _log(message: str) -> None:
    print(message, flush=True)


@app.get("/health")
def health():
    return jsonify(status="ok", failure_mode=FAILURE_MODE)


@app.get("/api")
def api():
    if FAILURE_MODE == "db_down":
        _log("ERROR: could not connect to database host 'db': Connection refused")
        return jsonify(error="database unreachable"), 500

    if FAILURE_MODE == "errors_500":
        try:
            1 / 0
        except ZeroDivisionError:
            _log(
                "ERROR: Traceback (most recent call last):\n"
                '  File "app.py", line 1, in api\n'
                "ZeroDivisionError: division by zero"
            )
            return jsonify(error="internal error"), 500

    if FAILURE_MODE == "slow":
        time.sleep(8)
        return jsonify(status="ok (slow)")

    if FAILURE_MODE == "high_cpu":
        end = time.time() + 3
        while time.time() < end:
            pass
        return jsonify(status="ok (busy)")

    return jsonify(status="ok")


def _crash_loop() -> None:
    time.sleep(5)
    _log("CRITICAL: simulated crash_loop failure -- exiting")
    os._exit(1)


def _memory_leak() -> None:
    hog = []
    while True:
        hog.append(b"x" * 10_000_000)  # ~10MB/s
        time.sleep(1)


if FAILURE_MODE == "crash_loop":
    threading.Thread(target=_crash_loop, daemon=True).start()

if FAILURE_MODE == "memory_leak":
    threading.Thread(target=_memory_leak, daemon=True).start()


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    app.run(host="0.0.0.0", port=5000)
