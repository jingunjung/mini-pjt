# 프로젝트 개요

> Source: Deep Interview, 2026-09-02

## Key Points
- SDS 7일 LangChain/LangGraph 교육 과정의 캡스톤(수료) 제출물.
- 산출물은 프로젝트 루트의 `SERVICE.md` 템플릿(사용자·문제·가치 / 확장 관점 / 도구·데이터 /
  가드레일 / 성공기준)을 채우는 것 + `data/`, `evaluation/`, `src/` 구현.
- 핵심 시나리오: **출장(사내 업무)보다 개인 여행 일정 플래너**에 가까움 — 목적지 추천, 일정표
  생성, 예산 배분, 맛집/관광지 추천 등.
- 인터뷰는 medium 깊이로 진행 (테마별 4~6질문, 총 6~10라운드).

## Details
7일 과정에서 등장한 재사용 가능 기술:
- Day1: LCEL, 멀티턴 히스토리, 구조화 출력(Structured Output), 툴 사용 여부 판단
- Day2: RAG (청킹/임베딩/벡터스토어/하이브리드 검색/리랭크/환각 검증) — `travel_policy.md` 등
  사내 규정 문서가 예시로 존재 (여행 플래너에는 규정 대신 여행 가이드/여행지 정보 문서로 대체 가능)
- Day3: LangGraph 상태 그래프, 조건 분기, 사이클, ReAct 에이전트
- Day4: Tools, MCP 서버/클라이언트, ToolNode 병렬 처리, 트레이싱
- Day5: 체크포인터(대화 지속), Human-in-the-loop(interrupt), 입출력 가드레일, 미들웨어, 요약
- Day6: 멀티에이전트 Supervisor 구조 (research_agent/data_agent/general_agent 조합)
- Day7: Plan-and-Execute, 장기 기억(Store), LLM 심사(judge)/평가셋, 트레이싱, 통합 점검

## Open Questions
- 여행 플래너에 구체적으로 어떤 하위 기능(목적지 추천, 일정 생성, 예산, 예약 연동 등)을 넣을지
- RAG에 쓸 문서를 무엇으로 할지 (여행 가이드북? 비자/입국 규정? 회사 출장 규정도 일부 포함?)
- MCP로 노출할 도구는 무엇으로 할지 (실제 API 연동 vs 더미 데이터)
- 멀티에이전트로 나눌지, 단일 ReAct 에이전트로 할지
- HITL(사람 승인)이 필요한 지점이 있는지 (예: 예약 확정 전 승인)
- 성공 기준을 어떻게 잡을지
