"""
GitHub 저장소를 초안(draft) 저장소로 사용합니다.
GitHub Actions와 Railway 봇 모두 이 모듈을 통해 초안에 접근합니다.
"""

from __future__ import annotations

import json
import base64
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# 목록 캐시: repo -> {"ts": float, "drafts": {id: draft}}
# 페이지를 이동할 때마다 100여 개 파일을 다시 불러오지 않도록 잠깐 저장해둔다.
# 글을 저장하면 해당 항목만 즉시 갱신되므로 최신 상태가 유지된다.
_LIST_CACHE: dict = {}
_CACHE_TTL = 45.0  # 초. 이 시간이 지나면 GitHub에서 새로 불러온다(새 수집분 반영).


class GitHubStore:
    def __init__(self, token: str, repo: str):
        """
        token: GitHub Personal Access Token (또는 Actions의 GITHUB_TOKEN)
        repo: "유저명/bokjisosik" 형식
        """
        self.token = token
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{repo}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def save_draft(self, draft: dict) -> bool:
        """초안을 drafts/{id}.json 으로 저장합니다."""
        draft_id = draft["id"]
        path = f"drafts/{draft_id}.json"
        content_str = json.dumps(draft, ensure_ascii=False, indent=2)
        encoded = base64.b64encode(content_str.encode()).decode()

        sha = self._get_file_sha(path)

        payload = {
            "message": f"draft: {draft.get('rewritten_title', draft.get('title', draft_id))[:50]}",
            "content": encoded,
        }
        if sha:
            payload["sha"] = sha

        response = requests.put(
            f"{self.base_url}/contents/{path}",
            headers=self.headers,
            json=payload,
        )

        success = response.status_code in (200, 201)
        if not success:
            print(f"[github_store] 저장 실패 ({response.status_code}): {response.text[:200]}")
        else:
            # 캐시에 해당 글만 즉시 반영(전체 재조회 없이 최신 상태 유지)
            entry = _LIST_CACHE.get(self.repo)
            if entry is not None:
                if draft.get("status") == "excluded":
                    entry["drafts"].pop(draft_id, None)
                else:
                    entry["drafts"][draft_id] = draft
        return success

    def load_draft(self, draft_id: str) -> dict | None:
        """초안을 로드합니다."""
        path = f"drafts/{draft_id}.json"
        response = requests.get(
            f"{self.base_url}/contents/{path}",
            headers=self.headers,
        )

        if response.status_code != 200:
            print(f"[github_store] 로드 실패: {draft_id}")
            return None

        raw = base64.b64decode(response.json()["content"]).decode()
        return json.loads(raw)

    def update_status(self, draft_id: str, status: str) -> bool:
        """초안 상태를 업데이트합니다. (pending / published / rejected)"""
        draft = self.load_draft(draft_id)
        if not draft:
            return False

        draft["status"] = status
        draft["updated_at"] = datetime.now().isoformat()
        return self.save_draft(draft)

    def list_pending(self) -> list[dict]:
        """대기 중인 초안 목록을 반환합니다."""
        return [d for d in self.list_all() if d.get("status") == "pending"]

    def _fetch_one_raw(self, entry: tuple) -> tuple:
        """(id, download_url)을 받아 raw CDN에서 내용을 가져온다. (id, draft|None) 반환."""
        draft_id, url = entry
        try:
            # raw.githubusercontent.com은 CDN이라 빠르고 API 호출 제한에 걸리지 않는다.
            # 비공개 저장소면 download_url에 임시 토큰이 포함되어 인증도 자동 처리된다.
            r = requests.get(url, headers={"Authorization": f"Bearer {self.token}"}, timeout=20)
            if r.status_code == 200:
                return draft_id, json.loads(r.text)
        except Exception as e:
            print(f"[github_store] raw 로드 실패 ({draft_id}): {e}")
        return draft_id, None

    def _fetch_all_drafts(self) -> dict:
        """drafts/ 폴더의 모든 글을 raw CDN에서 병렬로 불러온다. {id: draft} 반환."""
        response = requests.get(
            f"{self.base_url}/contents/drafts",
            headers=self.headers,
        )
        if response.status_code != 200:
            return {}

        entries = [
            (f["name"][:-5], f["download_url"])
            for f in response.json()
            if f["name"].endswith(".json") and f["name"] != ".gitkeep" and f.get("download_url")
        ]

        drafts: dict = {}
        # 순차로 100여 번 호출하면 20~30초. CDN에서 동시에 불러와 수 초로 단축.
        with ThreadPoolExecutor(max_workers=16) as ex:
            for draft_id, draft in ex.map(self._fetch_one_raw, entries):
                if draft:
                    drafts[draft_id] = draft
        return drafts

    def list_all(self, use_cache: bool = True) -> list[dict]:
        """제외된 항목을 제외한 모든 글 목록을 반환합니다. (캐시 활용)"""
        entry = _LIST_CACHE.get(self.repo)
        now = time.time()
        if use_cache and entry and (now - entry["ts"]) < _CACHE_TTL:
            drafts = entry["drafts"]
        else:
            drafts = self._fetch_all_drafts()
            _LIST_CACHE[self.repo] = {"ts": now, "drafts": drafts}

        result = [d for d in drafts.values() if d.get("status") != "excluded"]
        return sorted(result, key=lambda x: x.get("fetched_at", ""))

    def load_text_file(self, path: str) -> str | None:
        """저장소의 텍스트 파일(예: prompts/guidelines.md)을 읽습니다."""
        response = requests.get(
            f"{self.base_url}/contents/{path}",
            headers=self.headers,
        )
        if response.status_code != 200:
            return None
        return base64.b64decode(response.json()["content"]).decode()

    def save_text_file(self, path: str, content: str, message: str) -> bool:
        """저장소의 텍스트 파일을 저장(커밋)합니다."""
        encoded = base64.b64encode(content.encode()).decode()
        payload = {"message": message, "content": encoded}

        sha = self._get_file_sha(path)
        if sha:
            payload["sha"] = sha

        response = requests.put(
            f"{self.base_url}/contents/{path}",
            headers=self.headers,
            json=payload,
        )
        success = response.status_code in (200, 201)
        if not success:
            print(f"[github_store] 파일 저장 실패 ({response.status_code}): {response.text[:200]}")
        return success

    def _get_file_sha(self, path: str) -> str | None:
        """파일의 SHA를 가져옵니다 (업데이트 시 필요)."""
        response = requests.get(
            f"{self.base_url}/contents/{path}",
            headers=self.headers,
        )
        if response.status_code == 200:
            return response.json().get("sha")
        return None
