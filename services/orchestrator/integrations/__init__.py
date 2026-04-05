"""
Samantha OS — Integration Plugin System
All integrations inherit from BaseIntegration and register themselves.
Each integration is fully optional — disabled by default, enabled via config/env.
"""

from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("samantha.integrations")


class IntegrationStatus(Enum):
    DISABLED = "disabled"
    CONFIGURED = "configured"
    AUTHENTICATED = "authenticated"
    ERROR = "error"


@dataclass
class IntegrationAction:
    """An action that an integration can perform."""
    name: str                          # e.g. "send_email"
    description: str                   # e.g. "Send an email to someone"
    keywords: list[str]                # trigger words: ["email", "send", "mail", "write to"]
    parameters: list[str] = field(default_factory=list)  # ["to", "subject", "body"]
    examples: list[str] = field(default_factory=list)    # "Send an email to John about the meeting"


class BaseIntegration(ABC):
    """Base class for all Samantha integrations."""

    name: str = "base"
    display_name: str = "Base Integration"
    description: str = ""
    icon: str = ""
    requires_auth: bool = False

    def __init__(self):
        self.status = IntegrationStatus.DISABLED
        self._actions: list[IntegrationAction] = []

    @abstractmethod
    async def initialize(self, config: dict) -> bool:
        """Set up the integration with config. Return True if successful."""
        ...

    @abstractmethod
    async def execute(self, action_name: str, params: dict) -> dict:
        """Execute a named action with parameters. Returns result dict."""
        ...

    @abstractmethod
    def get_actions(self) -> list[IntegrationAction]:
        """Return list of available actions."""
        ...

    async def get_proactive_updates(self) -> list[dict] | None:
        """Check for proactive notifications (new emails, upcoming meetings, etc.)
        Return list of notification dicts or None."""
        return None

    def get_context_for_llm(self) -> str | None:
        """Return context string to inject into LLM system prompt.
        E.g. upcoming calendar events, unread email count."""
        return None

    async def shutdown(self):
        """Clean up resources."""
        pass


class IntegrationRegistry:
    """Central registry for all integrations."""

    def __init__(self):
        self._integrations: dict[str, BaseIntegration] = {}
        self._enabled: set[str] = set()

    def register(self, integration: BaseIntegration):
        self._integrations[integration.name] = integration
        logger.info(f"Registered integration: {integration.display_name}")

    async def enable(self, name: str, config: dict) -> bool:
        if name not in self._integrations:
            logger.warning(f"Integration not found: {name}")
            return False

        integration = self._integrations[name]
        try:
            ok = await integration.initialize(config)
            if ok:
                integration.status = IntegrationStatus.AUTHENTICATED if integration.requires_auth else IntegrationStatus.CONFIGURED
                self._enabled.add(name)
                logger.info(f"✅ Enabled: {integration.display_name}")
                return True
            else:
                integration.status = IntegrationStatus.ERROR
                return False
        except Exception as e:
            logger.error(f"Failed to enable {name}: {e}")
            integration.status = IntegrationStatus.ERROR
            return False

    def get(self, name: str) -> BaseIntegration | None:
        return self._integrations.get(name)

    def get_enabled(self) -> list[BaseIntegration]:
        return [self._integrations[n] for n in self._enabled if n in self._integrations]

    def get_all_actions(self) -> list[tuple[str, IntegrationAction]]:
        """Return all actions from all enabled integrations."""
        actions = []
        for name in self._enabled:
            intg = self._integrations.get(name)
            if intg:
                for action in intg.get_actions():
                    actions.append((name, action))
        return actions

    def get_context_blocks(self) -> list[str]:
        """Collect context from all enabled integrations for LLM injection."""
        blocks = []
        for intg in self.get_enabled():
            ctx = intg.get_context_for_llm()
            if ctx:
                blocks.append(ctx)
        return blocks

    async def check_proactive(self) -> list[dict]:
        """Poll all integrations for proactive notifications."""
        notifications = []
        for intg in self.get_enabled():
            try:
                updates = await intg.get_proactive_updates()
                if updates:
                    notifications.extend(updates)
            except Exception as e:
                logger.warning(f"Proactive check failed for {intg.name}: {e}")
        return notifications

    async def shutdown_all(self):
        for intg in self._integrations.values():
            await intg.shutdown()

    def status_summary(self) -> dict:
        return {
            name: {
                "display_name": intg.display_name,
                "status": intg.status.value,
                "enabled": name in self._enabled,
            }
            for name, intg in self._integrations.items()
        }
