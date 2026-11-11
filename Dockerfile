FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    TZ=America/Fortaleza

WORKDIR /app
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app:app /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .
RUN SECRET_KEY=build python manage.py collectstatic --noinput

USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/saude/').status==200 else 1)"

ENTRYPOINT ["sh", "/app/entrypoint.sh"]
