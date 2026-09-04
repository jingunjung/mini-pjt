# run.ps1 - 국내 여행 플래너 실행 스크립트 (Windows PowerShell)
#
# 사용법:
#   .\run.ps1 setup    가상환경 생성 + 패키지 설치
#   .\run.ps1 data     TourAPI 데이터 수집 + Chroma 벡터DB 빌드
#   .\run.ps1 start    CLI 실행 (기본 동작, 인자 없이 실행해도 동일)
#   .\run.ps1 api      RAG QA API 서버 실행 (POST /query, http://localhost:8000)
#   .\run.ps1 eval     평가셋(test_queries.csv) 실행
#
# 최초 1회는 순서대로 .\run.ps1 setup / .\run.ps1 data / .\run.ps1 start 를 실행한다.

param(
    [ValidateSet("setup", "data", "start", "api", "eval")]
    [string]$Command = "start"
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

function Ensure-Venv {
    if (-not (Test-Path $VenvPython)) {
        Write-Host "가상환경이 없습니다. 먼저 '.\run.ps1 setup'을 실행하세요." -ForegroundColor Yellow
        exit 1
    }
}

switch ($Command) {
    "setup" {
        if (-not (Test-Path (Join-Path $RepoRoot ".venv"))) {
            Write-Host "가상환경 생성 중..."
            python -m venv (Join-Path $RepoRoot ".venv")
        }
        Write-Host "패키지 설치 중..."
        & $VenvPython -m pip install --upgrade pip
        & $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")
        Write-Host "완료. 다음 단계: .\run.ps1 data" -ForegroundColor Green
    }
    "data" {
        Ensure-Venv
        Write-Host "TourAPI 데이터 수집 중 (TOURAPI_KEY 없으면 자동 스킵)..."
        & $VenvPython (Join-Path $RepoRoot "data\scripts\fetch_tourapi.py")
        Write-Host "Chroma 벡터DB 빌드 중..."
        & $VenvPython (Join-Path $RepoRoot "data\build_chroma.py")
        Write-Host "완료. 다음 단계: .\run.ps1 start" -ForegroundColor Green
    }
    "start" {
        Ensure-Venv
        & $VenvPython (Join-Path $RepoRoot "src\main.py")
    }
    "api" {
        Ensure-Venv
        & $VenvPython -m uvicorn api:app --app-dir (Join-Path $RepoRoot "src") --host 0.0.0.0 --port 8000
    }
    "eval" {
        Ensure-Venv
        & $VenvPython (Join-Path $RepoRoot "evaluation\run_eval.py")
    }
}
