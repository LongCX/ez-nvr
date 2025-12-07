FROM alpine:3.20

RUN apk add --no-cache curl tar xz && \
    curl -L -o /tmp/ffmpeg.tar.xz \
         https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz && \
    tar -xJf /tmp/ffmpeg.tar.xz -C /usr/local/bin --strip-components=1 \
        --wildcards "ffmpeg-*-static/ffmpeg" "ffmpeg-*-static/ffprobe" && \
    rm /tmp/ffmpeg.tar.xz && \
    apk del curl tar xz && \
    ffmpeg -version && ffprobe -version

RUN apk add --no-cache python3 py3-pip && \
    python3 -m pip install --no-cache-dir PyYAML==6.0.2 && \
    apk del py3-pip && \
    rm -rf /root/.cache /var/cache/apk/*

WORKDIR /app
COPY ./src /
RUN cat /crontab >> /etc/crontabs/root && rm /crontab

VOLUME ["/config", "/storage"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 /app/healthcheck.py || exit 1

CMD ["sh", "-c", "crond -f && python3 /app/nvr.py"]
