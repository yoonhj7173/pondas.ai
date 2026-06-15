# pondas.ai 백엔드 — FastAPI(web) + Celery(worker) 공용 이미지.
# web = start-web.sh(마이그레이션+시드+uvicorn), worker = start-worker.sh(celery).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 일부 패키지 휠 미제공 대비 빌드 도구(설치 후 정리).
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x start-web.sh start-worker.sh

EXPOSE 8000
# 기본 = web. worker 서비스는 Railway에서 start command를 ./start-worker.sh 로 오버라이드.
CMD ["./start-web.sh"]
