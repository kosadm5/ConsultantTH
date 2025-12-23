# backend/tasks.py
from celery import Celery
import os
import subprocess

REDIS = os.getenv("REDIS_URL", "redis://redis:6379/0")
app = Celery("tasks", broker=REDIS)

@app.task
def run_scrape():
    subprocess.run(["python", "/app/scraper/rg_scraper.py"], check=True)

@app.task
def run_process():
    subprocess.run(["python", "/app/processor/process_doc.py"], check=True)

@app.task
def run_index():
    subprocess.run(["python", "/app/indexer/index_to_qdrant.py"], check=True)

@app.on_after_configure.connect
def setup_periodic(sender, **kwargs):
    # ежедневный запуск
    sender.add_periodic_task(24*3600, run_scrape.s(), name="daily scrape")
    sender.add_periodic_task(24*3600 + 300, run_process.s(), name="daily process")
    sender.add_periodic_task(24*3600 + 600, run_index.s(), name="daily index")
