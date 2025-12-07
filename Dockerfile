FROM alpine:3.20

RUN apk add --no-cache curl tar python3 && \
    curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz | \
    tar -xJ -C /usr/local/bin --strip-components=1 --wildcards "*/ffmpeg" "*/ffprobe" && \
    apk del curl tar && \
    python3 -m pip install --no-cache-dir --break-system-packages PyYAML==6.0.2

WORKDIR /app
COPY ./src /
RUN cat /crontab >> /etc/crontabs/root && rm /crontab

VOLUME ["/config", "/storage"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 /app/healthcheck.py || exit 1

CMD ["sh", "-c", "crond -f && python3 /app/nvr.py"]
