"""
Aether OCR — Celery Application Instance
=========================================
Start workers:
  celery -A celery_app worker -Q ocr -c 4 --loglevel=info
  celery -A celery_app worker -Q llm -c 2 --loglevel=info
  celery -A celery_app worker -Q export -c 2 --loglevel=info

Monitor:
  celery -A celery_app flower --port=5555
"""

from celery import Celery

def make_celery(app=None):
    broker = "redis://localhost:6379/0"
    backend = "redis://localhost:6379/1"

    celery = Celery(
        "aether_ocr",
        broker=broker,
        backend=backend,
        include=["tasks"]
    )

    celery.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="Asia/Kolkata",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,           # Don't ack until task is done (safe on crash)
        worker_prefetch_multiplier=1,  # One task at a time per worker (memory safety)
        task_routes={
            "tasks.run_ocr_celery":        {"queue": "ocr"},
            "tasks.classify_document":     {"queue": "llm"},
            "tasks.structure_with_llm":    {"queue": "llm"},
            "tasks.build_master_case":     {"queue": "llm"},
            "tasks.generate_draft":        {"queue": "export"},
            "tasks.export_excel":          {"queue": "export"},
        },
        # Prevent memory leaks on long-running workers
        worker_max_tasks_per_child=50,
    )

    if app:
        celery.conf.update(app.config)
        class ContextTask(celery.Task):
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)
        celery.Task = ContextTask

    return celery


celery_app = make_celery()
