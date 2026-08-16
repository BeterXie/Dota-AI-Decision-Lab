import pytest

from app.events.hub import EventHub


@pytest.mark.asyncio
async def test_event_hub_counts_and_exports_queue_drops() -> None:
    exported = 0

    def on_drop() -> None:
        nonlocal exported
        exported += 1

    hub = EventHub(on_drop=on_drop)
    queue = hub.subscribe(maxsize=1)
    await hub.publish("status", {"n": 1})
    await hub.publish("status", {"n": 2})

    assert queue.qsize() == 1
    assert hub.dropped_events == 1
    assert exported == 1
