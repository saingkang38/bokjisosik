"""
WordPress REST API를 통해 포스트를 발행합니다.
Application Password 방식으로 인증합니다.
"""

import requests
from requests.auth import HTTPBasicAuth


def publish_post(
    wp_url: str,
    username: str,
    app_password: str,
    title: str,
    content: str,
    status: str = "publish",       # publish / draft
    category_ids: list[int] = None,
    tags: list[str] = None,
) -> dict | None:
    """
    WordPress에 포스트를 발행합니다.
    성공 시 포스트 정보(dict)를 반환합니다.

    app_password: 워드프레스 관리자 → 사용자 → 애플리케이션 비밀번호에서 생성
    """
    api_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts"
    auth = HTTPBasicAuth(username, app_password)

    payload: dict = {
        "title": title,
        "content": content,
        "status": status,
    }

    if category_ids:
        payload["categories"] = category_ids

    if tags:
        tag_ids = _get_or_create_tags(wp_url, auth, tags)
        payload["tags"] = tag_ids

    try:
        response = requests.post(api_url, json=payload, auth=auth, timeout=30)
        response.raise_for_status()
        post = response.json()
        print(f"[wordpress] 발행 완료: {post.get('link', '')}")
        return post
    except Exception as e:
        print(f"[wordpress] 발행 실패: {e}")
        return None


def _get_or_create_tags(wp_url: str, auth: HTTPBasicAuth, tag_names: list[str]) -> list[int]:
    """태그 이름 목록을 ID 목록으로 변환합니다. 없으면 생성합니다."""
    tag_ids = []
    tags_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/tags"

    for name in tag_names:
        try:
            # 기존 태그 검색
            resp = requests.get(tags_url, params={"search": name}, auth=auth, timeout=10)
            results = resp.json()

            if results:
                tag_ids.append(results[0]["id"])
            else:
                # 새 태그 생성
                create_resp = requests.post(tags_url, json={"name": name}, auth=auth, timeout=10)
                tag_ids.append(create_resp.json()["id"])
        except Exception:
            continue

    return tag_ids
