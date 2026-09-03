# 국내 여행 플래너 Agent

총 예산과 취향을 입력하면 국내 여행지/맛집/숙소를 추천하고, 출발지가 있으면 왕복 교통비를
먼저 추정해 제외한 뒤 남은 예산을 항목별(숙박/식비/현지교통/관광)로 자동 배분하고, 일자별
일정표를 만들어주는 LangGraph 멀티에이전트 시스템입니다.

SDS 7일 LangChain/LangGraph 교육 과정(`reference/`)에서 배운 RAG, 멀티에이전트(Supervisor),
Tools/MCP, 가드레일, Human-in-the-loop, 장기 기억, 평가/트레이싱을 실제로 조합한 캡스톤
프로젝트입니다. 기획 배경은 [SERVICE.md](SERVICE.md), 아키텍처와 설계 이유는
[CLAUDE.md](CLAUDE.md)를 참고하세요.

## 사용 기술

**LLM & 클라우드**
- AWS Bedrock `ChatBedrockConverse` (`us.anthropic.claude-sonnet-4-6`, `temperature=0` 고정)
- AWS Bedrock `BedrockEmbeddings` (`amazon.titan-embed-text-v2:0`)
- 한국관광공사 TourAPI (`areaBasedList2`, `detailCommon2`) — 실제 공공데이터 소스

**프레임워크 / 라이브러리**
- **LangChain** (`langchain`, `langchain-core`, `langchain-aws`) — `create_agent`, `@tool`,
  `with_structured_output`
- **LangGraph** (`langgraph`, `langgraph-supervisor`, `langgraph-checkpoint-sqlite`) —
  `StateGraph`, `interrupt()`/`Command`, `AsyncSqliteSaver`/`AsyncSqliteStore`
- **MCP** (`mcp` SDK 내장 `mcp.server.fastmcp.FastMCP`, `langchain-mcp-adapters`) — RAG 검색
  도구를 별도 프로세스로 노출
- **Chroma** (`langchain-chroma`) — 벡터DB

**외부 참조**: `reference/day1_practice`~`day7_practice`(SDS 7일 교육 과정 원본 코드)가 구조의
기반입니다 — RAG 파이프라인은 day2, Tools/MCP는 day4, Supervisor 멀티에이전트는 day6,
가드레일/HITL/장기기억/평가는 day5·day7 패턴을 이 프로젝트 도메인에 맞게 적용했습니다.

## 빠른 시작

**Windows (PowerShell)**
```powershell
.\run.ps1 setup   # 가상환경 생성 + 패키지 설치
.\run.ps1 data    # 관광 데이터 수집 + 벡터DB 빌드
.\run.ps1 start   # CLI 실행
```

**macOS / Linux / Git Bash**
```bash
./run.sh setup
./run.sh data
./run.sh start
```

**Docker**
```bash
docker build -t travel-planner .
docker run --rm -it --env-file .env travel-planner
```

## 사전 준비

레포 루트에 `.env` 파일이 필요합니다 (AWS Bedrock 사용):

```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
# 선택: 한국관광공사 TourAPI 실연동을 원할 때만 추가
TOURAPI_KEY=...
```

`TOURAPI_KEY`가 없어도 `data/docs/`에 미리 준비된 제주/부산/강릉 정적 문서로 정상 동작합니다.

## 사용 예시

```
사용자 ID를 입력하세요 (예: guest): guest

저장된 여행 계획: 0건
1) 새 계획 세우기
번호를 선택하세요 (종료하려면 '종료'): 1

어디로 여행 가시나요? (제주/부산/강릉 중 하나 추천): 제주
어디서 출발하시나요? (왕복 교통비 추정에 사용, 모르면 엔터): 서울
여행 기간(일수)을 입력하세요 (1~7): 3
인원수를 입력하세요 (1~10): 1
총 예산(원)을 입력하세요 (0보다 커야 함): 600000
취향 태그를 선택하세요 (쉼표로 여러 개 가능, 없으면 엔터): 맛집중심, 숨은여행지
```

