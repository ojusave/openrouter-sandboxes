"""OpenRouter chooses file actions. The host executes them in Render Sandboxes."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import shlex
import signal
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from render import RenderAsync
from render.experimental.sandbox.types import SandboxExecExit, SandboxExecOutput

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
CONTRACT = json.loads((SHARED / "contract.json").read_text())
REMOTE = base64.b64encode((SHARED / "remote.py").read_bytes()).decode()


class IntegrationError(RuntimeError):
    """A safe application-authored diagnostic, without provider response bodies."""


def validate_tool(name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object")
    if (
        name == "read_file"
        and set(arguments) == {"path"}
        and arguments["path"] in ("totals.py", "test_totals.py", "test_followup.py")
    ):
        return {"op": "read", **arguments}
    if (
        name == "write_file"
        and set(arguments) == {"path", "content"}
        and arguments["path"] == "totals.py"
        and isinstance(arguments["content"], str)
        and len(arguments["content"].encode()) <= CONTRACT["max_file_bytes"]
    ):
        return {"op": "write", **arguments}
    if name == "run_tests" and not arguments:
        return {"op": "tests"}
    raise ValueError("Unsupported action, path, arguments, or file size")


class Run:
    def __init__(self, api, output: Path, model: str):
        self.api = api
        self.output = output
        self.output.mkdir(parents=True, exist_ok=False)
        self.state = {
            "language": "python",
            "started_at": datetime.now(UTC).isoformat(),
            "model": model,
            "sandboxes": [],
            "snapshots": [],
            "checks": {},
            "calls": [],
            "complete": False,
        }
        self.save()

    def save(self):
        target = self.output / "run.json"
        temp = self.output / "run.json.tmp"
        temp.write_text(json.dumps(self.state, indent=2) + "\n")
        temp.replace(target)

    def check(self, name, result):
        self.state["checks"][name] = result
        self.save()
        print(name + ": " + json.dumps(result), flush=True)
        if result is False:
            raise IntegrationError("Check failed: " + name)

    async def create(self, snapshot=None):
        # Do not retry a create with an unknown outcome. The journal records the attempt.
        self.state["pending_create"] = datetime.now(UTC).isoformat()
        self.save()
        async with asyncio.timeout(45):
            s = await self.api.create(
                plan="starter", timeout_seconds=600, network_policy="deny-all", snapshot_id=snapshot
            )
        self.state["sandboxes"].append({"id": s.id, "terminated": False})
        self.state.pop("pending_create", None)
        self.save()
        for _ in range(45):
            s = await asyncio.wait_for(self.api.from_id(s.id), 20)
            if s.status == "running":
                if s.network_policy != "deny-all":
                    raise IntegrationError("Effective network policy differs from deny-all")
                return s.id
            if s.status not in ("creating", "pending"):
                raise IntegrationError("Sandbox failed during startup")
            await asyncio.sleep(2)
        raise TimeoutError("Sandbox readiness deadline exceeded")

    async def rpc(self, sid, payload):
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        command = shlex.join(
            ["python3", "-I", "-c", f"import base64;exec(base64.b64decode({REMOTE!r}))", encoded]
        )
        output = bytearray()
        code = None
        async with asyncio.timeout(30):
            async for event in self.api.exec(sid, command):
                if isinstance(event, SandboxExecOutput):
                    data = event.data.encode()
                    if len(output) + len(data) > 131072:
                        raise IntegrationError("Remote response exceeded host output limit")
                    output.extend(data)
                elif isinstance(event, SandboxExecExit):
                    code = event.exit_code
        if code is None:
            raise IntegrationError("Command stream ended without an exit code")
        if code:
            raise IntegrationError("Sandbox helper failed")
        return json.loads(output)

    async def setup(self, sid, files):
        await self.rpc(sid, {"op": "setup", "files": files})

    async def terminate(self, record):
        if record["terminated"]:
            return
        last = None
        for attempt in range(3):
            try:
                await asyncio.wait_for(self.api.terminate(record["id"]), 20)
            except Exception as exc:
                last = type(exc).__name__
            cursor = None
            for _ in range(100):
                page = await asyncio.wait_for(self.api.list(limit=100, cursor=cursor), 20)
                found = next((s for s in page.sandboxes if s.id == record["id"]), None)
                if found and (found.status == "terminated" or found.terminated_at is not None):
                    record["terminated"] = True
                    record["final_status"] = found.status
                    self.save()
                    return
                if not page.sandboxes or not page.next_cursor:
                    break
                if page.next_cursor == cursor:
                    raise IntegrationError("Sandbox pagination did not advance")
                cursor = page.next_cursor
            await asyncio.sleep(2 * (attempt + 1))
        raise IntegrationError(
            f"Cleanup unconfirmed for {record['id']} ({last or 'state pending'})"
        )

    async def snapshot(self, sid):
        name = "openrouter-" + self.output.name
        self.state["pending_snapshot"] = {"source": sid, "name": name}
        self.save()
        snap = await asyncio.wait_for(
            self.api.snapshots.create(
                sid, kind="filesystem", name=name, expires_at=datetime.now(UTC) + timedelta(hours=1)
            ),
            45,
        )
        record = {"id": snap.id, "group": snap.sandbox_group_id, "deleted": False}
        self.state["snapshots"].append(record)
        self.state.pop("pending_snapshot", None)
        self.save()
        await self.wait_snapshot(record)
        return snap.id

    async def wait_snapshot(self, record):
        for _ in range(45):
            snap = await asyncio.wait_for(
                self.api.snapshots.from_id(
                    sandbox_group_id=record["group"], snapshot_id=record["id"]
                ),
                20,
            )
            if snap.status != "creating":
                if snap.status == "failed":
                    raise IntegrationError("Snapshot capture failed")
                return
            await asyncio.sleep(2)
        raise TimeoutError("Snapshot readiness deadline exceeded")

    async def cleanup(self):
        errors = []
        for record in self.state["sandboxes"]:
            try:
                await self.terminate(record)
            except Exception as exc:
                errors.append(f"{record['id']}: {type(exc).__name__}")
        for record in self.state["snapshots"]:
            if record["deleted"]:
                continue
            try:
                # Delete first so recovery also handles an already-deleted snapshot.
                try:
                    await asyncio.wait_for(
                        self.api.snapshots.delete(
                            sandbox_group_id=record["group"], snapshot_id=record["id"]
                        ),
                        20,
                    )
                except Exception:
                    try:
                        await self.wait_snapshot(record)
                    except RuntimeError as exc:
                        if str(exc) != "Snapshot capture failed":
                            raise
                    await asyncio.wait_for(
                        self.api.snapshots.delete(
                            sandbox_group_id=record["group"], snapshot_id=record["id"]
                        ),
                        20,
                    )
                cursor = None
                for _ in range(100):
                    page = await asyncio.wait_for(
                        self.api.snapshots.list(
                            sandbox_group_id=record["group"], limit=100, cursor=cursor
                        ),
                        20,
                    )
                    if any(s.id == record["id"] for s in page.snapshots):
                        raise IntegrationError("Deleted snapshot remains listed")
                    if not page.snapshots or not page.next_cursor:
                        record["deleted"] = True
                        break
                    if page.next_cursor == cursor:
                        raise IntegrationError("Snapshot pagination did not advance")
                    cursor = page.next_cursor
                if not record["deleted"]:
                    raise IntegrationError("Snapshot pagination budget exceeded")
                self.save()
            except Exception as exc:
                errors.append(f"{record['id']}: {type(exc).__name__}")
        if self.state.get("pending_create") or self.state.get("pending_snapshot"):
            errors.append("Unknown creation outcome: inspect provider resources before retrying")
        self.state["cleanup_errors"] = errors
        self.state["cleanup_verified"] = not errors
        self.save()
        if errors:
            raise IntegrationError("Cleanup remains unconfirmed; inspect run.json")

    async def agent(self, sid, followup=False):
        messages = [
            {"role": "system", "content": CONTRACT["system"]},
            {"role": "user", "content": CONTRACT["followup" if followup else "initial"]},
        ]
        count = 0
        async with httpx.AsyncClient(timeout=60) as client:
            for _ in range(CONTRACT["max_turns"]):
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"],
                        "X-OpenRouter-Title": "Render Sandbox repair example",
                    },
                    json={
                        "model": self.state["model"],
                        "messages": messages,
                        "tools": CONTRACT["tools"],
                        "max_tokens": 2048,
                        "provider": {"require_parameters": True},
                    },
                )
                if response.status_code != 200:
                    raise IntegrationError(f"OpenRouter returned HTTP {response.status_code}")
                body = response.json()
                if body.get("error") or not body.get("choices"):
                    raise IntegrationError("OpenRouter did not return a completion")
                choice = body["choices"][0]
                message = choice["message"]
                self.state["calls"].append(
                    {
                        "model": body.get("model"),
                        "id": body.get("id"),
                        "usage": body.get("usage"),
                        "followup": followup,
                    }
                )
                self.save()
                # Preserve reasoning_details when a provider requires them on subsequent calls.
                messages.append(message)
                calls = message.get("tool_calls", [])
                if not calls:
                    if choice.get("finish_reason") != "stop":
                        raise IntegrationError("Model stopped before completing its turn")
                    return
                for call in calls:
                    count += 1
                    if count > CONTRACT["max_tool_calls"]:
                        raise IntegrationError("Tool call budget exceeded")
                    try:
                        payload = validate_tool(
                            call["function"]["name"], json.loads(call["function"]["arguments"])
                        )
                    except (ValueError, TypeError, KeyError):
                        result = {
                            "error": "Invalid tool request. Use only the listed actions and files."
                        }
                    else:
                        if payload["op"] == "tests":
                            payload["names"] = ["test_totals"] + (
                                ["test_followup"] if followup else []
                            )
                        result = await self.rpc(sid, payload)
                    messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)}
                    )
                    self.state.setdefault("tool_events", []).append(
                        {
                            "name": call["function"]["name"],
                            "followup": followup,
                            "exit_code": result.get("exit_code"),
                            "error": result.get("error"),
                        }
                    )
                    self.save()
            raise IntegrationError("Model turn budget exceeded")

    async def verify(self, source, followup=False):
        # A clean sandbox contains only the downloaded source and host-owned test originals.
        sid = await self.create()
        names = ["test_totals", "test_acceptance"] + (
            ["test_followup", "test_shipping_acceptance"] if followup else []
        )
        await self.setup(
            sid,
            {"totals.py": source, **{n + ".py": (SHARED / (n + ".py")).read_text() for n in names}},
        )
        result = await self.rpc(sid, {"op": "tests", "names": names})
        self.state["checks"]["followup_verification" if followup else "repair_verification"] = (
            result
        )
        self.save()
        if result["exit_code"] != 0:
            raise IntegrationError("Independent tests failed")
        await self.terminate(next(r for r in self.state["sandboxes"] if r["id"] == sid))

    async def demo(self):
        sid = await self.create()
        marker = str(uuid.uuid4())
        await self.setup(
            sid,
            {name: (SHARED / name).read_text() for name in ["totals.py", "test_totals.py"]}
            | {"restore-marker.txt": marker},
        )
        baseline = await self.rpc(sid, {"op": "tests", "names": ["test_totals"]})
        self.check(
            "initial_tests_fail",
            baseline["exit_code"] != 0 and "AssertionError: 125 != 375" in baseline["stderr"],
        )
        await self.agent(sid)
        source = (await self.rpc(sid, {"op": "read", "path": "totals.py"}))["content"]
        (self.output / "repaired.py").write_text(source)
        await self.verify(source)
        self.check("repair_passed_independent_tests", True)
        snap = await self.snapshot(sid)
        await self.terminate(next(r for r in self.state["sandboxes"] if r["id"] == sid))
        restored = await self.create(snap)
        saved = (await self.rpc(restored, {"op": "read", "path": "totals.py"}))["content"]
        saved_marker = (await self.rpc(restored, {"op": "read", "path": "restore-marker.txt"}))[
            "content"
        ]
        self.check(
            "restored_files_match", saved == source and saved_marker == marker and restored != sid
        )
        await self.setup(restored, {"test_followup.py": (SHARED / "test_followup.py").read_text()})
        await self.agent(restored, True)
        final = (await self.rpc(restored, {"op": "read", "path": "totals.py"}))["content"]
        (self.output / "totals.py").write_text(final)
        await self.verify(final, True)
        self.check("followup_passed_independent_tests", True)
        self.state["source_sha256"] = hashlib.sha256(final.encode()).hexdigest()

    async def boundaries(self):
        async with httpx.AsyncClient(timeout=10) as client:
            control = await client.get("https://example.com")
            self.check("network_host_control", control.status_code == 200)
        sid = await self.create()
        self.check(
            "sandbox_credentials_absent",
            (await self.rpc(sid, {"op": "environment"}))["credentials_absent"],
        )
        probes = {
            "exception_is_failure": (
                'raise IntegrationError("intentional")',
                lambda r: r["exit_code"] != 0 and r["limit"] is None,
            ),
            "timeout_enforced": (
                "import time; time.sleep(60)",
                lambda r: r["exit_code"] == 124 and r["limit"] == "timeout",
            ),
            "output_bounded": (
                'print("x"*100000)',
                lambda r: (
                    r["exit_code"] == 125
                    and sum(len(r[k].encode()) for k in ["stdout", "stderr"]) <= 16384
                ),
            ),
            "credentials_absent": (
                'import os; assert not any(os.environ.get(k) for k in ["RENDER_API_KEY","OPENROUTER_API_KEY"])',
                lambda r: r["exit_code"] == 0,
            ),
            "network_request_blocked_or_timed_out": (
                'import urllib.request\nprint("network_attempt_started",flush=True)\ntry:\n urllib.request.urlopen("https://example.com",timeout=3)\nexcept urllib.error.HTTPError:\n raise\nexcept (urllib.error.URLError, TimeoutError):\n print("network_blocked",flush=True)\nelse:\n raise AssertionError("network reached")',
                lambda r: (
                    (r["exit_code"] == 0 and "network_blocked" in r["stdout"])
                    or (r["exit_code"] == 124 and "network_attempt_started" in r["stdout"])
                ),
            ),
        }
        for name, (code, accept) in probes.items():
            await self.setup(sid, {"test_probe.py": code})
            result = await self.rpc(sid, {"op": "tests", "names": ["test_probe"]})
            self.state.setdefault("boundary_results", {})[name] = result
            self.save()
            self.check(name, accept(result))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["demo", "boundaries", "fail-after-create", "fail-after-snapshot", "cleanup"],
        nargs="?",
        default="demo",
    )
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    for key in ["RENDER_API_KEY", "RENDER_WORKSPACE_ID"] + (
        ["OPENROUTER_API_KEY"] if args.mode == "demo" else []
    ):
        if not os.environ.get(key):
            raise ValueError("Missing " + key)
    if os.environ.get("RENDER_USE_LOCAL_DEV") or os.environ.get("RENDER_LOCAL_DEV_URL"):
        raise ValueError("Unset Render local development overrides for this cloud example")
    api = RenderAsync().experimental.sandboxes
    if args.mode == "cleanup":
        if not args.run_dir:
            raise ValueError("cleanup requires --run-dir")
        run = object.__new__(Run)
        run.api, run.output = api, args.run_dir.resolve()
        run.state = json.loads((run.output / "run.json").read_text())
        if run.state.get("workspace") != os.environ["RENDER_WORKSPACE_ID"]:
            raise ValueError("Cleanup workspace does not match run.json")
        await run.cleanup()
        return
    output = args.run_dir or ROOT / ".runs" / ("python-" + uuid.uuid4().hex[:12])
    run = Run(api, output, os.getenv("OPENROUTER_MODEL", CONTRACT["model"]))
    run.state["workspace"] = os.environ["RENDER_WORKSPACE_ID"]
    run.save()
    print("Run journal: " + str(output / "run.json"), flush=True)
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(sig, task.cancel)
    try:
        async with asyncio.timeout(480):
            if args.mode == "demo":
                await run.demo()
            elif args.mode == "boundaries":
                await run.boundaries()
            else:
                sid = await run.create()
                if args.mode == "fail-after-snapshot":
                    await run.snapshot(sid)
                raise IntegrationError("Intentional failure for cleanup verification")
        run.state["complete"] = True
    except BaseException as exc:
        run.state["failure_type"] = type(exc).__name__
        if isinstance(exc, IntegrationError):
            run.state["failure_reason"] = str(exc)
        run.save()
        raise
    finally:
        for sig in [signal.SIGINT, signal.SIGTERM]:
            loop.remove_signal_handler(sig)
        await asyncio.shield(run.cleanup())
        print("cleanup_verified: " + str(run.state["cleanup_verified"]), flush=True)
        print("Evidence: " + str(output / "run.json"), flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (Exception, asyncio.CancelledError, KeyboardInterrupt) as exc:
        print(
            "Run stopped: "
            + (str(exc) if isinstance(exc, IntegrationError) else type(exc).__name__)
            + ". See run.json for cleanup state.",
            file=sys.stderr,
        )
        sys.exit(1)
