from datetime import datetime, timedelta, timezone

from croniter import croniter


def compute_next_run(
    schedule_type: str, schedule_value: str, base: datetime | None = None
) -> str | None:
    """Compute the next run time for a scheduled task.

    Returns an ISO 8601 string, or ``None`` for unknown schedule types.
    """
    if base is None:
        base = datetime.now(timezone.utc)

    if schedule_type == "cron":
        return croniter(schedule_value, base).get_next(datetime).isoformat()
    if schedule_type == "interval":
        return (base + timedelta(milliseconds=int(schedule_value))).isoformat()
    return schedule_value
