"""Register EventBus subscribers — UI, CRM, logs, metrics."""

from __future__ import annotations

from typing import Any

from core.account_logging import account_log
from core.observability.account_metrics import metrics_store
from core.observability.alerts import alert_store
from events.event_bus import event_bus
from events.event_types import EventType, SubscriberChannel


async def _ui_subscriber(account_id: str, event_type: EventType, data: dict[str, Any]) -> None:
    """UI channel: state push is handled by push_state flag; log notable events."""
    if event_type in (
        EventType.QUEUE_OVERFLOW,
        EventType.WORKER_CRASHED,
        EventType.RETRY_EXHAUSTED,
        EventType.HEALTH_ALERT,
    ):
        account_log(account_id, f"UI event {event_type.value}: {data.get('message', '')}", level="info")


async def _crm_subscriber(account_id: str, event_type: EventType, data: dict[str, Any]) -> None:
    if event_type == EventType.MESSAGE_RECEIVED:
        try:
            from services.crm_service import touch_from_message

            uid = data.get("user_id")
            if uid is not None:
                touch_from_message(
                    account_id,
                    int(uid),
                    direction="in",
                    name=data.get("name", ""),
                    username=data.get("username", ""),
                )
        except Exception:
            pass
    elif event_type == EventType.MESSAGE_SENT and data.get("channel") == "dm":
        try:
            from services.crm_service import touch_from_message

            uid = data.get("user_id")
            if uid is not None:
                touch_from_message(
                    account_id,
                    int(uid),
                    direction="out",
                    name=data.get("name", ""),
                    username=data.get("username", ""),
                )
        except Exception:
            pass


async def _logs_subscriber(account_id: str, event_type: EventType, data: dict[str, Any]) -> None:
    level = "info"
    if event_type in (EventType.ACCOUNT_ERROR, EventType.RETRY_EXHAUSTED, EventType.WORKER_CRASHED):
        level = "error"
    elif event_type in (EventType.ACCOUNT_SLEEP, EventType.RETRY_SCHEDULED, EventType.HEALTH_ALERT):
        level = "warning"
    msg = data.get("message") or event_type.value
    account_log(account_id, msg, level=level)


async def _metrics_subscriber(account_id: str, event_type: EventType, data: dict[str, Any]) -> None:
    if event_type == EventType.ACCOUNT_ERROR:
        metrics_store.record_task_fail(account_id, error=str(data.get("error", ""))[:200])
    elif event_type == EventType.RETRY_SCHEDULED:
        metrics_store.record_retry_scheduled(account_id)
    elif event_type == EventType.RETRY_EXHAUSTED:
        metrics_store.record_retry_exhausted(account_id)
    elif event_type == EventType.ACCOUNT_SLEEP:
        metrics_store.record_flood_wait(account_id)
    elif event_type == EventType.WORKER_RESTARTED:
        metrics_store.record_worker_restart(account_id)
    elif event_type == EventType.QUEUE_OVERFLOW:
        metrics_store.record_queue_rejected(account_id)


def register_event_subscribers() -> None:
    event_bus.subscribe(_ui_subscriber, channel=SubscriberChannel.UI)
    event_bus.subscribe(_crm_subscriber, channel=SubscriberChannel.CRM)
    event_bus.subscribe(_logs_subscriber, channel=SubscriberChannel.LOGS)
    event_bus.subscribe(_metrics_subscriber, channel=SubscriberChannel.METRICS)
