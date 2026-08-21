#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py ensure_admin

# gthread: I/O (PDF/WhatsApp) لا يجمّد كل العمال
# keep-alive قصير يمنع WORKER TIMEOUT على اتصالات المتصفح المعلّقة (no URI read)
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --worker-class "${GUNICORN_WORKER_CLASS:-gthread}" \
  --workers "${WEB_CONCURRENCY:-3}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-90}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
  --keep-alive "${GUNICORN_KEEPALIVE:-5}" \
  --access-logfile "-" \
  --error-logfile "-"
