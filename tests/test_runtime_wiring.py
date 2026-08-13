from app.config import Settings
from app.domain.jobs import JobType
from app.main import _job_workers, _provider_socket_workers
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


def test_email_notification_worker_is_registered() -> None:
    disabled = _job_workers(
        settings=Settings(_env_file=None),
        session_factory=None,
        jobs=None,
        handlers={},
        health=HealthRegistry(),
    )
    assert all(worker.name != "EmailNotificationWorker" for worker in disabled)

    workers = _job_workers(
        settings=Settings(
            _env_file=None,
            email_notifications_enabled=True,
            email_recipients="owner@example.com",
            resend_api_key="resend-test-key",
            resend_from="Decision Lab <alerts@example.com>",
        ),
        session_factory=None,
        jobs=None,
        handlers={},
        health=HealthRegistry(),
    )

    email_worker = next(worker for worker in workers if worker.name == "EmailNotificationWorker")
    assert email_worker.name == "EmailNotificationWorker"
    assert JobType.SEND_DECISION_EMAIL.value == "SEND_DECISION_EMAIL"
