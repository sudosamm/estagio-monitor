#!/bin/sh
set -e
python manage.py migrate --noinput

# Cria o primeiro orientador administrador se ADMIN_NOME estiver definido e ainda não houver nenhum
if [ -n "$ADMIN_NOME" ]; then
  python manage.py criar_orientador "$ADMIN_NOME" --admin --se-nao-houver-admin
fi

exec gunicorn monitor.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-3}" \
  --timeout 60 \
  --access-logfile - \
  --forwarded-allow-ips="*"
