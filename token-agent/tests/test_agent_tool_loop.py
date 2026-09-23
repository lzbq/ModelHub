import asyncio
import json
import unittest
from collections import deque
from copy import deepcopy

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from agents.tool_use import AgentToolLoop, ToolLoopError, ToolPolicy
from modelhub_tools.tool_manager import MCPToolManager, Tool


def message(*blocks, stop_reason="end_turn", seq=1):
    return Message(
        id=f"msg_{seq}",
        content=list(blocks),
        model="test-model",
        role="assistant",
        stop_reason=stop_reason,
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=10, output_tokens=5),
    )


class ScriptedMessages:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if not self.responses:
            raise AssertionError("LLM 被额外调用")
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses):
        self.messages = ScriptedMessages(responses)


class FakeApiError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


def manager_with_tool(handler, *, name="modelhub_search_models", schema=None):
    manager = MCPToolManager.__new__(MCPToolManager)
    manager._tools = {}
    manager._aliases = {}
    manager._cache = {}
    manager.register(Tool(
        name=name,
        description="test tool",
        handler=handler,
        schema=schema or {
            "type": "object",
            "properties": {"keyword": {"type": "string"}},
            "required": ["keyword"],
            "additionalProperties": False,
        },
    ))
    return manager


class AgentToolLoopTests(unittest.IsolatedAsyncioTestCase):

    async def test_auto_choice_can_finish_without_tool(self):
        calls = []

        async def handler(params, context):
            calls.append((params, context))
            return {"ok": True}

        manager = manager_with_tool(handler)
        client = FakeClient([message(TextBlock(text="直接回答", type="text"))])
        result = await AgentToolLoop(manager).run(
            client=client,
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "hello"}],
            policy=ToolPolicy(allowed_tools=("modelhub_search_models",)),
        )

        self.assertEqual("直接回答", result.content)
        self.assertEqual([], calls)
        self.assertEqual({"type": "auto"}, client.messages.calls[0]["tool_choice"])

    async def test_one_tool_round_trips_result_without_exposing_auth(self):
        calls = []

        async def handler(params, context):
            calls.append((deepcopy(params), deepcopy(context)))
            return {"models": ["safe-model"]}

        manager = manager_with_tool(handler, schema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "auth_token": {"type": "string"},
            },
            "required": ["keyword"],
        })
        client = FakeClient([
            message(ToolUseBlock(id="tool_1", input={"keyword": "ignored"}, name="modelhub_search_models", type="tool_use"), stop_reason="tool_use"),
            message(TextBlock(text="找到 safe-model", type="text"), seq=2),
        ])
        result = await AgentToolLoop(manager).run(
            client=client,
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "find"}],
            policy=ToolPolicy(
                allowed_tools=("modelhub_search_models",),
                first_choice="modelhub_search_models",
                locked_inputs={"modelhub_search_models": {"keyword": "claude"}},
            ),
            tool_context={"auth_token": "server-secret", "principal_id": "alice"},
        )

        self.assertEqual([({"keyword": "claude"}, {"auth_token": "server-secret", "principal_id": "alice"})], calls)
        self.assertEqual(["modelhub_search_models"], result.tools_used)
        self.assertNotIn("auth_token", client.messages.calls[0]["tools"][0]["input_schema"]["properties"])
        self.assertNotIn("server-secret", repr(client.messages.calls))
        second_messages = client.messages.calls[1]["messages"]
        self.assertEqual("tool_1", second_messages[-1]["content"][0]["tool_use_id"])
        self.assertFalse(second_messages[-1]["content"][0]["is_error"])
        self.assertEqual("auto", client.messages.calls[1]["tool_choice"]["type"])

    async def test_unauthorized_tool_is_never_executed(self):
        calls = []

        async def handler(params, context):
            calls.append(params)
            return {}

        manager = manager_with_tool(handler)
        client = FakeClient([
            message(ToolUseBlock(id="private_1", input={"order_id": 9}, name="token_order", type="tool_use"), stop_reason="tool_use"),
            message(TextBlock(text="无法执行私有查询", type="text"), seq=2),
        ])
        result = await AgentToolLoop(manager).run(
            client=client,
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "order"}],
            policy=ToolPolicy(allowed_tools=("modelhub_search_models",)),
        )

        self.assertEqual([], calls)
        self.assertEqual([], result.tools_used)
        self.assertEqual("denied", result.records[0].status)
        returned = client.messages.calls[1]["messages"][-1]["content"][0]
        self.assertTrue(returned["is_error"])
        self.assertIn("tool_not_allowed", returned["content"])

    async def test_duplicate_signature_executes_once(self):
        calls = []

        async def handler(params, context):
            calls.append(params)
            return {"ok": True}

        manager = manager_with_tool(handler, schema={
            "type": "object",
            "properties": {"keyword": {"type": "string"}, "current": {"type": "integer"}},
            "required": ["keyword"],
            "additionalProperties": False,
        })
        client = FakeClient([
            message(ToolUseBlock(id="one", input={"keyword": "x", "current": 1}, name="modelhub_search_models", type="tool_use"), stop_reason="tool_use"),
            message(ToolUseBlock(id="two", input={"current": 1, "keyword": "x"}, name="modelhub_search_models", type="tool_use"), stop_reason="tool_use", seq=2),
            message(TextBlock(text="done", type="text"), seq=3),
        ])
        result = await AgentToolLoop(manager).run(
            client=client,
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "find"}],
            policy=ToolPolicy(allowed_tools=("modelhub_search_models",)),
        )

        self.assertEqual(1, len(calls))
        self.assertIn("duplicate", [record.status for record in result.records])

    async def test_call_budget_switches_to_no_tool_finalization(self):
        calls = []

        async def handler(params, context):
            calls.append(params)
            return {"ok": True}

        manager = manager_with_tool(handler)
        client = FakeClient([
            message(
                ToolUseBlock(id="one", input={"keyword": "a"}, name="modelhub_search_models", type="tool_use"),
                ToolUseBlock(id="two", input={"keyword": "b"}, name="modelhub_search_models", type="tool_use"),
                stop_reason="tool_use",
            ),
            message(TextBlock(text="budget summary", type="text"), seq=2),
        ])
        result = await AgentToolLoop(manager).run(
            client=client,
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "find"}],
            policy=ToolPolicy(allowed_tools=("modelhub_search_models",), max_calls=1),
        )

        self.assertEqual(1, len(calls))
        self.assertTrue(result.limit_reached)
        self.assertNotIn("tools", client.messages.calls[-1])
        self.assertNotIn("tool_choice", client.messages.calls[-1])
        self.assertIn("budget_exceeded", [record.status for record in result.records])

    async def test_tool_result_is_truncated(self):
        async def handler(params, context):
            return {"text": '\\\"' * 10000}

        manager = manager_with_tool(handler)
        client = FakeClient([
            message(ToolUseBlock(id="one", input={"keyword": "x"}, name="modelhub_search_models", type="tool_use"), stop_reason="tool_use"),
            message(TextBlock(text="done", type="text"), seq=2),
        ])
        await AgentToolLoop(manager).run(
            client=client,
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "find"}],
            policy=ToolPolicy(allowed_tools=("modelhub_search_models",), max_result_chars=512),
        )
        content = client.messages.calls[1]["messages"][-1]["content"][0]["content"]
        self.assertLessEqual(len(content), 512)
        self.assertIn("truncated", content)
        self.assertTrue(json.loads(content)["truncated"])

    async def test_rate_limit_does_not_bypass_required_tool(self):
        async def handler(params, context):
            return {"ok": True}

        manager = manager_with_tool(handler)
        client = FakeClient([FakeApiError(429, "rate limited")])

        with self.assertRaises(ToolLoopError) as raised:
            await AgentToolLoop(manager).run(
                client=client,
                model="test-model",
                system="system",
                messages=[{"role": "user", "content": "find"}],
                policy=ToolPolicy(
                    allowed_tools=("modelhub_search_models",),
                    first_choice="modelhub_search_models",
                ),
            )
        self.assertIsInstance(raised.exception.__cause__, FakeApiError)
        self.assertEqual([], raised.exception.records)
        self.assertEqual(1, len(client.messages.calls))

    async def test_forced_or_any_choice_without_tool_use_fails_closed(self):
        async def handler(params, context):
            return {"ok": True}

        manager = manager_with_tool(handler)
        for first_choice in ("any", "modelhub_search_models"):
            with self.subTest(first_choice=first_choice):
                client = FakeClient([message(TextBlock(text="unsupported plain answer", type="text"))])
                with self.assertRaises(ToolLoopError) as raised:
                    await AgentToolLoop(manager).run(
                        client=client,
                        model="test-model",
                        system="system",
                        messages=[{"role": "user", "content": "find"}],
                        policy=ToolPolicy(
                            allowed_tools=("modelhub_search_models",),
                            first_choice=first_choice,
                        ),
                    )
                self.assertIn("强制要求", str(raised.exception))
                self.assertEqual(1, len(client.messages.calls))

    async def test_forced_tool_requires_authoritative_result_from_that_tool(self):
        async def required_handler(params, context):
            return {"success": False, "error": "backend unavailable"}

        async def other_handler(params, context):
            return {"success": True, "data": {"ok": True}}

        manager = manager_with_tool(required_handler, name="modelhub_get_model", schema={
            "type": "object",
            "properties": {"model_id": {"type": "integer"}},
            "required": ["model_id"],
            "additionalProperties": False,
        })
        manager.register(Tool(
            name="modelhub_search_models",
            description="other tool",
            handler=other_handler,
            schema={
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": ["keyword"],
                "additionalProperties": False,
            },
        ))
        client = FakeClient([message(
            ToolUseBlock(id="required", input={"model_id": 42}, name="modelhub_get_model", type="tool_use"),
            ToolUseBlock(id="other", input={"keyword": "safe"}, name="modelhub_search_models", type="tool_use"),
            stop_reason="tool_use",
        )])

        with self.assertRaises(ToolLoopError) as raised:
            await AgentToolLoop(manager).run(
                client=client,
                model="test-model",
                system="system",
                messages=[{"role": "user", "content": "model 42"}],
                policy=ToolPolicy(
                    allowed_tools=("modelhub_get_model", "modelhub_search_models"),
                    first_choice="modelhub_get_model",
                ),
            )

        records = raised.exception.records
        self.assertEqual(["modelhub_get_model", "modelhub_search_models"], [record.name for record in records])
        self.assertFalse(records[0].authoritative)
        self.assertTrue(records[1].authoritative)
        self.assertIn("权威证据", str(raised.exception))

    async def test_any_choice_requires_at_least_one_authoritative_result(self):
        async def handler(params, context):
            return {"success": False, "error": "offline"}

        manager = manager_with_tool(handler)
        client = FakeClient([
            message(
                ToolUseBlock(id="one", input={"keyword": "x"}, name="modelhub_search_models", type="tool_use"),
                stop_reason="tool_use",
            ),
        ])

        with self.assertRaises(ToolLoopError) as raised:
            await AgentToolLoop(manager).run(
                client=client,
                model="test-model",
                system="system",
                messages=[{"role": "user", "content": "find"}],
                policy=ToolPolicy(allowed_tools=("modelhub_search_models",), first_choice="any"),
            )

        self.assertEqual("failed", raised.exception.records[0].status)
        self.assertFalse(raised.exception.records[0].authoritative)

    async def test_later_llm_failure_keeps_successful_tool_records(self):
        async def handler(params, context):
            return {"ok": True}

        manager = manager_with_tool(handler)
        client = FakeClient([
            message(
                ToolUseBlock(id="one", input={"keyword": "x"}, name="modelhub_search_models", type="tool_use"),
                stop_reason="tool_use",
            ),
            FakeApiError(503, "gateway unavailable"),
        ])

        with self.assertRaises(ToolLoopError) as raised:
            await AgentToolLoop(manager).run(
                client=client,
                model="test-model",
                system="system",
                messages=[{"role": "user", "content": "find"}],
                policy=ToolPolicy(allowed_tools=("modelhub_search_models",)),
            )

        self.assertIsInstance(raised.exception.__cause__, FakeApiError)
        self.assertEqual(1, raised.exception.rounds)
        self.assertEqual(["modelhub_search_models"], [record.name for record in raised.exception.records])
        self.assertTrue(raised.exception.records[0].authoritative)

    async def test_same_round_tools_run_concurrently_and_results_keep_request_order(self):
        started = []
        both_started = asyncio.Event()

        async def handler(params, context):
            started.append(params["keyword"])
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=0.5)
            if params["keyword"] == "first":
                await asyncio.sleep(0.02)
            return {"keyword": params["keyword"]}

        manager = manager_with_tool(handler)
        client = FakeClient([
            message(
                ToolUseBlock(id="first-id", input={"keyword": "first"}, name="modelhub_search_models", type="tool_use"),
                ToolUseBlock(id="second-id", input={"keyword": "second"}, name="modelhub_search_models", type="tool_use"),
                stop_reason="tool_use",
            ),
            message(TextBlock(text="done", type="text"), seq=2),
        ])

        result = await AgentToolLoop(manager).run(
            client=client,
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "find both"}],
            policy=ToolPolicy(
                allowed_tools=("modelhub_search_models",),
                max_calls=2,
                max_parallel_calls=2,
            ),
        )

        returned = client.messages.calls[1]["messages"][-1]["content"]
        self.assertEqual(["first-id", "second-id"], [item["tool_use_id"] for item in returned])
        self.assertCountEqual(["first", "second"], started)
        self.assertEqual(2, len(result.records))

    async def test_required_unavailable_fails_even_when_optional_definition_exists(self):
        async def handler(params, context):
            return {"ok": True}

        manager = manager_with_tool(handler)
        client = FakeClient([])

        with self.assertRaises(ToolLoopError):
            await AgentToolLoop(manager).run(
                client=client,
                model="test-model",
                system="system",
                messages=[{"role": "user", "content": "find"}],
                policy=ToolPolicy(
                    allowed_tools=("modelhub_search_models",),
                    required_tool_unavailable=True,
                ),
            )
        self.assertEqual([], client.messages.calls)

    async def test_optional_tools_fallback_only_for_explicit_unsupported_error(self):
        async def handler(params, context):
            return {"ok": True}

        manager = manager_with_tool(handler)
        client = FakeClient([
            FakeApiError(400, "unsupported parameter: tools"),
            message(TextBlock(text="plain fallback", type="text"), seq=2),
        ])

        result = await AgentToolLoop(manager).run(
            client=client,
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "hello"}],
            policy=ToolPolicy(allowed_tools=("modelhub_search_models",), first_choice="auto"),
        )

        self.assertEqual("plain fallback", result.content)
        self.assertNotIn("tools", client.messages.calls[-1])


if __name__ == "__main__":
    unittest.main()
