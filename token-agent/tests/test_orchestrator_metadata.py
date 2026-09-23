import unittest

from agents.agent_orchestrator import (
    AgentOrchestrator,
    AgentResponse,
    AgentType,
    Request,
)
from core.intent_recognizer import IntentCategory, UrgencyLevel
from agents.tool_use import ToolUseRecord


class OrchestratorMetadataTests(unittest.IsolatedAsyncioTestCase):

    async def test_parallel_run_uses_intent_route_as_primary_agent(self):
        orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
        orchestrator._route = lambda intent, urgency: AgentType.QUOTA_ORDER

        async def execute(req, agent_type):
            tool_name = "modelhub_hot_packages" if agent_type == AgentType.QUOTA_ORDER else "modelhub_hot_models"
            record = ToolUseRecord(tool_name, "public_business", "success", authoritative=True)
            return AgentResponse(
                agent_type=agent_type,
                content=agent_type.value,
                success=True,
                tools_used=[tool_name],
                tool_records=[record],
                tool_call_count=1,
                tool_rounds=1,
            )

        orchestrator._execute = execute
        request = Request(
            message="有便宜的 Token 套餐优先推荐",
            user_id="u1",
            conv_id="c1",
            intent=IntentCategory.TOKEN_PACKAGE,
            urgency=UrgencyLevel.LOW,
        )

        result = await orchestrator.run_parallel(
            request,
            [AgentType.MODEL_ADVISOR, AgentType.QUOTA_ORDER],
        )

        self.assertEqual(AgentType.QUOTA_ORDER, result.agent_type)
        self.assertEqual(
            [AgentType.QUOTA_ORDER, AgentType.MODEL_ADVISOR],
            result.collaborating_agent_types,
        )
        self.assertTrue(result.response.startswith("[quota_order]"))
        self.assertEqual(["modelhub_hot_packages", "modelhub_hot_models"], result.tools_used)
        self.assertEqual(2, result.tool_call_count)
        self.assertEqual(1, result.tool_rounds)


if __name__ == "__main__":
    unittest.main()
