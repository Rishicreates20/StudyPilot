"""Wakes the worker after a request that queued a job (ADR-052).

Request code calls ``app.core.job_signals.note_job_queued`` when it inserts a job. This middleware
watches for that and, when the response starts, asks the configured ``JobWake`` for a run. The
response starts only after the route has returned, so the transaction that stored the job has
committed and a worker woken now will find it. A failed response (status 400 or more) rolled its
transaction back and wakes nothing.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.job_signals import watch_job_signals
from app.jobs.wake import JobWake


class JobWakeMiddleware:
    def __init__(self, app: ASGIApp, wake: JobWake) -> None:
        self.app = app
        self.wake = wake

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with watch_job_signals() as queued:

            async def send_after_waking(message: Message) -> None:
                if message["type"] == "http.response.start" and queued and message["status"] < 400:
                    queued.clear()  # once per request, however many jobs it queued
                    await self.wake.wake()
                await send(message)

            await self.app(scope, receive, send_after_waking)
