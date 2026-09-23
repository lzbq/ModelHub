"""ModelHub MCP 2.0 server with stdio and Streamable HTTP transports."""
from __future__ import annotations

import argparse
import os
from functools import lru_cache
from typing import Annotated, Any, Dict, Optional

from dotenv import load_dotenv
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from modelhub_mcp.service import ModelHubPublicService, estimate_token_cost
from modelhub_tools.model_hub_client import ModelHubClient

load_dotenv()
#创建了一个 MCP 服务，名字叫 modelhub
mcp = MCPServer(
    name="modelhub",
    title="ModelHub Public Tools",
    description="Public model catalog, Token package, and deterministic cost tools.",
    version="1.0.0",
    #告诉调用方这个 MCP 只能用于：查询公开模型数据、查询公开套餐数据、做确定性的成本计算
    #并且明确禁止：API Key、auth token、密码、支付凭证、购买、支付、退款、额度变更、用户订单、账户余额等敏感操作
    instructions=(
        "Use these tools only for public ModelHub model/package data and deterministic cost calculation. "
        "Prices returned by Java fields inputPrice/outputPrice/payValue are in fen; convert to yuan by dividing by 100. "
        "Never ask for or pass API keys, auth tokens, passwords, payment credentials, or other secrets. "
        "Purchases, payments, refunds, quota changes, user orders, and account balances are intentionally unavailable."
    ),
)
#这两个是工具注解。
#PUBLIC_READ_ONLY 表示工具是公开只读查询，例如查模型、查套餐。
#LOCAL_READ_ONLY 表示本地只读计算，例如估算 Token 成本。
PUBLIC_READ_ONLY = ToolAnnotations(
    #意思是这些工具不会写数据、不会破坏数据、多次调用结果语义上安全。
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,#表示会访问外部世界，比如 ModelHub 后端。
)
LOCAL_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

#创建后端服务客户端
@lru_cache(maxsize=1)#只创建一次，后面复用。
def get_service() -> ModelHubPublicService:
    client = ModelHubClient(
        base_url=os.getenv("MODELHUB_API_BASE_URL", "http://127.0.0.1:8081").strip(),
        timeout_s=float(os.getenv("MODELHUB_API_TIMEOUT", "5")),
        # 公开 MCP 工具不会继承用户登录态或默认 token
        default_auth_token="",
    )
    return ModelHubPublicService(client)

#装饰器会把 Python 函数暴露成 Agent 可调用的工具。
@mcp.tool(title="查询热门模型", annotations=PUBLIC_READ_ONLY)
async def modelhub_hot_models(
    category: Annotated[Optional[str], Field(max_length=100)] = None,
    current: Annotated[int, Field(ge=1, le=10000)] = 1,
) -> Dict[str, Any]:
    """Query the public ModelHub hot-model catalog, optionally by category."""
    return await get_service().hot_models(category, current)


@mcp.tool(title="搜索模型", annotations=PUBLIC_READ_ONLY)
async def modelhub_search_models(
    keyword: Annotated[str, Field(min_length=1, max_length=100)],
    current: Annotated[int, Field(ge=1, le=10000)] = 1,
) -> Dict[str, Any]:
    """Search the public ModelHub model catalog by keyword."""
    return await get_service().search_models(keyword.strip(), current)


@mcp.tool(title="查询模型详情", annotations=PUBLIC_READ_ONLY)
async def modelhub_get_model(
    model_id: Annotated[int, Field(ge=1)],
) -> Dict[str, Any]:
    """Get public details and prices for one ModelHub model ID."""
    return await get_service().get_model(model_id)


@mcp.tool(title="查询模型套餐", annotations=PUBLIC_READ_ONLY)
async def modelhub_list_packages(
    model_id: Annotated[int, Field(ge=1)],
) -> Dict[str, Any]:
    """List public Token packages available for one ModelHub model ID."""
    return await get_service().list_packages(model_id)


@mcp.tool(title="查询套餐详情", annotations=PUBLIC_READ_ONLY)
async def modelhub_get_package(
    package_id: Annotated[int, Field(ge=1)],
) -> Dict[str, Any]:
    """Get public details, quota, price, and inventory for one package ID."""
    return await get_service().get_package(package_id)


@mcp.tool(title="查询热门套餐", annotations=PUBLIC_READ_ONLY)
async def modelhub_hot_packages(
    current: Annotated[int, Field(ge=1, le=10000)] = 1,
) -> Dict[str, Any]:
    """Query public popular or limited-time ModelHub Token packages."""
    return await get_service().hot_packages(current)


@mcp.tool(title="估算 Token 成本", annotations=LOCAL_READ_ONLY)
def modelhub_estimate_cost(
    input_tokens: Annotated[int, Field(ge=0, le=10**12)],#输入 token 数
    output_tokens: Annotated[int, Field(ge=0, le=10**12)],
    input_price_fen_per_million: Annotated[float, Field(ge=0, le=10**9)],#输入价格，单位是“分 / 百万 token”
    output_price_fen_per_million: Annotated[float, Field(ge=0, le=10**9)],
    requests: Annotated[int, Field(ge=1, le=10**9)] = 1,#请求次数
) -> Dict[str, Any]:
    """Deterministically calculate input, output, and total CNY cost."""
    return estimate_token_cost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        requests=requests,
        input_price_fen_per_million=input_price_fen_per_million,
        output_price_fen_per_million=output_price_fen_per_million,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ModelHub MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("MODELHUB_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("MODELHUB_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MODELHUB_MCP_PORT", "8010")))
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return
    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