추천(RAG) → 예산 배분 → 일정 생성·검증 순으로 전문 에이전트가 협업해 계획을 만들고
(진행 상황은 몇 단계 중 몇 단계인지 스피너로 표시됩니다), 최종 확정 전 승인(approve) /
수정(modify) / 거절(reject) 중 하나를 선택하는 확인 단계를 거칩니다. 승인한 계획은 장기
기억에 저장되어, 다음에 프로그램을 실행하고 같은 사용자 ID로 로그인하면 시작 메뉴에서
"저장된 계획 보기"로 다시 꺼내볼 수 있습니다. 어느 입력창에서든 `종료`를 입력하면 즉시
안전하게 끝낼 수 있습니다.

## 평가

```powershell
.\run.ps1 eval    # 또는: ./run.sh eval
```

[evaluation/test_queries.csv](evaluation/test_queries.csv)의 20개 케이스(positive/negative/
edge/guardrail)를 자동 실행하고, `expected_traits` 충족 여부·`forbidden` 미포함 여부·
`expected_tools` 호출 여부를 LLM 심사로 채점합니다. 결과는 `evaluation/eval_result.json`에
저장되며, 전체 80% 이상 통과가 성공 기준입니다 (자세한 내용은
[SERVICE.md](SERVICE.md#5-성공-기준) 참고).

## 구현 상세

**`data/`**
- `scripts/fetch_tourapi.py` — TourAPI 호출(관광지/맛집/숙소)로 지역별 `.md` 생성, 키 없으면
  자동 스킵
- `docs/{제주,부산,강릉}.md` — 폴백 정적 데이터 (검증 안 된 주소·연락처는 지어내지 않고 비움)
- `build_chroma.py` — `RecursiveCharacterTextSplitter(300, 50)` → `Chroma.from_documents`

**`src/tools/`** (전부 결정적 계산/조회 — LLM 산술을 배제)
- `rag_search_tool.py` / `mcp_server.py` — RAG 검색, MCP로 노출
- `transport_tool.py` — 출발지~목적지 왕복 교통비 추정 (서울↔부산·서울↔강릉 KTX, 제주행
  국내선 항공만 지원하는 조회 테이블; 모르는 노선은 지어내지 않고 정보 없음으로 답함)
- `budget_tool.py` — 예산 배분 (취향 태그 가중치 조정 + 왕복 교통비 선차감)
- `itinerary_tool.py` — 시간 겹침·동선(지역 일관성) 검증

**`src/agents/`**
- `recommend_agent.py` / `budget_agent.py` / `itinerary_agent.py` — 위 도구를 하나씩 담당하는
  전문 에이전트 (`create_agent`)
- `supervisor.py` — 세 에이전트를 `create_supervisor`로 조립, 라우팅·종합 프롬프트 보유

**`src/graph/`**
- `outer_graph.py` — Supervisor를 감싸 HITL(`interrupt`) 승인/수정/거절을 처리하고, 진행
  상황(몇 단계 중 몇 단계)을 스피너로 스트리밍
- `guardrails.py` — 입력 가드레일(프롬프트 인젝션·주제 이탈 판별), 출력 가드레일(그라운딩
  재검증·예산 초과 재검증)

**`src/memory/`** (둘 다 `AsyncSqliteStore`로 영속화, 재실행해도 유지)
- `preferences.py` — 취향 태그·과거 방문지 요약
- `plans.py` — 승인된 계획 전체 원문 (시작 메뉴에서 재조회)

**`src/main.py`** — CLI 진입점 (메뉴, 입력 범위 검증, `종료` 명령, HITL 루프)

**`evaluation/`**
- `test_queries.csv` — 20개 케이스 (positive 8 · negative 4 · edge 5 · guardrail 3)
- `llm_judge.py` — `expected_traits`/`forbidden` 충족 여부를 구조화 출력으로 채점
- `run_eval.py` — Supervisor를 직접 호출하는 배치 평가 (HITL 없이 자동 실행)

## 디렉터리 구조

```
data/         관광 데이터 수집 스크립트, 정적 문서, Chroma 벡터DB 빌드
src/          에이전트/툴/그래프/CLI 구현
evaluation/   평가셋과 채점 스크립트
docs/         기획 단계 인터뷰 기록
reference/    7일 교육 과정 실습 코드 원본 (참고용, 수정하지 않음)
```

세부 구조와 설계 이유는 [CLAUDE.md](CLAUDE.md)에 정리되어 있습니다.
