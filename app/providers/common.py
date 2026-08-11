import ssl
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TimedPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    payload: dict[str, Any] | list[Any]
    request_started_at: datetime
    received_at: datetime


def create_system_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()
