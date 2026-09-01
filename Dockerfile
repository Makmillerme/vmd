# VMD Extractor — production image
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Kyiv \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# tzdata for Europe/Kyiv in cron/scheduler
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY run.py run_auto.py ./
COPY vmd_extractor/ ./vmd_extractor/
COPY deploy/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && mkdir -p vmd_extractor/data/db vmd_extractor/data/files \
        vmd_extractor/data/pdf vmd_extractor/data/extract_data \
        vmd_extractor/data/temp_extracted vmd_extractor/data/brief \
        vmd_logs

VOLUME ["/app/vmd_extractor/data", "/app/vmd_logs"]

ENTRYPOINT ["/entrypoint.sh"]
CMD ["daemon"]
