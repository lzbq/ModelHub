import unittest

from modelhub_tools.model_hub_client import ModelHubClient
from modelhub_tools.tool_manager import MCPToolManager
from api.main import _register_model_hub_tools


class ModelHubUnitTests(unittest.TestCase):

    def test_java_cent_fields_gain_explicit_yuan_fields(self):
        normalized = ModelHubClient._with_display_units({
            "inputPrice": 50,
            "outputPrice": 200,
            "payValue": 990,
            "tokenQuota": 1_000_000,
        })

        self.assertEqual("0.50", normalized["inputPriceYuanPerMillionToken"])
        self.assertEqual("2.00", normalized["outputPriceYuanPerMillionToken"])
        self.assertEqual("9.90", normalized["payValueYuan"])
        self.assertEqual("Token", normalized["tokenQuotaUnit"])

    def test_nested_model_lists_are_normalized(self):
        normalized = ModelHubClient._with_display_units({
            "success": True,
            "data": [{"inputPrice": 100, "outputPrice": 400}],
        })

        model = normalized["data"][0]
        self.assertEqual("1.00", model["inputPriceYuanPerMillionToken"])
        self.assertEqual("4.00", model["outputPriceYuanPerMillionToken"])


class ModelHubCostToolTests(unittest.IsolatedAsyncioTestCase):

    async def test_internal_estimator_fetches_raw_prices_by_model_id(self):
        detail_calls = []

        class FakeClient:
            async def model_detail(self, params, context):
                detail_calls.append((params, context))
                return {
                    "success": True,
                    "data": {"inputPrice": 50, "outputPrice": 200},
                }

            def __getattr__(self, name):
                async def stub(params, context):
                    return {"success": True, "data": []}
                return stub

        manager = MCPToolManager.__new__(MCPToolManager)
        manager._tools = {}
        manager._aliases = {}
        manager._cache = {}
        _register_model_hub_tools(manager, FakeClient())

        definition = manager.get_tool_definitions(("modelhub_estimate_cost",))[0]
        properties = definition["input_schema"]["properties"]
        self.assertEqual(
            {"model_id", "input_tokens", "output_tokens", "requests"},
            set(properties),
        )
        self.assertNotIn("input_price_fen_per_million", properties)
        self.assertNotIn("output_price_fen_per_million", properties)

        result = await manager.call(
            "modelhub_estimate_cost",
            {
                "model_id": 42,
                "input_tokens": 1_000_000,
                "output_tokens": 500_000,
                "requests": 2,
            },
            context={"principal_id": "alice"},
        )

        self.assertTrue(result.success)
        self.assertEqual([({"model_id": 42}, {"principal_id": "alice"})], detail_calls)
        self.assertEqual("3.000000", result.data["total_cost_yuan"])
        self.assertEqual(50, result.data["input_price_fen_per_million"])
        self.assertEqual(200, result.data["output_price_fen_per_million"])
        self.assertEqual("modelhub_model_detail", result.data["price_source"])


if __name__ == "__main__":
    unittest.main()
