from app.main import _provider_socket_workers
from app.runtime.health import HealthRegistry


class _Socket:
    async def run(self, *_callbacks) -> None:
        return None

    async def stop(self) -> None:
        return None


async def _callback(*_args) -> None:
    return None


def test_provider_socket_workers_are_registered_before_messages() -> None:
    workers = _provider_socket_workers(
        raybet_socket=_Socket(),
        dltv_socket=_Socket(),
        raybet_publish=_callback,
        raybet_state=_callback,
        dltv_event=_callback,
        dltv_state=_callback,
        health=HealthRegistry(),
    )

    assert [worker.name for worker in workers] == [
        "RayBetSocketWorker",
        "DltvSocketWorker",
    ]
