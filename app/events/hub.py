import asyncio


class EventHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._dropped_events = 0

    async def publish(self, topic: str, payload: dict) -> None:
        event = {"topic": topic, "payload": payload}
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._dropped_events += 1
                continue

    @property
    def dropped_events(self) -> int:
        return self._dropped_events

    def subscribe(self, *, maxsize: int = 100) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)
