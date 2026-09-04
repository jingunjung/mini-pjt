# Dockerfile - 클린 환경 재현용.
# 이미지에는 자격증명(.env)을 포함하지 않는다. 실행 시 --env-file .env 로 주입하거나
# docker-compose의 env_file로 넘긴다.
#
# 빌드:  docker build -t travel-planner .
# 실행:  docker run --rm -it --env-file .env travel-planner
# 평가:  docker run --rm --env-file .env travel-planner python evaluation/run_eval.py
# RAG QA API(POST /query):
#        docker run --rm --env-file .env -p 8000:8000 travel-planner \
#          python -m uvicorn api:app --app-dir src --host 0.0.0.0 --port 8000
# 벡터DB 재생성(문서를 고쳤을 때만):
#        docker run --rm --env-file .env travel-planner python data/build_chroma.py

FROM python:3.12-slim

WORKDIR /app

# 시스템 패키지: sqlite3(체크포인터), git(일부 패키지 빌드용)는 slim 이미지에 없을 수 있어 추가
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드만 복사 (.dockerignore로 reference/, .venv, 캐시 등 제외)
COPY data/ ./data/
COPY src/ ./src/
COPY evaluation/ ./evaluation/
COPY SERVICE.md CLAUDE.md ./

# data/chroma_travel/ 은 볼륨으로 유지하고 싶다면 실행 시 -v 로 마운트한다.
VOLUME ["/app/data/chroma_travel"]

# RAG QA API(src/api.py)를 띄울 때 쓰는 포트. 기본 CMD(CLI)는 이 포트를 쓰지 않는다 -
# API로 실행하려면 위 주석의 docker run 커맨드로 CMD를 덮어쓰고 -p로 포트를 매핑한다.
EXPOSE 8000

# 컨테이너 첫 실행 시 벡터DB가 비어 있으면 빌드부터 하고 CLI를 띄운다.
CMD ["sh", "-c", "[ -d data/chroma_travel ] && [ \"$(ls -A data/chroma_travel 2>/dev/null)\" ] || python data/build_chroma.py; python src/main.py"]
