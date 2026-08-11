import uvicorn

from app.runtime.health import HealthRegistry


class WebServerWorker:
    name = "WebServer"

    def __init__(
        self,
        app,
        *,
        host: str,
        port: int,
        log_level: str,
        health: HealthRegistry,
    ) -> None:
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=port,
                log_level=log_level.lower(),
                access_log=False,
            )
        )
        self._health = health
        self._server.install_signal_handlers = lambda: None

    async def start(self) -> None:
        return None

    async def run(self) -> None:
        await self._server.serve()

    async def stop(self) -> None:
        self._server.should_exit = True

    async def health(self) -> dict:
        return await self._health.worker(self.name)
