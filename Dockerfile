FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 1000 devpilot \
    && chown -R devpilot:devpilot /app

USER devpilot

EXPOSE 8080

CMD ["python", "-m", "devpilot.server"]
