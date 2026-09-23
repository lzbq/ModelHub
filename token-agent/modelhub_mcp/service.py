"""Protocol-independent public service used by the MCP tool facade."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

from modelhub_tools.model_hub_client import ModelHubClient


class ModelHubPublicService:
    """Expose only public, read-only ModelHub backend operations."""

    def __init__(self, client: ModelHubClient):
        self.client = client
    #_safe() 是一个包装器。所有查询后端的方法都通过它执行。好处是 MCP 工具调用失败时，不会直接抛 Python 异常给 agent，而是返回统一格式
    async def _safe(self, operation: Callable[[], Awaitable[Dict[str, Any]]]) -> Dict[str, Any]:
        #Callable：它是一个可以调用的函数
        #[]：调用它时不需要传参数
        #Awaitable[...]：调用后返回一个可以 await 的结果
        #Dict[str, Any]：最终 await 出来的结果是一个字典
        try:
            return await operation()
        except httpx.TimeoutException:
            return {"success": False, "error": "ModelHub 后端查询超时，请稍后重试", "data": None}
        except httpx.HTTPStatusError as ex:
            return {
                "success": False,
                "error": f"ModelHub 后端返回 HTTP {ex.response.status_code}",
                "data": None,
            }
        except (httpx.HTTPError, ValueError, TypeError):
            return {"success": False, "error": "ModelHub 后端查询失败，请稍后重试", "data": None}

    async def hot_models(self, category: Optional[str], current: int) -> Dict[str, Any]:
        #self.client.hot_models(...) 是异步函数，调用后返回的是一个 Awaitable
        #这个 lambda 的意思是：先不要马上执行请求，只把“以后怎么执行这个请求”交给 _safe()。
        return await self._safe(lambda: self.client.hot_models({"category": category, "current": current}))

    async def search_models(self, keyword: str, current: int) -> Dict[str, Any]:
        return await self._safe(lambda: self.client.search_models({"keyword": keyword, "current": current}))

    async def get_model(self, model_id: int) -> Dict[str, Any]:
        return await self._safe(lambda: self.client.model_detail({"model_id": model_id}))

    async def list_packages(self, model_id: int) -> Dict[str, Any]:
        return await self._safe(lambda: self.client.model_packages({"model_id": model_id}))

    async def get_package(self, package_id: int) -> Dict[str, Any]:
        return await self._safe(lambda: self.client.package_detail({"package_id": package_id}))

    async def hot_packages(self, current: int) -> Dict[str, Any]:
        return await self._safe(lambda: self.client.hot_packages({"current": current}))


def estimate_token_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    requests: int,
    input_price_fen_per_million: float,
    output_price_fen_per_million: float,
) -> Dict[str, Any]:
    """Calculate CNY cost from Java backend prices expressed in fen / 1M Token."""
    try:
        input_price = Decimal(str(input_price_fen_per_million))
        output_price = Decimal(str(output_price_fen_per_million))
    except InvalidOperation as ex:
        raise ValueError("价格必须是有效数字") from ex
    if min(input_tokens, output_tokens, requests) < 0 or input_price < 0 or output_price < 0:
        raise ValueError("Token、调用次数和价格不能为负数")

    million = Decimal("1000000")
    fen_per_yuan = Decimal("100")
    total_input_tokens = input_tokens * requests
    total_output_tokens = output_tokens * requests
    input_cost = Decimal(total_input_tokens) * input_price / million / fen_per_yuan
    output_cost = Decimal(total_output_tokens) * output_price / million / fen_per_yuan
    total_cost = input_cost + output_cost

    def money(value: Decimal) -> str:
        return format(value.quantize(Decimal("0.000001")), "f")

    return {
        "success": True,
        "currency": "CNY",
        "price_unit": "fen_per_million_tokens",
        "requests": requests,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "input_cost_yuan": money(input_cost),
        "output_cost_yuan": money(output_cost),
        "total_cost_yuan": money(total_cost),
    }


__all__ = ["ModelHubPublicService", "estimate_token_cost"]
