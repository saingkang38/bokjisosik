"""
Claude API를 사용해 복지 정책을 2단계로 처리합니다.
1단계: 초안 생성 (보수적 초안 작성 엔진)
2단계: 초안 검수 (보수적 검수 및 교정 엔진)

프롬프트는 prompts/guidelines.md에서 읽어옵니다.
"""

import anthropic
import os
import re


def _load_guidelines() -> dict:
    """guidelines.md에서 각 단계 프롬프트를 읽어옵니다."""
    # 파일 위치: 프로젝트 루트의 prompts/guidelines.md
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base_dir, "prompts", "guidelines.md")

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # 1차 초안 프롬프트 추출
        draft_match = re.search(
            r"## 1차 초안 생성 프롬프트\n(.*?)(?=## |\Z)", content, re.DOTALL
        )
        draft_prompt = draft_match.group(1).strip() if draft_match else ""

        # 검수 프롬프트 추출
        review_match = re.search(
            r"## 2단계 검수 프롬프트\n(.*?)(?=## |\Z)", content, re.DOTALL
        )
        review_prompt = review_match.group(1).strip() if review_match else ""

        return {"draft": draft_prompt, "review": review_prompt}

    except Exception as e:
        print(f"[rewriter] guidelines.md 로드 실패: {e}")
        return {"draft": "", "review": ""}


def generate_draft(draft: dict, api_key: str) -> str:
    """
    1단계: 원문 데이터를 기반으로 1차 초안을 생성합니다.
    Returns: 초안 텍스트
    """
    guidelines = _load_guidelines()
    system_prompt = guidelines["draft"]

    if not system_prompt:
        return "[오류] guidelines.md에서 초안 프롬프트를 찾을 수 없습니다."

    user_content = f"""[원문 데이터]
서비스명: {draft.get('title', '')}
소관부처: {draft.get('department', '')}
지원대상: {draft.get('target', '')}
선정기준: {draft.get('criteria', '')}
지원내용: {draft.get('content', '')}
서비스요약: {draft.get('summary', '')}
신청방법: {draft.get('apply_method', '')}
연락처: {draft.get('contact', '')}
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return message.content[0].text
    except Exception as e:
        return f"[오류] 초안 생성 실패: {e}"


def review_draft(draft: dict, draft_content: str, api_key: str) -> str:
    """
    2단계: 원문과 1차 초안을 비교하여 검수합니다.
    Returns: 검수 결과 텍스트 (최종 수정본 포함)
    """
    guidelines = _load_guidelines()
    system_prompt = guidelines["review"]

    if not system_prompt:
        return "[오류] guidelines.md에서 검수 프롬프트를 찾을 수 없습니다."

    user_content = f"""[원문 데이터]
서비스명: {draft.get('title', '')}
소관부처: {draft.get('department', '')}
지원대상: {draft.get('target', '')}
선정기준: {draft.get('criteria', '')}
지원내용: {draft.get('content', '')}
서비스요약: {draft.get('summary', '')}
신청방법: {draft.get('apply_method', '')}

[1차 가공 초안]
{draft_content}
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return message.content[0].text
    except Exception as e:
        return f"[오류] 검수 실패: {e}"
