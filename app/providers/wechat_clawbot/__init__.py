"""Direct integration with the official Tencent WeChat ClawBot channel.

Implements the documented iLink bot HTTP API subset used by the official
``@tencent-weixin/openclaw-weixin`` channel, without an OpenClaw runtime.
"""

from app.providers.wechat_clawbot.client import WeChatClawBotClient
from app.providers.wechat_clawbot.service import WeChatClawBotService
from app.providers.wechat_clawbot.storage import WeChatClawBotStore

__all__ = ["WeChatClawBotClient", "WeChatClawBotService", "WeChatClawBotStore"]
