import asyncio
import time
import unittest

from modelhub_tools.tool_manager import CircuitState, MCPToolManager, Tool


class ToolManagerSecurityTests(unittest.IsolatedAsyncioTestCase):

    async def test_cache_is_scoped_by_context_without_exposing_secret(self):
        manager = MCPToolManager.__new__(MCPToolManager)
        manager._cache = {}

        async def handler(params, context):
            return {"owner": context["auth_token"]}

        tool = Tool(
            name="private_read",
            description="test",
            handler=handler,
            schema={"type": "object", "properties": {}, "required": []},
            cache_ttl=60,
            cache_context_keys=("auth_token",),
        )
        manager._tools = {tool.name: tool}

        alice = await manager.call(tool.name, {}, {"auth_token": "alice-secret"})
        bob = await manager.call(tool.name, {}, {"auth_token": "bob-secret"})
        alice_again = await manager.call(tool.name, {}, {"auth_token": "alice-secret"})

        self.assertEqual({"owner": "alice-secret"}, alice.data)
        self.assertEqual({"owner": "bob-secret"}, bob.data)
        self.assertTrue(alice_again.cached)
        for key in manager._cache:
            self.assertNotIn("alice-secret", key)
            self.assertNotIn("bob-secret", key)

    async def test_async_fallback_is_awaited(self):
        manager = MCPToolManager.__new__(MCPToolManager)

        async def fallback(params, context, error):
            return {"fallback": True, "error": error}

        tool = Tool(
            name="fallback_test",
            description="test",
            handler=lambda params, context: None,
            schema={"type": "object", "properties": {}, "required": []},
            fallback=fallback,
        )

        result = await manager._fallback_result(tool, {}, None, "offline")

        self.assertEqual({"fallback": True, "error": "offline"}, result.data)

    async def test_backend_business_failure_is_not_cached_and_opens_breaker(self):
        manager = MCPToolManager.__new__(MCPToolManager)
        manager._cache = {}
        manager._aliases = {}
        calls = 0

        async def handler(params, context):
            nonlocal calls
            calls += 1
            return {"success": False, "error": "business failure"}

        tool = Tool(
            name="business_read",
            description="test",
            handler=handler,
            schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            cache_ttl=60,
        )
        tool.breaker.threshold = 2
        manager._tools = {tool.name: tool}

        first = await manager.call(tool.name, {})
        second = await manager.call(tool.name, {})
        blocked = await manager.call(tool.name, {})

        self.assertFalse(first.success)
        self.assertFalse(second.success)
        self.assertFalse(blocked.success)
        self.assertEqual(2, calls)
        self.assertEqual({}, manager._cache)
        self.assertEqual(0, tool.stats.success)
        self.assertEqual(2, tool.stats.failed)
        self.assertEqual(2, tool.stats.consecutive_fails)
        self.assertEqual(CircuitState.OPEN, tool.breaker.state)

    async def test_invalid_params_do_not_affect_stats_or_breaker(self):
        manager = MCPToolManager.__new__(MCPToolManager)
        manager._cache = {}
        manager._aliases = {}

        async def handler(params, context):
            raise AssertionError("invalid input must not reach handler")

        tool = Tool(
            name="validated_read",
            description="test",
            handler=handler,
            schema={
                "type": "object",
                "properties": {"model_id": {"type": "integer", "minimum": 1}},
                "required": ["model_id"],
                "additionalProperties": False,
            },
        )
        tool.breaker.threshold = 1
        manager._tools = {tool.name: tool}

        for _ in range(3):
            result = await manager.call(tool.name, {"model_id": "bad"})
            self.assertFalse(result.success)

        self.assertEqual(0, tool.stats.total)
        self.assertEqual(0, tool.stats.failed)
        self.assertEqual(0, tool.breaker.fail_count)
        self.assertEqual(CircuitState.CLOSED, tool.breaker.state)

    async def test_closed_call_cancellation_does_not_count_as_backend_failure(self):
        manager = MCPToolManager.__new__(MCPToolManager)
        manager._cache = {}
        manager._aliases = {}
        started = asyncio.Event()

        async def handler(params, context):
            started.set()
            await asyncio.Event().wait()

        tool = Tool(
            name="cancelled_read",
            description="test",
            handler=handler,
            schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        )
        manager._tools = {tool.name: tool}

        task = asyncio.create_task(manager.call(tool.name, {}))
        await asyncio.wait_for(started.wait(), timeout=0.5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(CircuitState.CLOSED, tool.breaker.state)
        self.assertEqual(0, tool.breaker.fail_count)
        self.assertFalse(tool.breaker.probe_in_flight)
        self.assertEqual(0, tool.stats.failed)
        self.assertEqual(0, tool.stats.consecutive_fails)

    async def test_half_open_allows_one_probe_and_cancellation_reopens(self):
        manager = MCPToolManager.__new__(MCPToolManager)
        manager._cache = {}
        manager._aliases = {}
        started = asyncio.Event()
        calls = 0

        async def handler(params, context):
            nonlocal calls
            calls += 1
            started.set()
            await asyncio.Event().wait()

        tool = Tool(
            name="probe_read",
            description="test",
            handler=handler,
            schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        )
        tool.breaker.state = CircuitState.OPEN
        tool.breaker.fail_count = tool.breaker.threshold
        tool.breaker.opened_at = time.monotonic() - tool.breaker.recovery_s - 1
        manager._tools = {tool.name: tool}

        probe = asyncio.create_task(manager.call(tool.name, {}))
        await asyncio.wait_for(started.wait(), timeout=0.5)
        rejected = await manager.call(tool.name, {})
        self.assertFalse(rejected.success)
        self.assertEqual(1, calls)

        probe.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await probe

        self.assertEqual(CircuitState.OPEN, tool.breaker.state)
        self.assertFalse(tool.breaker.probe_in_flight)
        self.assertEqual(tool.breaker.threshold, tool.breaker.fail_count)
        self.assertFalse(tool.breaker.allow())


if __name__ == "__main__":
    unittest.main()
