"""
GitHub 저장소를 초안(draft) 저장소로 사용합니다.
GitHub Actions와 Railway 봇 모두 이 모듈을 통해 초안에 접근합니다.
"""

import json
import base64
import requests
from datetime import datetime


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
        response = requests.get(
            f"{self.base_url}/contents/drafts",
            headers=self.headers,
        )

        if response.status_code != 200:
            return []

        drafts = []
        for file_info in response.json():
            if not file_info["name"].endswith(".json") or file_info["name"] == ".gitkeep":
                continue

            draft_id = file_info["name"].replace(".json", "")
            draft = self.load_draft(draft_id)
            if draft and draft.get("status") == "pending":
                drafts.append(draft)

        return sorted(drafts, key=lambda x: x.get("fetched_at", ""))

    def _get_file_sha(self, path: str) -> str | None:
        """파일의 SHA를 가져옵니다 (업데이트 시 필요)."""
        response = requests.get(
            f"{self.base_url}/contents/{path}",
            headers=self.headers,
        )
        if response.status_code == 200:
            return response.json().get("sha")
        return None
