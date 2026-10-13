"""Failure-focused checks, independent of paid services."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("client", ROOT / "python/main.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class ContractTests(unittest.TestCase):
    def test_rejects_paths_and_extra_arguments(self):
        for name, args in [
            ("write_file", {"path": "../totals.py", "content": ""}),
            ("write_file", {"path": "test_totals.py", "content": ""}),
            ("read_file", {"path": "/etc/passwd"}),
            ("read_file", {"path": ["totals.py"]}),
            ("run_tests", {"command": "anything"}),
            ("shell", {"command": "anything"}),
            ("run_tests", []),
        ]:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                client.validate_tool(name, args)

    def test_byte_limit_includes_multibyte_text(self):
        with self.assertRaises(ValueError):
            client.validate_tool("write_file", {"path": "totals.py", "content": "€" * 6000})
        self.assertEqual(
            client.validate_tool("write_file", {"path": "totals.py", "content": "x" * 16384})["op"],
            "write",
        )


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        (ROOT / ".runs").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / ".runs")
        self.api = NS(
            terminate=AsyncMock(),
            list=AsyncMock(),
            snapshots=NS(delete=AsyncMock(), list=AsyncMock()),
        )
        self.run = client.Run(self.api, Path(self.tmp.name) / "run", "test-model")

    def tearDown(self):
        self.tmp.cleanup()

    async def test_termination_follows_pagination(self):
        self.api.list.side_effect = [
            NS(sandboxes=[NS(id="unrelated")], next_cursor="p2"),
            NS(
                sandboxes=[NS(id="sbx-owned", status="errored", terminated_at="now")],
                next_cursor=None,
            ),
        ]
        r = {"id": "sbx-owned", "terminated": False}
        await self.run.terminate(r)
        self.assertTrue(r["terminated"])
        self.assertEqual(self.api.list.call_args.kwargs["cursor"], "p2")
        self.api.terminate.assert_awaited_once_with("sbx-owned")

    async def test_cleanup_continues_after_one_failure_and_does_not_claim_success(self):
        self.run.state["sandboxes"] = [{"id": x, "terminated": False} for x in ["first", "second"]]
        self.run.terminate = AsyncMock(side_effect=[RuntimeError("failure"), None])
        with self.assertRaises(RuntimeError):
            await self.run.cleanup()
        self.assertEqual(self.run.terminate.await_count, 2)
        self.assertFalse(self.run.state["cleanup_verified"])

    async def test_snapshot_cleanup_is_retryable_after_deletion(self):
        self.run.state["snapshots"] = [{"id": "snp-owned", "group": "sbg-owned", "deleted": False}]
        self.api.snapshots.list.return_value = NS(snapshots=[], next_cursor=None)
        await self.run.cleanup()
        self.assertTrue(self.run.state["snapshots"][0]["deleted"])
        self.assertTrue(self.run.state["cleanup_verified"])

    async def test_unknown_create_cannot_be_reported_clean(self):
        self.run.state["pending_create"] = "known-start-time"
        with self.assertRaises(RuntimeError):
            await self.run.cleanup()
        self.assertFalse(self.run.state["cleanup_verified"])

    async def test_missing_exit_is_not_success(self):
        async def events(*args):
            yield client.SandboxExecOutput("stdout", "{}")

        self.api.exec = events
        with self.assertRaisesRegex(RuntimeError, "without an exit"):
            await self.run.rpc("sbx-owned", {"op": "environment"})

    async def test_stream_output_is_bounded(self):
        async def events(*args):
            yield client.SandboxExecOutput("stdout", "x" * 131073)

        self.api.exec = events
        with self.assertRaisesRegex(RuntimeError, "output limit"):
            await self.run.rpc("sbx-owned", {"op": "environment"})

    async def test_model_success_cannot_bypass_independent_tests(self):
        self.run.create = AsyncMock(return_value="sbx-verifier")
        self.run.setup = AsyncMock()
        self.run.rpc = AsyncMock(return_value={"exit_code": 1})
        with self.assertRaisesRegex(RuntimeError, "Independent tests failed"):
            await self.run.verify("broken source")
        files = self.run.setup.call_args.args[1]
        self.assertEqual(files["test_totals.py"], (ROOT / "shared/test_totals.py").read_text())
        self.assertIn("test_acceptance.py", files)


if __name__ == "__main__":
    unittest.main()
