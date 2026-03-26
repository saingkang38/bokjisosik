"""
한국사회보장정보원 중앙부처복지서비스 API에서 정책 데이터를 가져옵니다.
- 목록: https://apis.data.go.kr/B554287/NationalWelfareInformationsV001/NationalWelfarelistV001
- 상세: https://apis.data.go.kr/B554287/NationalWelfareInformationsV001/NationalWelfaredetailedV001
"""

import requests
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime

BASE_URL = "https://apis.data.go.kr/B554287/NationalWelfareInformationsV001"


def fetch_welfare_policies(api_key: str, num_rows: int = 10, page: int = 1) -> list[dict]:
    """복지서비스 목록을 가져온 뒤 각 항목의 상세 정보까지 조회합니다."""
    url = f"{BASE_URL}/NationalWelfarelistV001"
    params = {
        "serviceKey": api_key,
        "pageNo": page,
        "numOfRows": num_rows,
        "srchKeyCode": "001",   # 필수 파라미터
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.text)

        result_code = root.findtext("resultCode", "")
        if result_code != "0":
            print(f"[fetcher] API 오류: {root.findtext('resultMessage', '')}")
            return []

        items = root.findall("servList")
        print(f"[fetcher] 목록 {len(items)}건 수집")

        results = []
        for item in items:
            serv_id = item.findtext("servId", "")
            if not serv_id:
                continue
            detail = fetch_welfare_detail(api_key, serv_id)
            if detail:
                detail["servDtlLink"] = item.findtext("servDtlLink", "")
                detail["sprtCycNm"] = item.findtext("sprtCycNm", "")
                detail["srvPvsnNm"] = item.findtext("srvPvsnNm", "")
                detail["intrsThemaArray"] = item.findtext("intrsThemaArray", "")  # 카테고리
                results.append(detail)

        return results

    except Exception as e:
        print(f"[fetcher] 목록 조회 실패: {e}")
        return []


def fetch_welfare_detail(api_key: str, serv_id: str) -> dict | None:
    """서비스 ID로 상세 정보를 조회합니다."""
    url = f"{BASE_URL}/NationalWelfaredetailedV001"
    params = {
        "serviceKey": api_key,
        "servId": serv_id,
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.text)

        if root.findtext("resultCode", "") != "0":
            return None

        def text(tag):
            el = root.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        # 신청방법 목록 추출
        apply_methods = []
        for a in root.findall("applmetList"):
            link = a.findtext("servSeDetailLink", "")
            if link:
                apply_methods.append(link)

        return {
            "servId":       text("servId"),
            "servNm":       text("servNm"),           # 서비스명
            "jurMnofNm":    text("jurMnofNm"),        # 소관부처명
            "tgtrDtlCn":    text("tgtrDtlCn"),        # 지원대상 상세
            "slctCritCn":   text("slctCritCn"),       # 선정기준
            "alwServCn":    text("alwServCn"),         # 지원내용
            "wlfareInfoOutlCn": text("wlfareInfoOutlCn"),  # 요약
            "rprsCtadr":    text("rprsCtadr"),         # 대표 연락처
            "applyMethod":  "\n".join(apply_methods),  # 신청방법
        }

    except Exception as e:
        print(f"[fetcher] 상세 조회 실패 ({serv_id}): {e}")
        return None


def normalize_policy(item: dict) -> dict:
    """API 응답을 초안 표준 포맷으로 변환합니다."""
    raw = item.get("servId", "") or item.get("servNm", "")
    draft_id = hashlib.md5(raw.encode()).hexdigest()[:12]

    return {
        "id": draft_id,
        "status": "pending",
        "title": item.get("servNm", "제목 없음"),
        "department": item.get("jurMnofNm", ""),
        "target": item.get("tgtrDtlCn", ""),
        "criteria": item.get("slctCritCn", ""),
        "content": item.get("alwServCn", ""),
        "summary": item.get("wlfareInfoOutlCn", ""),
        "apply_method": item.get("applyMethod", ""),
        "contact": item.get("rprsCtadr", ""),
        "detail_link": item.get("servDtlLink", ""),
        "serv_id": item.get("servId", ""),
        "categories": item.get("intrsThemaArray", ""),  # 예: "생활지원,신체건강"
        "fetched_at": datetime.now().isoformat(),
        "rewritten_title": "",
        "rewritten_content": "",
        "draft_content": "",       # 1차 초안
        "reviewed_content": "",    # 검수 후 최종본
        "scheduled_at": "",        # 예약발행 시각
        "image_url": "",
        "telegram_message_id": None,
        "wp_post_id": None,
    }
