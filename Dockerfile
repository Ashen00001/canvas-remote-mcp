FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # OAuth state (Claude's client registration + issued tokens) lives here.
    # Must be a persistent volume — if it's wiped, the connector needs a reconnect.
    FASTMCP_HOME=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV PORT=8000
EXPOSE 8000
VOLUME ["/data"]

CMD ["python", "server.py"]
