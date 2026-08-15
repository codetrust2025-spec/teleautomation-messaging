"""Backward-compatible imports — logic lives in join_cycle.py."""

from core.join_cycle import (  # noqa: F401
    can_attempt_new_join,
    clear_join_restriction,
    evaluate_join,
    get_joined_total,
    post_join_delay_seconds,
    record_join_attempt,
    record_join_failure,
    record_join_success,
    record_new_join,
    set_join_restriction,
)
