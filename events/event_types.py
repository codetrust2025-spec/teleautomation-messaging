"""Domain events for decoupled worker → CRM/UI/logs."""

from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    MESSAGE_SENT = "MESSAGE_SENT"
    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
    ACCOUNT_SLEEP = "ACCOUNT_SLEEP"
    ACCOUNT_ERROR = "ACCOUNT_ERROR"
    CALL_INITIATED = "CALL_INITIATED"
    ACCOUNT_STATE = "ACCOUNT_STATE"
    QUEUE_UPDATE = "QUEUE_UPDATE"
    QUEUE_OVERFLOW = "QUEUE_OVERFLOW"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    WORKER_CRASHED = "WORKER_CRASHED"
    WORKER_RESTARTED = "WORKER_RESTARTED"
    HEALTH_ALERT = "HEALTH_ALERT"
    METRICS_UPDATE = "METRICS_UPDATE"
    STATS_RESET = "STATS_RESET"
    CYCLE_COMPLETE = "CYCLE_COMPLETE"


class SubscriberChannel(str, Enum):
    """Logical subscriber groups — handlers run in parallel per publish."""

    UI = "ui"
    CRM = "crm"
    LOGS = "logs"
    METRICS = "metrics"
