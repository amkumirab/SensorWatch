FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --no-cache-dir ".[postgres]"

RUN mkdir -p /app/data && useradd --create-home --uid 10001 sensorwatch \
    && chown -R sensorwatch:sensorwatch /app
USER sensorwatch

EXPOSE 8000

CMD ["sh", "-c", "sensorwatch migrate && exec uvicorn sensorwatch.api:app --host 0.0.0.0 --port 8000"]
