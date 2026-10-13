"""Sent by the host for each operation. Runs only inside a Render sandbox."""

import base64
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/workspace")
MAX_BYTES = 16_384


def write_file(name, content):
    # Refuse final-component symlinks. The surrounding VM remains the isolation boundary.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    with os.fdopen(os.open(ROOT / name, flags, 0o600), "w") as f:
        f.write(content)


def run_tests(names, seconds=12):
    # Tests can import generated code. Never give this child the host's environment.
    script = (
        'import sys, unittest; sys.path.insert(0,"/workspace"); '
        "suite=unittest.TestSuite(); "
        f"[suite.addTests(unittest.defaultTestLoader.loadTestsFromName(n)) for n in {names!r}]; "
        "result=unittest.TextTestRunner(verbosity=2).run(suite); "
        "sys.exit(not result.wasSuccessful())"
    )
    p = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", script],
        cwd=ROOT,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    output = {"stdout": bytearray(), "stderr": bytearray()}
    sel = selectors.DefaultSelector()
    sel.register(p.stdout, selectors.EVENT_READ, "stdout")
    sel.register(p.stderr, selectors.EVENT_READ, "stderr")
    deadline = time.monotonic() + seconds
    limited = None
    try:
        while sel.get_map():
            if time.monotonic() >= deadline:
                limited = "timeout"
                break
            for key, _ in sel.select(timeout=min(0.1, max(0, deadline - time.monotonic()))):
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    sel.unregister(key.fileobj)
                    continue
                room = MAX_BYTES - sum(map(len, output.values()))
                output[key.data].extend(chunk[:room])
                if len(chunk) > room:
                    limited = "output_limit"
                    break
            if limited:
                break
        if not limited:
            try:
                p.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                limited = "timeout"
    finally:
        # Also stop children if the test process exited while leaving pipes open.
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.wait(timeout=2)
        sel.close()
        p.stdout.close()
        p.stderr.close()
    return {
        **{k: bytes(v).decode("utf-8", errors="replace") for k, v in output.items()},
        "exit_code": 124 if limited == "timeout" else 125 if limited else p.returncode,
        "limit": limited,
    }


def main(payload):
    ROOT.mkdir(exist_ok=True)
    op = payload["op"]
    if op == "environment":
        return {
            "credentials_absent": not any(
                os.environ.get(k) for k in ["RENDER_API_KEY", "OPENROUTER_API_KEY"]
            )
        }
    if op == "setup":
        # Only the controlling application calls setup; the model cannot supply file maps.
        for name, text in payload["files"].items():
            if "/" in name or name in {".", ".."}:
                raise ValueError("Invalid setup filename")
            write_file(name, text)
        return {"written": list(payload["files"])}
    if op == "read":
        name = payload["path"]
        if name not in {"totals.py", "test_totals.py", "test_followup.py", "restore-marker.txt"}:
            raise ValueError("File not readable")
        with os.fdopen(os.open(ROOT / name, os.O_RDONLY | os.O_NOFOLLOW), "rb") as f:
            content = f.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError("File too large")
        return {"content": content.decode("utf-8")}
    if op == "write":
        if payload["path"] != "totals.py" or len(payload["content"].encode()) > MAX_BYTES:
            raise ValueError("Only totals.py may be edited, within the byte limit")
        write_file("totals.py", payload["content"])
        return {"written": "totals.py"}
    if op == "tests":
        allowed = {
            "test_totals",
            "test_followup",
            "test_acceptance",
            "test_shipping_acceptance",
            "test_probe",
        }
        if not payload["names"] or not set(payload["names"]) <= allowed:
            raise ValueError("Unknown test suite")
        return run_tests(payload["names"])
    raise ValueError("Unknown operation")


if __name__ == "__main__":
    try:
        result = main(json.loads(base64.b64decode(sys.argv[1])))
        print(json.dumps(result))
    except Exception as exc:
        # Do not expose filesystem contents or credentials through diagnostic exceptions.
        print(json.dumps({"error": type(exc).__name__}))
        sys.exit(1)
