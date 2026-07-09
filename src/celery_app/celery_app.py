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

# Розклад для Celery Beat
celery_app.conf.beat_schedule = {
    "delete-expired-tokens-every-hour": {
        "task": "src.tasks.accounts.delete_expired_tokens",
        "schedule": crontab(minute=0, hour="*"),  # Кожну годину
    },
}

celery_app.conf.timezone = "UTC"
