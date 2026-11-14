"""Celery: Redis as the broker, results stored in Postgres by the tasks themselves.

Tasks are acknowledged only after they finish (acks_late) and re-queued if a
worker dies mid-task, so every task is written to be safe to run twice.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init, worker_ready

from hartriage.core.config import get_settings
from hartriage.core.logging import configure

settings = get_settings()

app = Celery("hartriage", broker=settings.redis_url, include=["hartriage.worker.tasks"])
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    task_always_eager=settings.celery_eager,
    task_eager_propagates=True,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
    beat_schedule={
        "retention-sweep": {"task": "hartriage.retention_sweep", "schedule": crontab(minute=17)},
    },
)


@worker_process_init.connect
def _init_process(**_: object) -> None:
    configure(settings.log_level, settings.log_json)


@worker_ready.connect
def _metrics_server(**_: object) -> None:
    """Serve /metrics for all worker processes (prometheus multiprocess mode)."""
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not directory:
        return
    from prometheus_client import CollectorRegistry, start_http_server
    from prometheus_client.multiprocess import MultiProcessCollector

    registry = CollectorRegistry()
    MultiProcessCollector(registry, path=directory)  # type: ignore[no-untyped-call]
    start_http_server(
        int(os.environ.get("HARTRIAGE_WORKER_METRICS_PORT", "9100")), registry=registry
    )
