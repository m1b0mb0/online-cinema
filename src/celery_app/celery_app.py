from celery import Celery
from celery.schedules import crontab

from src.config.dependencies import get_settings

settings = get_settings()

celery_app = Celery(
    "online_cinema",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_BROKER_URL,
    include=["src.tasks.accounts"],
)

# Celery Beat schedule.
celery_app.conf.beat_schedule = {
    "delete-expired-tokens-every-hour": {
        "task": "src.tasks.accounts.delete_expired_tokens",
        "schedule": crontab(minute=0, hour="*"),
    },
}

celery_app.conf.timezone = "UTC"
celery_app.conf.broker_connection_retry_on_startup = True
