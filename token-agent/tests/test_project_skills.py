import tempfile
import unittest
from pathlib import Path

from agents.agent_orchestrator import (
    AgentOrchestrator,
    AgentResponse,
    AgentType,
    ModelAdvisorAgent,
    Request,
)
from core.intent_recognizer import IntentCategory
from core.project_skills import ProjectSkillError, ProjectSkillRegistry
from agents.tool_use import ToolPolicy


class ProjectSkillRegistryTests(unittest.TestCase):

    def test_repository_skills_load_and_resolve_in_order(self):
        registry = ProjectSkillRegistry()
        names = [skill.name for skill in registry.list()]

        self.assertEqual(
            [
                "modelhub-api-troubleshooting",
                "modelhub-cost-estimation",
                "modelhub-model-selection",
                "modelhub-quota-order",
                "modelhub-risk-review",
            ],
            names,
        )
        resolved, prompt = registry.resolve(
            ["modelhub-model-selection", "modelhub-cost-estimation", "modelhub-model-selection"]
        )
        self.assertEqual(["modelhub-model-selection", "modelhub-cost-estimation"], resolved)
        self.assertLess(prompt.index("modelhub-model-selection"), prompt.index("modelhub-cost-estimation"))

    def test_invalid_frontmatter_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "broken-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: broken-skill\ndescription: Broken\nextra: forbidden\n---\nDo work.\n",
                encoding="utf-8",
            )
            with self.assertRaises(ProjectSkillError):
                ProjectSkillRegistry(tmp)


class ProjectSkillOrchestratorTests(unittest.IsolatedAsyncioTestCase):

    def test_skill_is_appended_to_system_prompt(self):
        agent = ModelAdvisorAgent.__new__(ModelAdvisorAgent)
        request = Request(
            message="推荐模型",
            user_id="u1",
            conv_id="c1",
            skill_instructions='<project-skill name="modelhub-model-selection">流程</project-skill>',
        )

        prompt = agent._build_system_prompt(request)

        self.assertTrue(prompt.startswith(agent.system_prompt))
        self.assertIn("[项目内部 Skill 工作流]", prompt)
        self.assertIn("modelhub-model-selection", prompt)

    def test_intent_and_agent_map_to_deterministic_skills(self):
        orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
        request = Request(
            message="估算用量",
            user_id="u1",
            conv_id="c1",
            intent=IntentCategory.USAGE_ANALYSIS,
        )

        self.assertEqual(
            ("modelhub-cost-estimation",),
            orchestrator._skill_names_for_execution(request, AgentType.COST_OPTIMIZER),
        )
        self.assertEqual(
            ("modelhub-cost-estimation",),
            orchestrator._skill_names_for_execution(request, AgentType.GENERAL),
        )

    def test_tool_policy_forces_public_detail_and_never_exposes_private_tools(self):
        orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
        orchestrator._tool_use_enabled = True
        orchestrator._available_tool_names = {
            name for names in orchestrator._AGENT_TOOLS.values() for name in names
        }
        orchestrator._tool_max_rounds = 3
        orchestrator._tool_max_calls = 4
        orchestrator._tool_max_parallel_calls = 3
        orchestrator._tool_result_max_chars = 8000
        request = Request(
            message="查看 42 号模型价格",
            user_id="u1",
            conv_id="c1",
            intent=IntentCategory.MODEL_SEARCH,
            tool_inputs={"model_id": 42, "current": 1},
        )

        policy = orchestrator._tool_policy_for_execution(request, AgentType.MODEL_ADVISOR)

        self.assertEqual("modelhub_get_model", policy.first_choice)
        self.assertEqual({"model_id": 42}, policy.locked_inputs["modelhub_get_model"])
        self.assertNotIn("token_order", policy.allowed_tools)
        self.assertNotIn("token_account", policy.allowed_tools)

    async def test_execute_clones_request_before_injecting_skill(self):
        orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)

        class Registry:
            def resolve(self, names):
                return list(names), "trusted workflow"

        class Agent:
            async def handle(self, request):
                self.seen = request
                return AgentResponse(AgentType.MODEL_ADVISOR, "ok", True)

        agent = Agent()
        orchestrator._skill_registry = Registry()
        orchestrator._tool_policy_for_execution = lambda request, agent_type: ToolPolicy()
        orchestrator._best_agent = lambda agent_type: agent
        request = Request(
            message="推荐模型",
            user_id="u1",
            conv_id="c1",
            intent=IntentCategory.MODEL_SEARCH,
        )

        response = await orchestrator._execute(request, AgentType.MODEL_ADVISOR)

        self.assertEqual("", request.skill_instructions)
        self.assertEqual("trusted workflow", agent.seen.skill_instructions)
        self.assertEqual(["modelhub-model-selection"], response.skills_used)

    async def test_required_tool_failure_does_not_fall_back_to_unconstrained_answer(self):
        orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)

        class Registry:
            def resolve(self, names):
                return list(names), "trusted workflow"

        class FailingAgent:
            def __init__(self):
                self.calls = 0

            async def handle(self, request):
                self.calls += 1
                return AgentResponse(AgentType.MODEL_ADVISOR, "generic failure", False)

        agent = FailingAgent()
        orchestrator._skill_registry = Registry()
        orchestrator._tool_use_enabled = True
        orchestrator._available_tool_names = {"modelhub_hot_models"}
        orchestrator._tool_max_rounds = 3
        orchestrator._tool_max_calls = 4
        orchestrator._tool_max_parallel_calls = 3
        orchestrator._tool_result_max_chars = 8000
        orchestrator._best_agent = lambda agent_type: agent
        request = Request(
            message="推荐当前热门模型",
            user_id="u1",
            conv_id="c1",
            intent=IntentCategory.MODEL_SEARCH,
        )

        response = await orchestrator._execute(request, AgentType.MODEL_ADVISOR)

        self.assertEqual(1, agent.calls)
        self.assertTrue(response.success)
        self.assertIn("无法调用", response.content)
        self.assertIn("不能核验", response.content)


if __name__ == "__main__":
    unittest.main()
