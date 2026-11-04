import os 
# pyrefly: ignore [missing-import]
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

#setup 

celery_app = Celery(
    "orbit_tasks",
    broker = REDIS_URL,
    backend=REDIS_URL, #stores reault in redis 
    include= ["src.tasks.research_tasks"] #register tasks
)

#optional config for prod taks

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)