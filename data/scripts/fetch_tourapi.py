# fetch_tourapi.py - 한국관광공사 TourAPI(국문 관광정보서비스)에서
# 지역별 관광지/음식점 정보를 받아 RAG용 정적 마크다운 문서(data/docs/<지역>.md)로 저장한다.
#
# 실행: python data/scripts/fetch_tourapi.py
#
# 필요 환경변수 (.env, 레포 루트):
#   TOURAPI_KEY  공공데이터포털에서 발급받은 "한국관광공사_국문 관광정보 서비스_GW" 인증키
#                (인코딩/디코딩 키 둘 다 그대로 붙여넣어도 된다 - 아래에서 자동으로 보정한다)
#
# TOURAPI_KEY가 없거나 호출이 실패하면 아무 문서도 덮어쓰지 않고 종료한다.
# 이 경우 data/docs/ 에는 사람이 미리 정리해 둔 폴백 문서(*.md)가 그대로 RAG 소스로 쓰인다.
import os
import sys
from pathlib import Path
from urllib.parse import unquote

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # mini-pjt/data
DOCS_DIR = BASE_DIR / "docs"

load_dotenv(BASE_DIR.parent / ".env")

AREA_LIST_URL = "http://apis.data.go.kr/B551011/KorService2/areaBasedList2"
DETAIL_COMMON_URL = "http://apis.data.go.kr/B551011/KorService2/detailCommon2"

# 지역코드(areaCode)는 TourAPI 표준 코드. 부산/제주는 광역시·특별자치도라 areaCode만으로
# 이미 원하는 범위(도시 전체/섬 전체)와 일치하지만, 강릉은 "강원특별자치도"라는 도(道) 전체를
# 가리키는 areaCode(32) 아래의 한 시(市)일 뿐이라 sigunguCode(시군구코드)까지 지정해야 한다.
# 이걸 빠뜨리면 강릉이 아니라 강원도 전역(춘천/평창/삼척 등)이 섞여 들어온다 - 실제로 한 번
# 이 버그로 데이터를 받은 적이 있어 areaCode2 API로 sigunguCode(강릉시=1)를 확인해 고쳤다.
AREAS = {
    "제주": {"area_code": "39"},
    "부산": {"area_code": "6"},
    "강릉": {"area_code": "32", "sigungu_code": "1"},
}

# contentTypeId: 12=관광지, 39=음식점, 32=숙박
CONTENT_TYPES = {
    "관광지": "12",
    "맛집": "39",
    "숙소": "32",
}

# TourAPI에 실제로 존재하는 건수는 카테고리당 수백 건인데(예: 제주 맛집 490건), RAG
# 임베딩 비용과 detailCommon2 호출 횟수(항목당 1회 추가)를 고려해 카테고리당 이만큼만
# 큐레이션해서 가져온다. 늘리고 싶으면 이 값만 바꾸면 된다. (평가/개발 중 빠른 반복 테스트를
# 위해 30에서 10으로 낮춰뒀다 - 최종 데이터 규모를 키우려면 다시 올린다.)
NUM_ENTRIES_PER_CATEGORY = 10


def fetch_area(
    area_name: str, area_code: str, content_type_name: str, content_type_id: str, api_key: str,
    sigungu_code: str | None = None,
) -> list[dict]:
    params = {
        "serviceKey": api_key,
        "numOfRows": NUM_ENTRIES_PER_CATEGORY,
        "pageNo": 1,
        "MobileOS": "ETC",
        "MobileApp": "TravelPlanner",
        # arrangeType은 값에 상관없이 "INVALID_REQUEST_PARAMETER_ERROR(arrangeType)"로 거부되는
        # 것을 라이브로 확인해 뺐다 (A/B/C/D/O/Q/R/S 전부 실패, 파라미터 자체를 안 보내면 정상
        # 응답 - 이 계정/버전의 KorService2가 이 파라미터를 안 받는 것으로 보인다). 기본 정렬로
        # 받아도 우리는 어차피 전체 목록을 다 쓰므로 문제 없다.
        "areaCode": area_code,
        "contentTypeId": content_type_id,
        "_type": "json",
    }
    if sigungu_code:
        params["sigunguCode"] = sigungu_code
    resp = requests.get(AREA_LIST_URL, params=params, timeout=10)
    resp.raise_for_status()
    body = resp.json()["response"]["body"]
    items = body.get("items", "")
    if not items:
        return []
    rows = items.get("item", [])
    if isinstance(rows, dict):
        rows = [rows]
    results = []
    for row in rows:
        results.append(
            {
                "content_id": row.get("contentid", ""),
                "name": row.get("title", "").strip(),
                "address": row.get("addr1", "").strip(),
                # areaBasedList2가 tel을 비워 주는 경우가 많아, 없으면 detailCommon2로 보완한다.
                "tel": row.get("tel", "").strip(),
                "homepage": "",
                "category": content_type_name,
            }
        )
    return results


