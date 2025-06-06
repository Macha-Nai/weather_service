import os
import json
import logging
from datetime import datetime, timedelta
from collections.abc import Sequence
from functools import lru_cache
from typing import Any
import httpx
from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource
)
from pydantic import AnyUrl

# 環境変数の読み込み
load_dotenv()

# ログの準備
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weather-server")

# APIキーの準備
API_KEY = os.getenv("OPENWEATHER_API_KEY")
if not API_KEY:
    raise ValueError("OPENWEATHER_API_KEY environment variable required")

# 定数の準備
API_BASE_URL = "http://api.openweathermap.org/data/2.5"
DEFAULT_CITY = "London"
CURRENT_WEATHER_ENDPOINT = "weather"
FORECAST_ENDPOINT = "forecast"

# HTTPパラメータの準備
http_params = {
    "appid": API_KEY,
    "units": "metric"
}

# OpenWeatherで天気情報を取得
async def fetch_weather(city: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE_URL}/weather",
            params={"q": city, **http_params}
        )
        response.raise_for_status()
        data = response.json()

    return {
        "temperature": data["main"]["temp"],
        "conditions": data["weather"][0]["description"],
        "humidity": data["main"]["humidity"],
        "wind_speed": data["wind"]["speed"],
        "timestamp": datetime.now().isoformat()
    }

# サーバの準備
app = Server("weather-server")

# 利用可能な天気リソース一覧の取得
@app.list_resources()
async def list_resources() -> list[Resource]:
    uri = AnyUrl(f"weather://{DEFAULT_CITY}/current")
    return [
        Resource(
            uri=uri,
            name=f"Current weather in {DEFAULT_CITY}",
            mimeType="application/json",
            description="Real-time weather data"
        )
    ]

# 特定の天気リソースの取得
@app.read_resource()
async def read_resource(uri: AnyUrl) -> str:
    city = DEFAULT_CITY
    if str(uri).startswith("weather://") and str(uri).endswith("/current"):
        city = str(uri).split("/")[-2]
    else:
        raise ValueError(f"Unknown resource: {uri}")

    try:
        weather_data = await fetch_weather(city)
        return json.dumps(weather_data, indent=2)
    except httpx.HTTPError as e:
        raise RuntimeError(f"Weather API error: {str(e)}")

# 利用可能な天気ツール一覧の取得
@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_forecast",
            description="Get weather forecast for a city",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name"
                    },
                    "days": {
                        "type": "number",
                        "description": "Number of days (1-5)",
                        "minimum": 1,
                        "maximum": 5
                    }
                },
                "required": ["city"]
            }
        )
    ]

# 天気ツールの呼び出し
@app.call_tool()
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    if name != "get_forecast":
        raise ValueError(f"Unknown tool: {name}")

    if not isinstance(arguments, dict) or "city" not in arguments:
        raise ValueError("Invalid forecast arguments")

    city = arguments["city"]
    days = min(int(arguments.get("days", 3)), 5)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE_URL}/{FORECAST_ENDPOINT}",
                params={
                    "q": city,
                    "cnt": days * 8,  # API returns 3-hour intervals
                    **http_params,
                }
            )
            response.raise_for_status()
            data = response.json()

        forecasts = []
        for i in range(0, len(data["list"]), 8):
            day_data = data["list"][i]
            forecasts.append({
                "date": day_data["dt_txt"].split()[0],
                "temperature": day_data["main"]["temp"],
                "conditions": day_data["weather"][0]["description"]
            })

        return [
            TextContent(
                type="text",
                text=json.dumps(forecasts, indent=2)
            )
        ]
    except requests.HTTPError as e:
        logger.error(f"Weather API error: {str(e)}")
        raise RuntimeError(f"Weather API error: {str(e)}")

# メイン
async def main():
    # イベントループの問題を回避するためにここにインポート
    from mcp.server.stdio import stdio_server

    # サーバの実行
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )