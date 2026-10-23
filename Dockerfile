FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir '.[exporter]'

USER 10001:10001
EXPOSE 9109
ENTRYPOINT ["aiotlse2109-exporter", "--listen-address", "0.0.0.0"]
