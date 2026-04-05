"""
Samantha OS — Weather Integration
Uses Open-Meteo API — completely free, no API key needed.
"""

from __future__ import annotations
import logging
from datetime import datetime

import httpx

from integrations import BaseIntegration, IntegrationAction

logger = logging.getLogger("samantha.weather")

WMO_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "rime fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "light snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


class WeatherIntegration(BaseIntegration):
    name = "weather"
    display_name = "Weather (Open-Meteo)"
    description = "Current weather and forecasts — free, no API key"
    icon = "🌤️"
    requires_auth = False

    def __init__(self):
        super().__init__()
        self.latitude: float = 55.87
        self.longitude: float = 12.83
        self.location_name: str = "Landskrona"
        self.timezone: str = "Europe/Stockholm"
        self._cache: dict = {}
        self._cache_time: float = 0

    async def initialize(self, config: dict) -> bool:
        self.latitude = config.get("latitude", self.latitude)
        self.longitude = config.get("longitude", self.longitude)
        self.location_name = config.get("location", self.location_name)
        self.timezone = config.get("timezone", self.timezone)
        return True

    def get_actions(self) -> list[IntegrationAction]:
        return [
            IntegrationAction(
                name="current_weather",
                description="Get current weather conditions",
                keywords=["weather", "temperature", "outside", "rain", "snow", "cold", "hot", "warm"],
                examples=["What's the weather like?", "Is it cold outside?", "Will it rain?"],
            ),
            IntegrationAction(
                name="forecast",
                description="Get weather forecast",
                keywords=["forecast", "weather tomorrow", "this week", "weekend weather"],
                parameters=["days"],
                examples=["What's the forecast for tomorrow?", "Will it rain this weekend?"],
            ),
        ]

    async def execute(self, action_name: str, params: dict) -> dict:
        if action_name == "current_weather":
            return await self._current()
        elif action_name == "forecast":
            return await self._forecast(params.get("days", 3))
        return {"error": f"Unknown action: {action_name}"}

    async def _current(self) -> dict:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://api.open-meteo.com/v1/forecast", params={
                    "latitude": self.latitude, "longitude": self.longitude,
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                    "timezone": self.timezone,
                })
                data = resp.json().get("current", {})
                code = data.get("weather_code", 0)
                return {
                    "location": self.location_name,
                    "temperature": data.get("temperature_2m"),
                    "feels_like": data.get("apparent_temperature"),
                    "humidity": data.get("relative_humidity_2m"),
                    "wind_speed": data.get("wind_speed_10m"),
                    "condition": WMO_CODES.get(code, "unknown"),
                    "unit": "°C",
                }
        except Exception as e:
            return {"error": str(e)}

    async def _forecast(self, days: int = 3) -> dict:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://api.open-meteo.com/v1/forecast", params={
                    "latitude": self.latitude, "longitude": self.longitude,
                    "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
                    "timezone": self.timezone,
                    "forecast_days": min(days, 7),
                })
                daily = resp.json().get("daily", {})
                forecast = []
                dates = daily.get("time", [])
                for i, date in enumerate(dates):
                    code = daily.get("weather_code", [0])[i] if i < len(daily.get("weather_code", [])) else 0
                    forecast.append({
                        "date": date,
                        "high": daily.get("temperature_2m_max", [None])[i],
                        "low": daily.get("temperature_2m_min", [None])[i],
                        "condition": WMO_CODES.get(code, "unknown"),
                        "rain_chance": daily.get("precipitation_probability_max", [None])[i],
                    })
                return {"location": self.location_name, "forecast": forecast, "unit": "°C"}
        except Exception as e:
            return {"error": str(e)}

    async def get_proactive_updates(self) -> list[dict] | None:
        try:
            w = await self._current()
            temp = w.get("temperature")
            cond = w.get("condition", "")
            if temp is not None and ("rain" in cond or "snow" in cond or "thunderstorm" in cond):
                return [{"type": "card", "title": "Weather", "body": f"{cond.title()}, {temp}°C", "integration": self.name}]
        except Exception:
            pass
        return None

    def get_context_for_llm(self) -> str | None:
        return f"You can check weather for {self.location_name} and surroundings."
