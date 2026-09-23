import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from api.main import (
    ChatRequest,
    EvalDialogInput,
    EvalRunInput,
    _memory_subject,
    _private_query_flags,
    _require_eval_admin,
    _resolve_auth_token,
    _sanitize_private_payload,
)


class ApiAuthBoundaryTests(unittest.TestCase):

    def test_numeric_user_id_is_normalized_for_java_api_clients(self):
        request = ChatRequest(message="推荐一个模型", user_id=7)

        self.assertEqual("7", request.user_id)

    def test_bearer_header_wins_and_body_token_is_ignored_by_default(self):
        request = ChatRequest(message="余额", auth_token="body-secret")

        with patch.dict(os.environ, {"ALLOW_LEGACY_BODY_AUTH_TOKEN": "false"}):
            self.assertEqual("header-secret", _resolve_auth_token(request, "Bearer header-secret"))
            self.assertEqual("", _resolve_auth_token(request, None))

    def test_non_bearer_authorization_is_rejected(self):
        request = ChatRequest(message="余额")
        with self.assertRaises(HTTPException) as raised:
            _resolve_auth_token(request, "Basic abc")
        self.assertEqual(401, raised.exception.status_code)

    def test_memory_subject_never_contains_raw_identity_or_token(self):
        authenticated = _memory_subject("claimed-user", "very-secret-token")
        anonymous = _memory_subject("name:with:delimiter", "")

        self.assertNotIn("very-secret-token", authenticated)
        self.assertNotIn("claimed-user", authenticated)
        self.assertNotIn("name:with:delimiter", anonymous)
        self.assertNotEqual(authenticated, anonymous)

    def test_private_projection_removes_credentials_and_pii_but_keeps_quota(self):
        projected = _sanitize_private_payload({
            "authToken": "secret",
            "userId": 7,
            "phone": "13000000000",
            "data": {
                "tokenQuota": 1000000,
                "status": "ACTIVE",
                "remainingToken": 50,
                "unknownProfile": {"displayName": "private"},
            },
        }, tool_name="token_account")

        self.assertNotIn("authToken", projected)
        self.assertNotIn("userId", projected)
        self.assertNotIn("phone", projected)
        self.assertEqual(1000000, projected["data"]["tokenQuota"])
        self.assertEqual(50, projected["data"]["remainingToken"])
        self.assertNotIn("unknownProfile", projected["data"])

    def test_private_projection_is_specific_to_each_interface(self):
        projected = _sanitize_private_payload({
            "data": {
                "orderId": 9,
                "packageName": "测试套餐",
                "payStatus": "PAID",
                "remainingToken": 123,
                "email": "should-not-pass@example.com",
            },
        }, tool_name="token_order")

        self.assertEqual(9, projected["data"]["orderId"])
        self.assertEqual("测试套餐", projected["data"]["packageName"])
        self.assertNotIn("remainingToken", projected["data"])
        self.assertNotIn("email", projected["data"])

    def test_private_prefetch_requires_an_explicit_action(self):
        self.assertEqual(
            (False, False),
            _private_query_flags(ChatRequest(message="推荐一个便宜模型", order_id=99)),
        )
        self.assertEqual(
            (False, False),
            _private_query_flags(ChatRequest(message="Token 消耗怎么算")),
        )
        self.assertEqual(
            (True, False),
            _private_query_flags(ChatRequest(message="查询订单状态", order_id=99)),
        )
        self.assertEqual(
            (False, True),
            _private_query_flags(ChatRequest(message="查询我的用量")),
        )

    def test_eval_payload_rejects_auth_tokens_and_unknown_fields(self):
        with self.assertRaises(ValidationError):
            EvalDialogInput(question="hello", auth_token="must-not-enter-eval")
        with self.assertRaises(ValidationError):
            EvalRunInput(auth_token="must-not-enter-eval")

    def test_eval_admin_auth_is_disabled_without_config_and_constant_time_checked(self):
        with patch.dict(os.environ, {"EVAL_ADMIN_TOKEN": ""}):
            with self.assertRaises(HTTPException) as disabled:
                _require_eval_admin("Bearer anything")
        self.assertEqual(503, disabled.exception.status_code)

        with patch.dict(os.environ, {"EVAL_ADMIN_TOKEN": "admin-secret"}):
            with self.assertRaises(HTTPException) as rejected:
                _require_eval_admin("Bearer wrong-secret")
            self.assertEqual(401, rejected.exception.status_code)
            _require_eval_admin("Bearer admin-secret")


if __name__ == "__main__":
    unittest.main()
