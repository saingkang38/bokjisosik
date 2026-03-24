"""
공공데이터포털 복지서비스 API에서 정책 데이터를 가져옵니다.
API 키가 없을 때는 샘플 데이터를 반환합니다.
"""

import requests
import hashlib
from datetime import datetime

WELFARE_API_URL = "http://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/LcgvWelfareSrvc"


def fetch_welfare_policies(api_key: str, num_rows: int = 5) -> list[dict]:
    """공공데이터포털 복지서비스 API 호출."""
    params = {
        "serviceKey": api_key,
        "pageNo": 1,
        "numOfRows": num_rows,
        "dataType": "JSON",
    }

    try:
        response = requests.get(WELFARE_API_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        items = (
            data.get("body", {})
                .get("items", {})
                .get("item", [])
        )

        if isinstance(items, dict):
            items = [items]

        print(f"[fetcher] {len(items)}개 정책 수집 완료")
        return items

    except Exception as e:
        print(f"[fetcher] API 호출 실패: {e}")
        return []


def normalize_policy(item: dict) -> dict:
    """API 응답을 표준 포맷으로 변환합니다."""
    raw_text = item.get("servId", "") + item.get("servNm", "") + item.get("jurMnofNm", "")
    draft_id = hashlib.md5(raw_text.encode()).hexdigest()[:12]

    return {
        "id": draft_id,
        "status": "pending",
        "title": item.get("servNm", "제목 없음"),
        "department": item.get("jurMnofNm", ""),           # 소관부처
        "target": item.get("tgtrDsc", ""),                 # 지원대상
        "summary": item.get("servDgst", ""),               # 서비스 요약
        "content": item.get("servCont", ""),               # 서비스 내용
        "start_date": item.get("srvBgYmd", ""),            # 서비스 시작일
        "end_date": item.get("srvEnYmd", ""),              # 서비스 종료일
        "apply_url": item.get("aplyUrlAddr", ""),          # 신청 URL
        "fetched_at": datetime.now().isoformat(),
        "rewritten_title": "",
        "rewritten_content": "",
        "telegram_message_id": None,
        "wp_post_id": None,
    }
