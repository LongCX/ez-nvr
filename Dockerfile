FROM python:3.12-slim

RUN apt update && apt install -y \
    cron \
    build-essential \
    gcc \
    g++ \
    make \
    python3-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY ./requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY ./src /

RUN cat /crontab >> /etc/crontab && rm /crontab

VOLUME ["/config", "/storage"]

CMD cron && python /app/nvr.py

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 CMD python /app/healthcheck.py
