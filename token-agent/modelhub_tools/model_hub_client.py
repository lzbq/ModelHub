"""Read-only tools for the ModelHub Java backend."""
from typing import Any, Dict, Optional
from urllib.parse import urljoin
from decimal import Decimal, InvalidOperation

import httpx


class ModelHubClient:
    """
    ModelHub Java 后端的只读异步客户端。

    Agent 模型白名单只包含公共模型/套餐查询；订单和额度必须由应用代码在
    明确私有动作及 Bearer 上下文下确定性调用。抢购、支付、退款及额度调整
    必须由 Java 业务页面在用户确认后执行。
    """

    def __init__(self, base_url: str, timeout_s: float = 5.0, default_auth_token: str = ""):
        self.base_url = base_url.rstrip("/") + "/"             #Java 后端地址
        self.timeout_s = timeout_s                             #HTTP 超时时间，默认 5 秒
        self.default_auth_token = default_auth_token.strip()   #默认鉴权 token，可为空

    async def _request(
        self,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        auth_token: Optional[str] = None,
        allow_default_auth: bool = True,
    ) -> Dict[str, Any]:
        token = (auth_token or (self.default_auth_token if allow_default_auth else "") or "").strip()
        headers = {"authorization": token} if token else {}
        async with httpx.AsyncClient(timeout=self.timeout_s, trust_env=False) as client:
            response = await client.get(
                urljoin(self.base_url, path.lstrip("/")),#拼出完整 URL：base_url + path
                #过滤掉值为 None 的 query 参数
                params={key: value for key, value in (params or {}).items() if value is not None},
                headers=headers,#如果有 token，就加请求头
            )
            response.raise_for_status()#检查 HTTP 状态码
            data = response.json()
        if isinstance(data, dict) and data.get("success") is False:
            return {
                "success": False,
                "error": data.get("errorMsg") or "ModelHub Java 后端返回失败",
                "data": data.get("data"),
                "total": data.get("total"),
            }
        if isinstance(data, dict) and "success" in data:
            return {
                "success": True,
                "data": self._with_display_units(data.get("data")),
                "total": data.get("total"),
            }
        return {"success": True, "data": self._with_display_units(data), "total": None}

    @classmethod
    def _with_display_units(cls, value: Any) -> Any:
        """保留 Java 原始分值，同时增加明确的人民币元展示字段。"""
        if isinstance(value, list):
            return [cls._with_display_units(item) for item in value]
        if not isinstance(value, dict):
            return value

        normalized = {key: cls._with_display_units(item) for key, item in value.items()}
        cls._append_yuan_field(normalized, "inputPrice", "inputPriceYuanPerMillionToken")
        cls._append_yuan_field(normalized, "outputPrice", "outputPriceYuanPerMillionToken")
        cls._append_yuan_field(normalized, "input_price", "input_price_yuan_per_million_token")
        cls._append_yuan_field(normalized, "output_price", "output_price_yuan_per_million_token")
        cls._append_yuan_field(normalized, "payValue", "payValueYuan")
        cls._append_yuan_field(normalized, "pay_value", "pay_value_yuan")
        if "tokenQuota" in normalized:
            normalized.setdefault("tokenQuotaUnit", "Token")
        if "token_quota" in normalized:
            normalized.setdefault("token_quota_unit", "Token")
        return normalized

    @staticmethod
    def _append_yuan_field(data: Dict[str, Any], source: str, target: str) -> None:
        if source not in data or data[source] is None:
            return
        try:
            yuan = Decimal(str(data[source])) / Decimal("100")
        except (InvalidOperation, ValueError):
            return
        data.setdefault(target, format(yuan.quantize(Decimal("0.01")), "f"))


    @staticmethod
    def _token(params: Dict[str, Any], context: Optional[Dict[str, Any]]) -> str:
        if context and context.get("auth_token"):
            return str(context["auth_token"])
        return ""
    #查热门模型
    async def hot_models(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("/ai-model/hot", params={
            "category": params.get("category"),
            "current": int(params.get("current", 1)),
        })
    #按关键词搜模型
    async def search_models(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("/ai-model/search", params={
            "keyword": str(params["keyword"]),
            "current": int(params.get("current", 1)),
        })
    #查模型详情
    async def model_detail(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request(f"/ai-model/{int(params['model_id'])}")
    #查某模型可买套餐
    async def model_packages(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request(f"/token-package/model/{int(params['model_id'])}")
    #查套餐详情
    async def package_detail(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request(f"/token-package/{int(params['package_id'])}")

    # 查热门套餐
    async def hot_packages(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("/token-package/hot", params={"current": int(params.get("current", 1))})

    # 查当前用户订单，需要 token
    async def token_order(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        auth_token = self._token(params, context)
        if not auth_token:
            return {"success": False, "error": "需要登录后才能查询订单", "data": None}
        return await self._request(
            f"/token-order/{int(params['order_id'])}",
            auth_token=auth_token,
            allow_default_auth=False,
        )
    #查当前用户额度账户，需要 token
    async def token_account(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        auth_token = self._token(params, context)
        if not auth_token:
            return {"success": False, "error": "需要登录后才能查询额度账户", "data": None}
        return await self._request(
            "/token-order/account/me",
            params={"modelId": params.get("model_id")},
            auth_token=auth_token,
            allow_default_auth=False,
        )
