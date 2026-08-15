"""Queue task definitions — one account, one queue, no cross-account tasks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    GROUP_POST = "group_post"
    DM_SEND = "dm_send"
    DM_SEND_MEDIA = "dm_send_media"
    DM_SEND_LOCATION = "dm_send_location"
    AI_AUTO_REPLY = "ai_auto_reply"
    JOIN_GROUP = "join_group"
    RUN_CYCLE = "run_cycle"
    RETRY = "retry"


class TaskPriority(int, Enum):
    """Lower value = dequeued first. Retry beats normal work."""

    RETRY = 0
    HIGH = 1  # DM replies
    NORMAL = 2  # group post, join
    LOW = 3  # full cycle orchestration


def priority_for_task_type(task_type: TaskType, *, is_retry: bool = False) -> TaskPriority:
    if is_retry or task_type == TaskType.RETRY:
        return TaskPriority.RETRY
    if task_type in (
        TaskType.DM_SEND,
        TaskType.DM_SEND_MEDIA,
        TaskType.DM_SEND_LOCATION,
        TaskType.AI_AUTO_REPLY,
    ):
        return TaskPriority.HIGH
    if task_type == TaskType.RUN_CYCLE:
        return TaskPriority.LOW
    return TaskPriority.NORMAL


@dataclass
class QueueTask:
    account_id: str
    task_type: TaskType
    payload: dict[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    retry_count: int = 0
    wait_result: bool = False
    priority: TaskPriority = field(default=TaskPriority.NORMAL)

    def __post_init__(self) -> None:
        if self.priority == TaskPriority.NORMAL and self.task_type:
            self.priority = priority_for_task_type(
                self.task_type,
                is_retry=self.retry_count > 0 or self.task_type == TaskType.RETRY,
            )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "account_id": self.account_id,
            "task_type": self.task_type.value,
            "retry_count": self.retry_count,
            "priority": self.priority.name,
            "payload_keys": list(self.payload.keys()),
        }
