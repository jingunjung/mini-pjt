#!/usr/bin/env bash
# run.sh - 국내 여행 플래너 실행 스크립트 (bash / macOS / Linux / Git Bash)
#
# 사용법:
#   ./run.sh setup    가상환경 생성 + 패키지 설치
#   ./run.sh data     TourAPI 데이터 수집 + Chroma 벡터DB 빌드
#   ./run.sh start    CLI 실행 (기본 동작, 인자 없이 실행해도 동일)
#   ./run.sh eval     평가셋(test_queries.csv) 실행
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$REPO_ROOT/.venv/bin/python"
# Windows Git Bash의 venv는 Scripts/에 생긴다
[ -f "$VENV_PY" ] || VENV_PY="$REPO_ROOT/.venv/Scripts/python.exe"

ensure_venv() {
    if [ ! -f "$VENV_PY" ]; then
        echo "가상환경이 없습니다. 먼저 './run.sh setup'을 실행하세요." >&2
        exit 1
    fi
}

COMMAND="${1:-start}"

case "$COMMAND" in
    setup)
        if [ ! -d "$REPO_ROOT/.venv" ]; then
            echo "가상환경 생성 중..."
            python3 -m venv "$REPO_ROOT/.venv" || python -m venv "$REPO_ROOT/.venv"
        fi
        echo "패키지 설치 중..."
        "$VENV_PY" -m pip install --upgrade pip
        "$VENV_PY" -m pip install -r "$REPO_ROOT/requirements.txt"
        echo "완료. 다음 단계: ./run.sh data"
        ;;
    data)
        ensure_venv
        echo "TourAPI 데이터 수집 중 (TOURAPI_KEY 없으면 자동 스킵)..."
        "$VENV_PY" "$REPO_ROOT/data/scripts/fetch_tourapi.py"
        echo "Chroma 벡터DB 빌드 중..."
        "$VENV_PY" "$REPO_ROOT/data/build_chroma.py"
        echo "완료. 다음 단계: ./run.sh start"
        ;;
    start)
        ensure_venv
        "$VENV_PY" "$REPO_ROOT/src/main.py"
        ;;
    eval)
        ensure_venv
        "$VENV_PY" "$REPO_ROOT/evaluation/run_eval.py"
        ;;
    *)
        echo "사용법: $0 {setup|data|start|eval}" >&2
        exit 1
        ;;
esac
