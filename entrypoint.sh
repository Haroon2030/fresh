#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py ensure_admin

# keep-alive=0 يغلق الاتصال بعد كل رد — يمنع لوب WORKER TIMEOUT / SIGKILL
# من اتصالات المتصفح المعلّقة (no URI read)
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --worker-class sync \
  --workers "${WEB_CONCURRENCY:-3}" \
  --timeout "${GUNICORN_TIMEOUT:-90}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-20}" \
  --keep-alive 0 \
  --access-logfile "-" \
  --error-logfile "-"
