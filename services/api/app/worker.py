"""The background worker process.

Run it next to the API (it reads the same ``.env``)::

    uv run python -m app.worker

It claims queued jobs from PostgreSQL (roadmap generation today), runs them, and keeps going until
interrupted; Ctrl+C lets a job that is running finish first. On Windows it needs a selector event
loop, which ``main`` selects, because psycopg's async mode rejects the default proactor loop.
"""

import asyncio
import signal
import sys
from types import FrameType

from app.core.config import EX_CONFIG, Settings, load_settings_or_exit
from app.core.logging import configure_logging
from app.jobs.environment import worker_environment
from app.jobs.worker import Worker


async def run_worker(settings: Settings, stop: asyncio.Event) -> None:
    async with worker_environment(settings) as env:
        await Worker(env).run(stop)


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(stop.set)

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):  # SIGBREAK exists on Windows only
        number = getattr(signal, name, None)
        if number is not None:
            signal.signal(number, request_stop)


async def _main(settings: Settings) -> None:
    stop = asyncio.Event()
    _install_signal_handlers(asyncio.get_running_loop(), stop)
    await run_worker(settings, stop)


def main() -> None:
    settings = load_settings_or_exit()
    configure_logging(settings.log_level, json_logs=settings.json_logs)
    if settings.database_url is None:
        sys.stderr.write("DATABASE_URL must be set for the worker.\n")
        raise SystemExit(EX_CONFIG)
    asyncio.run(_main(settings), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    main()
