"""Smoke-test a running ModelHub Streamable HTTP MCP endpoint."""
import argparse
import asyncio

from mcp import Client


async def smoke(url: str) -> None:
    async with Client(url) as client:
        listing = await client.list_tools()
        names = {tool.name for tool in listing.tools}
        required = {"modelhub_search_models", "modelhub_estimate_cost"}
        missing = required - names
        if missing:
            raise RuntimeError(f"MCP tools missing: {sorted(missing)}")
        result = await client.call_tool(
            "modelhub_estimate_cost",
            {
                "input_tokens": 1000,
                "output_tokens": 500,
                "input_price_fen_per_million": 100,
                "output_price_fen_per_million": 200,
                "requests": 10,
            },
        )
        if result.is_error:
            raise RuntimeError("MCP cost tool returned an error")
        payload = result.structured_content.get("result", result.structured_content)
        if payload.get("total_cost_yuan") != "0.020000":
            raise RuntimeError(f"Unexpected MCP result: {payload}")
        print(f"MCP smoke OK: {url} ({len(names)} tools)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8010/mcp")
    args = parser.parse_args()
    asyncio.run(smoke(args.url))


if __name__ == "__main__":
    main()
