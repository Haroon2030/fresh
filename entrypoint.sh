#!/bin/sh
set -e

echo "[deploy] Running database migrations..."
python manage.py migrate --noinput
echo "[deploy] Migrations complete."

mkdir -p "${MEDIA_ROOT:-/data/media}"
python manage.py ensure_ops_schema
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
