import os

from celery import Celery
from celery.schedules import crontab

app = Celery("magnus-timekeeping", include=["app.tasks.dashboard_tasks"])
app.conf.update(
    broker_url=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
    result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/0"),
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "refresh-pending-device-dashboard-snapshot": {
            "task": "app.tasks.dashboard_tasks.refresh_pending_device_snapshot",
            "schedule": crontab(minute=os.getenv("CELERY_BEAT_CRON_MINUTE", "*/5")),
        },
        "refresh-recent-attendance-dashboard-snapshots": {
            "task": "app.tasks.dashboard_tasks.refresh_recent_attendance_snapshot",
            "schedule": crontab(minute=os.getenv("CELERY_BEAT_CRON_MINUTE", "*/5")),
        },
        "refresh-leave-dashboard-snapshots": {
            "task": "app.tasks.dashboard_tasks.refresh_leave_dashboard_snapshots",
            "schedule": crontab(minute=os.getenv("CELERY_BEAT_CRON_MINUTE", "*/5")),
        },
    },
)