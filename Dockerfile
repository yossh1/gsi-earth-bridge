FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --chown=10001:10001 app.py /app/app.py
RUN mkdir /cache && chown 10001:10001 /cache

USER 10001:10001
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3)"]

CMD ["python", "-B", "app.py", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]
