import sys
import unittest
from pathlib import Path

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from modelhub_mcp.server import mcp
from modelhub_mcp.service import estimate_token_cost


class ModelHubMCPUnitTests(unittest.TestCase):

    def test_cost_calculation_uses_fen_per_million_token(self):
        result = estimate_token_cost(
            input_tokens=1_000,
            output_tokens=500,
            requests=10,
            input_price_fen_per_million=100,
            output_price_fen_per_million=200,
        )

        self.assertEqual(10_000, result["total_input_tokens"])
        self.assertEqual(5_000, result["total_output_tokens"])
        self.assertEqual("0.010000", result["input_cost_yuan"])
        self.assertEqual("0.010000", result["output_cost_yuan"])
        self.assertEqual("0.020000", result["total_cost_yuan"])


class ModelHubMCPProtocolTests(unittest.IsolatedAsyncioTestCase):

    async def test_protocol_lists_only_public_read_only_tools(self):
        async with Client(mcp) as client:
            listing = await client.list_tools()

        tools = {tool.name: tool for tool in listing.tools}
        self.assertEqual(
            {
                "modelhub_hot_models",
                "modelhub_search_models",
                "modelhub_get_model",
                "modelhub_list_packages",
                "modelhub_get_package",
                "modelhub_hot_packages",
                "modelhub_estimate_cost",
            },
            set(tools),
        )
        for tool in tools.values():
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.destructive_hint)
            self.assertNotIn("auth_token", str(tool.input_schema).lower())
        self.assertNotIn("token_order", tools)
        self.assertNotIn("token_account", tools)

    async def test_protocol_calls_deterministic_cost_tool(self):
        async with Client(mcp) as client:
            result = await client.call_tool(
                "modelhub_estimate_cost",
                {
                    "input_tokens": 1_000,
                    "output_tokens": 500,
                    "input_price_fen_per_million": 100,
                    "output_price_fen_per_million": 200,
                    "requests": 10,
                },
            )

        self.assertFalse(result.is_error)
        payload = result.structured_content.get("result", result.structured_content)
        self.assertEqual("0.020000", payload["total_cost_yuan"])

    async def test_stdio_transport_round_trip(self):
        project_root = Path(__file__).resolve().parents[1]
        server = StdioServerParameters(
            command=sys.executable,
            args=["-B", "-m", "modelhub_mcp.server"],
            cwd=project_root,
        )

        async with Client(stdio_client(server)) as client:
            listing = await client.list_tools()

        self.assertIn("modelhub_estimate_cost", {tool.name for tool in listing.tools})


if __name__ == "__main__":
    unittest.main()
