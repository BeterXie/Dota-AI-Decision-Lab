"""QQ Bot channel backed by the harness-installed official QQ SDK.

The Python runtime owns decisions and data queries. A small Node bridge
(``tools/qq_bot_bridge.mjs``) loads ``@tencent-connect/qqbot-nodejs`` from the
harness profile and exposes a loopback HTTP API for sending messages and
polling inbound events. Runtime delivery is user-scoped through Notification
Center; the legacy service remains importable for focused transport tests.
"""

from app.providers.qq_bot.bridge_client import QQBridgeClient
from app.providers.qq_bot.bridge_runner import QQBotBridgeRunner
from app.providers.qq_bot.storage import QQBotStore
from app.providers.qq_bot.user_service import UserScopedQQBotService as QQBotService

__all__ = ["QQBotService", "QQBotStore", "QQBridgeClient", "QQBotBridgeRunner"]
