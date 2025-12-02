#!/usr/bin/env sh
celery -A fm_app.workers.worker worker --loglevel=INFO --soft-time-limit=1800 --time-limit=2400 --pool=prefork --concurrency=8
