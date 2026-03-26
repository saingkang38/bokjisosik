"""
한국사회보장정보원 중앙부처복지서비스 API에서 정책 데이터를 가져옵니다.
엔드포인트: https://apis.data.go.kr/B554287/NationalWelfareInformationsV001
데이터포맷: XML
"""

import requests
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime

BASE_URL = "https://apis.data.go.kr/B554287/NationalWelfareInformationsV001"


def fetch_welfare_policies(api_key: str, num_rows: int = 5) -> list[dict]:
    """중앙부처복지서비스 목록을 가져옵니다."""
    url = f"{BASE_URL}/getNationalWelfareListV001"
    params = {
        "serviceKey": api_key,
        "pageNo": 1,
        "numOfRows": num_rows,
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        root = ET.fromstring(response.text)

        # 에러 체크
        result_code = root.findtext(".//resultCode", "")
        if result_code and result_code != "00":
            result_msg = root.findtext(".//resultMsg", "")
            print(f"[fetcher] API 오류: {result_code} - {result_msg}")
            return []

        items = root.findall(".//servList") or root.findall(".//item")
        print(f"[fetcher] {len(items)}개 정책 수집 완료")
        return [_parse_item(item) for item in items]

    except Exception as e:
        print(f"[fetcher] API 호출 실패: {e}")
        return []


def fetch_welfare_detail(api_key: str, serv_id: str) -> dict:
    """서비스 ID로 상세 정보를 가져옵니다."""
    url = f"{BASE_URL}/getNationalWelfareDetailV001"
    params = {
        "serviceKey": api_key,
        "servId": serv_id,
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        item = root.find(".//servDtlList") or root.find(".//item")
        if item is not None:
            return _parse_item(item)
    except Exception as e:
        print(f"[fetcher] 상세 조회 실패: {e}")

    return {}


def _parse_item(item: ET.Element) -> dict:
    """XML 엘리먼트를 딕셔너리로 변환합니다."""
    def text(tag):
        el = item.find(tag)
        return el.text.strip() if el is not None and el.text else ""

    return {
        "servId":     text("servId"),
        "servNm":     text("servNm"),        # 서비스명
        "jurMnofNm":  text("jurMnofNm"),     # 소관부처명
        "tgtrDsc":    text("tgtrDsc"),       # 지원대상
        "servDgst":   text("servDgst"),      # 서비스 요약
        "servCont":   text("servCont"),      # 서비스 내용
        "srvBgYmd":   text("srvBgYmd"),      # 서비스 시작일
        "srvEnYmd":   text("srvEnYmd"),      # 서비스 종료일
        "aplyUrlAddr": text("aplyUrlAddr"),  # 신청 URL
    }


def normalize_policy(item: dict) -> dict:
    """API 응답을 초안 표준 포맷으로 변환합니다."""
    raw = item.get("servId", "") or item.get("servNm", "") + item.get("jurMnofNm", "")
    draft_id = hashlib.md5(raw.encode()).hexdigest()[:12]

    return {
        "id": draft_id,
        "status": "pending",
        "title": item.get("servNm", "제목 없음"),
        "department": item.get("jurMnofNm", ""),
        "target": item.get("tgtrDsc", ""),
        "summary": item.get("servDgst", ""),
        "content": item.get("servCont", ""),
        "start_date": item.get("srvBgYmd", ""),
        "end_date": item.get("srvEnYmd", ""),
        "apply_url": item.get("aplyUrlAddr", ""),
        "fetched_at": datetime.now().isoformat(),
        "rewritten_title": "",
        "rewritten_content": "",
        "telegram_message_id": None,
        "wp_post_id": None,
    }
