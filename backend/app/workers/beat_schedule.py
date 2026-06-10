"""Celery beat schedule (placeholder).

Real schedule added when timed tasks (e.g. log archival) are introduced.
"""

celerybeat_schedule: dict = {
    # Example: nightly_log_archive: {
    #     "task": "executions.archive_old_logs",
    #     "schedule": crontab(hour=2, minute=0),
    # },
}
