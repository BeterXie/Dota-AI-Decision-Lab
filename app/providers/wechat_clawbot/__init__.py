"""Direct integration with the official Tencent WeChat ClawBot channel.

Implements the documented iLink bot HTTP API subset used by the official
``@tencent-weixin/openclaw-weixin`` channel, without an OpenClaw runtime.
Runtime delivery is user-scoped through verified Notification Center bindings.
"""

from app.providers.wechat_clawbot.client import WeChatClawBotClient
from app.providers.wechat_clawbot.qr import WeChatUserQrBindingService
from app.providers.wechat_clawbot.storage import WeChatClawBotStore
from app.providers.wechat_clawbot.user_service import (
    UserScopedWeChatClawBotService as WeChatClawBotService,
)

__all__ = [
    "WeChatClawBotClient",
    "WeChatClawBotService",
    "WeChatClawBotStore",
    "WeChatUserQrBindingService",
]
