# CLAUDE.md

이 파일은 이 저장소에서 작업하는 Claude Code(및 다른 코딩 에이전트)를 위한 안내다.

## 프로젝트 개요

**국내 여행 플래너 Agent** — SDS 7일 LangChain/LangGraph 교육 과정(`reference/day1_practice`
~`day7_practice`)에서 배운 기술을 종합해 만든 캡스톤 프로젝트. 총 예산과 취향을 입력하면
국내 여행지 추천, 항목별(숙박/식비/교통/관광) 예산 자동 배분, 일자별 일정표 생성을 해주는
멀티에이전트 시스템이다.

기획 배경과 요구사항 전체는 [SERVICE.md](SERVICE.md)를 참고한다. 세부 설계 결정과 근거는
[docs/interview/](docs/interview/)의 인터뷰 기록에 남아 있다.

## 아키텍처

```
사용자 입력
  → 입력 가드레일 (여행 무관 질문/프롬프트 인젝션 차단)
  → outer_graph (LangGraph, AsyncSqliteSaver 체크포인터 + AsyncSqliteStore 장기기억 - 둘 다
    파일로 영속되어 프로그램을 다시 실행해도 유지됨)
      plan_trip 노드: Supervisor 멀티에이전트 서브그래프 호출 (진행 상황을 스피너로 표시)
        ├─ recommend_agent  (RAG 검색, MCP로 노출)
        ├─ budget_agent     (예산 계산기, 로컬 tool)
        └─ itinerary_agent  (일정 검증기, 로컬 tool)
      human_approval 노드: interrupt()로 최종 일정 승인/수정/거절
  → 출력 가드레일 (환각 장소명 차단, 예산 초과 재확인)
  → 최종 응답 (일정표 + 예산표 + 출처). 승인 시 계획 전체와 취향/방문지 요약을 장기 기억에
    저장 - 다음 실행 시 메뉴에서 다시 조회 가능
```

핵심 설계 이유:
- **Supervisor는 middleware를 지원하지 않는다** → 가드레일은 Supervisor 내부가 아니라
  `outer_graph`/`main.py`에서 호출 전후로 수동 적용한다.
- **예산·교통비 계산은 항상 `calculate_budget_allocation`/`estimate_round_trip_transport`
  툴이 전담** — LLM이 직접 산술하면 오류가 나기 쉬우므로, Agent는 툴 결과를 인용만 하도록
  프롬프트로 강제한다. 왕복 교통비는 알려진 노선(서울↔부산/강릉 KTX, 제주행 항공)만 조회
  테이블로 추정하고, 모르는 노선은 지어내지 않고 "정보 없음"으로 답한다.
- **RAG 검색만 MCP로 노출**하고 예산/교통비/일정 툴은 로컬 `@tool`로 둔다 — MCP는 독립
  배포가 필요한 서비스에 적합하고, 나머지는 이 프로젝트 내부에서만 쓰이기 때문.

## 디렉터리 구조

- `data/` — 관광 데이터(TourAPI 수집 스크립트 + 정적 md 문서) 및 Chroma 벡터DB 빌드 스크립트
- `src/tools/` — RAG 검색(MCP), 왕복 교통비 추정기, 예산 계산기, 일정 검증기
- `src/agents/` — 3개 specialist agent + Supervisor 조립
- `src/graph/` — 가드레일, HITL 포함 외곽 LangGraph
- `src/memory/`, `src/tracing/` — 장기 기억(사용자 취향), 실행 트레이싱
- `src/main.py` — CLI 진입점
- `evaluation/` — 평가셋(`test_queries.csv`)과 LLM 심사(`llm_judge.py`)/평가 실행(`run_eval.py`)
- `docs/interview/` — 기획 단계 deep-interview 기록 (구현 시 참고용, 산출물 아님)
- `reference/` — 7일 교육 과정 실습 코드 원본 (재사용 패턴의 출처, 직접 수정하지 않음)

## 실행 방법

`run.ps1`(Windows)/`run.sh`(macOS·Linux·Git Bash)의 `setup`/`data`/`start`/`eval` 서브커맨드를
쓴다 — 각 단계가 정확히 무슨 명령을 실행하는지는 두 스크립트 안에 그대로 적혀 있다. 자세한
사용법은 [README.md](README.md#빠른-시작) 참고.

`.env`(레포 루트)에 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`이
필요하다 (AWS Bedrock 사용). TourAPI 실연동을 원하면 `TOURAPI_KEY`를 추가한다.

## 공용 설정

모델 ID/리전 등은 `src/config.py`에 모아뒀다 — 새 파일에서 하드코딩하지 말고 여기서
import해서 쓴다. LLM은 전부 `temperature=0`(결정적 라우팅/툴 호출을 위해), 임베딩은
`amazon.titan-embed-text-v2:0`으로 고정되어 있다.

채팅 모델은 계정의 토큰 한도 스로틀링(`ThrottlingException`)이 자주 걸려서, 한 모델에
몰지 않고 `CHAT_MODEL_IDS` 목록을 `make_chat_llm()` 호출마다 순서대로 돌려쓴다
(`itertools.cycle`) — 현재 목록: `global.anthropic.claude-sonnet-4-5-20250929-v1:0`,
`us.anthropic.claude-sonnet-4-6`, `global.anthropic.claude-sonnet-4-6`. 호출될 때마다
`[모델] <model_id>`를 출력해서 어떤 모델이 쓰였는지 바로 확인할 수 있다. 목록을 조정하려면
`CHAT_MODEL_IDS`만 고치면 된다 (Haiku 4.5는 평가셋 통과율이 30%로 떨어져 기본 목록에서
뺐다 - 속도/비용이 급하지 않으면 넣지 않는 걸 권장).

## 알려진 한계

- **숙소 추천이 100% 보장되지 않는다.** `recommend_agent`에 "관광지/맛집/숙소를 각각 검색하고
  답변 전에 숙소 포함 여부를 점검하라"는 체크리스트를 넣었지만, 같은 모델·temperature=0
  에서도 요청 문구에 따라 빠지는 경우가 있다(`evaluation/test_queries.csv` 케이스 2). 프롬프트
  로는 확정적으로 못 고치는 LLM 비결정성 문제로 보고 더 밀어붙이지 않았다. 구조적으로 잡으려면
  Chroma 메타데이터에 카테고리 태그를 추가해 "숙소 카테고리 장소가 실제로 언급됐는지" 후처리
  검증을 `outer_graph.py`의 `plan_trip`에 추가하면 된다 (미구현).
- **TourAPI 데이터는 카테고리당 30건 샘플이다** (`fetch_tourapi.py`의
  `NUM_ENTRIES_PER_CATEGORY`). 실제로는 지역당 수백 건 있다. 늘리면 항목당 1번씩 더 호출하는
  홈페이지 조회(`detailCommon2`)도 비례해서 늘어난다.
- **맛집(음식점) 카테고리는 연락처가 거의 없고, 리뷰/평점은 TourAPI에 아예 없다** (순수
  이름/주소/사진/설명 디렉토리). 필요하면 카카오맵/네이버 플레이스 등 별도 상업용 API 연동이
  필요하다 (미구현).
- **지역 코드 확장 시 주의**: `areaCode`는 광역시/도 단위다. 부산·제주처럼 그 자체가 원하는
  범위인 지역은 괜찮지만, 강릉처럼 "도 안의 한 시"는 `sigunguCode`까지 지정해야 한다 -
  빠뜨리면 도 전체 데이터가 섞인다(`AREAS` 딕셔너리 참고). 새 지역 추가 시 `areaCode2` API로
  관할 범위를 먼저 확인한다.
