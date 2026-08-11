from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TimedPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    payload: dict[str, Any] | list[Any]
    request_started_at: datetime
    received_at: datetime
