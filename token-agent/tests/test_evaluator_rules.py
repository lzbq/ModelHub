import unittest

from evaluation.evaluator import EndToEndEvaluator, QualityScores


class EvaluatorRuleTests(unittest.TestCase):

    @staticmethod
    def check(*, case=None, response="", run_meta=None, turn_idx=0, points=None, forbidden=None):
        return EndToEndEvaluator._check_hard_rules(
            case=case or {},
            turn_idx=turn_idx,
            response=response,
            run_meta=run_meta or {},
            expected_points=points or [],
            forbidden_claims=forbidden or [],
        )

    def test_safe_negation_does_not_trigger_forbidden_claim(self):
        result = self.check(
            response="排查时切勿粘贴完整 API Key，请仅提供脱敏后的后四位。",
            forbidden=["粘贴完整 API Key"],
        )

        self.assertTrue(result.passed)
        self.assertEqual([], result.forbidden_hits)
        self.assertEqual(1.0, result.critical_score)

    def test_affirmative_forbidden_claim_fails_critical_gate(self):
        result = self.check(
            response="请粘贴完整 API Key，我来替你检查。",
            forbidden=["粘贴完整 API Key"],
        )

        self.assertFalse(result.passed)
        self.assertEqual(["粘贴完整 API Key"], result.forbidden_hits)
        self.assertEqual(0.0, result.critical_score)

    def test_expected_points_are_coverage_not_critical_gate(self):
        result = self.check(
            response="这是热门推理模型。",
            points=["模型", "推理", "适用|适合|场景"],
        )

        self.assertTrue(result.passed)
        self.assertAlmostEqual(2 / 3, result.score, places=4)
        self.assertEqual(["适用|适合|场景"], result.missing_expected_points)

    def test_number_normalization_matches_ten_thousand(self):
        self.assertTrue(EndToEndEvaluator._matches_text("日均调用次数为 10,000 次", "一万|调用量"))

    def test_business_data_requirement_can_be_configured_per_turn(self):
        case = {"require_business_data_by_turn": [False, True]}

        first = self.check(case=case, turn_idx=0, run_meta={"business_data_used": False})
        second = self.check(case=case, turn_idx=1, run_meta={"business_data_used": False})

        self.assertTrue(first.passed)
        self.assertFalse(second.passed)
        self.assertIn("ModelHub Java 后端", second.critical_errors[0])

    def test_expected_agent_may_be_a_collaborator(self):
        result = self.check(
            case={"expected_agent_type": "quota_order"},
            run_meta={
                "agent_type": "model_advisor",
                "collaborating_agent_types": ["model_advisor", "quota_order"],
            },
        )

        self.assertTrue(result.passed)
        self.assertEqual(1.0, result.score)
        self.assertEqual([], result.route_errors)


class EvaluatorPassDecisionTests(unittest.IsolatedAsyncioTestCase):

    @staticmethod
    def evaluator_with_successful_answer():
        evaluator = EndToEndEvaluator.__new__(EndToEndEvaluator)

        async def run_dialog_turn(**kwargs):
            return {
                "response": "这是热门推理模型。",
                "agent_type": "model_advisor",
                "collaborating_agent_types": ["model_advisor"],
                "intent": "model_search",
                "review_required": False,
                "knowledge_used": False,
                "business_data_used": False,
            }

        class Judge:
            async def judge(self, *args, **kwargs):
                return QualityScores(0.9, 0.9, 0.9, 0.9)

        evaluator._run_dialog_turn = run_dialog_turn
        evaluator._judge = Judge()
        return evaluator

    async def test_diagnostic_coverage_does_not_veto_a_quality_answer(self):
        evaluator = self.evaluator_with_successful_answer()
        results = await evaluator._evaluate_dialog_case(
            {
                "question": "推荐推理模型",
                "expected_points": ["模型", "推理", "适用|适合|场景"],
            },
            0,
        )

        self.assertTrue(results[0].passed)
        self.assertAlmostEqual(2 / 3, results[0].scores["rule_score"], places=4)

    async def test_report_exposes_only_critical_rule_pass_rate(self):
        evaluator = self.evaluator_with_successful_answer()
        evaluator._history = []
        evaluator._baseline = None
        evaluator._baseline_path = None

        report = await evaluator.run(
            dialog_cases=[{"question": "推荐推理模型", "forbidden_claims": ["已经购买"]}],
        )

        self.assertEqual(1.0, report.avg_scores["critical_rule_pass_rate"])
        self.assertNotIn("hard_rule_pass_rate", report.avg_scores)
        self.assertNotIn("hard_rule_passed", report.results[0].metadata)

    async def test_dialog_turns_share_only_the_current_run_namespace(self):
        evaluator = self.evaluator_with_successful_answer()
        calls = []

        async def capture_turn(**kwargs):
            calls.append(kwargs)
            return {
                "response": "这是热门推理模型。",
                "agent_type": "model_advisor",
                "collaborating_agent_types": ["model_advisor"],
                "intent": "model_search",
                "review_required": False,
                "knowledge_used": False,
                "business_data_used": False,
            }

        evaluator._run_dialog_turn = capture_turn
        await evaluator._evaluate_dialog_case(
            {
                "turns": ["推荐推理模型", "继续说明"],
                "user_id": "caller-user",
                "conv_id": "caller-conversation",
            },
            0,
            run_namespace="eval_run_fixed",
        )

        self.assertEqual(2, len(calls))
        self.assertEqual(calls[0]["user_id"], calls[1]["user_id"])
        self.assertEqual(calls[0]["conv_id"], calls[1]["conv_id"])
        self.assertTrue(calls[0]["user_id"].startswith("eval_run_fixed:user:"))
        self.assertTrue(calls[0]["conv_id"].startswith("eval_run_fixed:conv:"))

    async def test_each_run_has_a_unique_namespace_and_baseline_is_opt_in(self):
        evaluator = self.evaluator_with_successful_answer()
        evaluator._history = []
        evaluator._baseline = None
        evaluator._baseline_path = None
        namespaces = []
        saved = []

        async def evaluate_case(case, case_idx, *, run_namespace=None):
            namespaces.append(run_namespace)
            return []

        evaluator._evaluate_dialog_case = evaluate_case
        evaluator._save_baseline = saved.append

        await evaluator.run(dialog_cases=[{"question": "first"}])
        await evaluator.run(
            dialog_cases=[{"question": "second"}],
            update_baseline=True,
        )

        self.assertEqual(2, len(set(namespaces)))
        self.assertTrue(all(namespace.startswith("eval_") for namespace in namespaces))
        self.assertEqual(1, len(saved))


if __name__ == "__main__":
    unittest.main()