def fetch_homepage(content_id: str, content_type_id: str, api_key: str) -> str:
    """detailCommon2에서 홈페이지 URL만 뽑아온다. homepage 필드는 <a href="...">...</a> 형태의
    HTML 앵커 문자열로 오므로 href 값만 정규식으로 추출한다. 실패하면 조용히 빈 문자열을 반환한다
    (이 정보 없이도 나머지 데이터는 쓸 수 있어야 하므로 전체를 막지 않는다)."""
    import re

    params = {
        "serviceKey": api_key,
        "contentId": content_id,
        "contentTypeId": content_type_id,
        "defaultYN": "Y",
        "overviewYN": "N",
        "MobileOS": "ETC",
        "MobileApp": "TravelPlanner",
        "_type": "json",
    }
    try:
        resp = requests.get(DETAIL_COMMON_URL, params=params, timeout=10)
        resp.raise_for_status()
        body = resp.json()["response"]["body"]
        item = body.get("items", {}).get("item", [{}])
        if isinstance(item, list):
            item = item[0] if item else {}
        homepage_html = (item.get("homepage") or "").strip()
        match = re.search(r'href="([^"]+)"', homepage_html)
        return match.group(1) if match else ""
    except Exception:
        return ""


def write_doc(area_name: str, entries_by_category: dict[str, list[dict]]) -> Path:
    path = DOCS_DIR / f"{area_name}.md"
    lines = [f"# {area_name} 여행 정보", "", "> 출처: 한국관광공사 TourAPI (areaBasedList2 + detailCommon2)", ""]
    for category, entries in entries_by_category.items():
        lines.append(f"## {category}")
        lines.append("")
        for e in entries:
            lines.append(f"- **{e['name']}**")
            if e["address"]:
                lines.append(f"  - 주소: {e['address']}")
            if e["tel"]:
                lines.append(f"  - 연락처: {e['tel']}")
            if e["homepage"]:
                lines.append(f"  - 웹사이트: {e['homepage']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    api_key = os.environ.get("TOURAPI_KEY")
    if not api_key:
        print("TOURAPI_KEY가 .env에 없습니다. TourAPI 호출을 건너뜁니다.")
        print("data/docs/ 의 기존(폴백) 문서를 그대로 사용합니다.")
        return

    # 공공데이터포털은 서비스키를 "인코딩(Encoding)"과 "디코딩(Decoding)" 두 형태로 준다.
    # 인코딩 키(%2F, %2B, %3D 등 %가 포함된 형태)를 그대로 requests에 넘기면, requests가
    # 쿼리스트링을 만들 때 그 %를 다시 한번 퍼센트 인코딩해버려 이중 인코딩된 키가 되고,
    # API가 이를 유효하지 않은 키로 판단해 403 Forbidden을 반환한다. %가 섞여 있으면 먼저
    # 한 번 디코딩해서 항상 "순수한(디코딩된)" 키 상태로 맞춰준다 - 디코딩 키를 넣었을 때도
    # unquote()는 아무 영향이 없어(% 문자가 없으므로) 두 경우 모두 안전하다.
    if "%" in api_key:
        api_key = unquote(api_key)
        print("[안내] TOURAPI_KEY에 '%'가 포함되어 있어 이중 인코딩 방지를 위해 한 번 디코딩했습니다.")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    any_success = False
    for area_name, area_conf in AREAS.items():
        area_code = area_conf["area_code"]
        sigungu_code = area_conf.get("sigungu_code")
        entries_by_category: dict[str, list[dict]] = {}
        for cat_name, cat_id in CONTENT_TYPES.items():
            try:
                entries = fetch_area(area_name, area_code, cat_name, cat_id, api_key, sigungu_code)
            except Exception as e:
                print(f"[경고] {area_name}/{cat_name} 조회 실패: {type(e).__name__}: {e}")
                entries = []
            # 홈페이지는 목록 API에 없어 항목별로 detailCommon2를 한 번씩 더 호출해야 한다.
            for e in entries:
                if e["content_id"]:
                    e["homepage"] = fetch_homepage(e["content_id"], cat_id, api_key)
            if entries:
                entries_by_category[cat_name] = entries
        if entries_by_category:
            path = write_doc(area_name, entries_by_category)
            print(f"생성: {path} ({sum(len(v) for v in entries_by_category.values())}건)")
            any_success = True
        else:
            print(f"[경고] {area_name}: 가져온 데이터 없음 (폴백 문서 유지)")

    if not any_success:
        print("TourAPI에서 아무 데이터도 받지 못했습니다. 폴백 문서만 사용됩니다.")
        sys.exit(0)


if __name__ == "__main__":
    main()
