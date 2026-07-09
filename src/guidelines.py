"""
AI 글 작성 지침(prompts/guidelines.md)을 읽고 저장합니다.

- GitHub 저장소(GITHUB_TOKEN/GITHUB_REPO 설정 시)를 우선 사용합니다.
  → 대시보드에서 지침을 수정하면 재배포 없이 다음 글부터 바로 반영됩니다.
- GitHub 접근이 안 되면 로컬 prompts/guidelines.md를 사용합니다.
"""

import os
import re

GUIDELINES_REPO_PATH = "prompts/guidelines.md"


def _local_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "prompts", "guidelines.md")


def load_guidelines_text(store=None) -> str:
    """지침 전문을 반환합니다. store는 GitHubStore 인스턴스(선택)."""
    if store:
        text = store.load_text_file(GUIDELINES_REPO_PATH)
        if text:
            return text

    try:
        with open(_local_path(), "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[guidelines] 로컬 지침 로드 실패: {e}")
        return ""


def save_guidelines_text(text: str, store=None) -> bool:
    """지침 전문을 저장합니다. GitHub 우선, 실패 시 로컬."""
    if store:
        if store.save_text_file(GUIDELINES_REPO_PATH, text, "docs: 지침 수정 (대시보드)"):
            return True

    try:
        with open(_local_path(), "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except Exception as e:
        print(f"[guidelines] 로컬 지침 저장 실패: {e}")
        return False


def parse_guidelines(text: str) -> dict:
    """지침 전문에서 각 섹션을 추출합니다.

    Returns: {"draft": str, "review": str, "banned_words": list[str]}
    """
    def section(title: str) -> str:
        match = re.search(rf"## {title}\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
        return match.group(1).strip() if match else ""

    banned = []
    for line in section("금지 표현").splitlines():
        line = line.strip()
        if line.startswith("- "):
            word = line[2:].strip()
            if word:
                banned.append(word)

    return {
        "draft": section("1차 초안 생성 프롬프트"),
        "review": section("2단계 검수 프롬프트"),
        "banned_words": banned,
    }
