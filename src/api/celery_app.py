import os

from dotenv import load_dotenv

# Ensure DATABASE_URL and REDIS_URL are available before task modules import
# persistence and Celery configuration.
load_dotenv()

from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "orbit_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["src.tasks.research_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)
