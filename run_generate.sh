#!/bin/bash
# AI 초안 자동 생성 스크립트 (맥북에서 Claude Code로 실행)
# launchd가 매일 정해진 시간에 실행하며, 직접 실행해도 됩니다: ./run_generate.sh

cd "$(dirname "$0")"

# launchd는 PATH가 좁아서 Claude Code 위치를 못 찾을 수 있음 → 흔한 경로 보강
export PATH="$HOME/.claude/local:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ ! -d ".venv" ]; then
  echo "가상환경이 없습니다. MACBOOK_SERVER.md의 2단계를 먼저 진행하세요."
  exit 1
fi

mkdir -p logs
echo "=== $(date '+%Y-%m-%d %H:%M:%S') AI 초안 생성 시작 ===" >> logs/generate.log
.venv/bin/python main.py --generate >> logs/generate.log 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') 종료 ===" >> logs/generate.log
