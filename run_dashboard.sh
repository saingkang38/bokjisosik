#!/bin/bash
# 복지소식 대시보드 실행 스크립트 (맥북 서버용)
# 사용법: ./run_dashboard.sh

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "가상환경이 없습니다. 먼저 아래를 실행하세요:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [ ! -f ".env" ]; then
  echo ".env 파일이 없습니다. .env.example을 복사해서 값을 채워주세요:"
  echo "  cp .env.example .env"
  exit 1
fi

exec .venv/bin/uvicorn src.web_app:app --host 0.0.0.0 --port 8000
