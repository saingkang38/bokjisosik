"""
Claude API를 사용해 복지 정책을 중학생도 이해할 수 있는 쉬운 글로 재작성합니다.
"""

import anthropic

SYSTEM_PROMPT = """당신은 복지 정책 전문 블로그 작가입니다.
어려운 정부 복지 정책 내용을 중학생도 쉽게 이해할 수 있도록 블로그 포스팅으로 재작성합니다.

규칙:
1. 어려운 한자어나 행정용어는 쉬운 말로 바꿔 설명하세요
2. 핵심 내용을 먼저 말하고, 자세한 내용은 뒤에 설명하세요
3. 지원 대상, 지원 내용, 신청 방법을 명확하게 구분해 주세요
4. 딱딱한 말투가 아닌 친근하고 따뜻한 말투를 사용하세요
5. HTML 태그를 사용해 워드프레스에 바로 올릴 수 있게 작성하세요
6. 제목은 클릭하고 싶게 흥미롭게 만드세요
"""

USER_PROMPT_TEMPLATE = """아래 복지 정책 정보를 블로그 포스팅으로 재작성해주세요.

[원본 정보]
정책명: {title}
소관부처: {department}
지원대상: {target}
서비스 요약: {summary}
서비스 내용: {content}
신청 URL: {apply_url}

[출력 형식]
반드시 아래 형식으로 출력하세요:

TITLE: (블로그 제목)
---
CONTENT:
(HTML 형식의 블로그 본문)
"""


def rewrite_policy(draft: dict, api_key: str) -> tuple[str, str]:
    """
    정책 내용을 Claude로 재작성합니다.
    Returns: (rewritten_title, rewritten_content)
    """
    client = anthropic.Anthropic(api_key=api_key)

    prompt = USER_PROMPT_TEMPLATE.format(
        title=draft.get("title", ""),
        department=draft.get("department", ""),
        target=draft.get("target", ""),
        summary=draft.get("summary", ""),
        content=draft.get("content", ""),
        apply_url=draft.get("apply_url", ""),
    )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
            system=SYSTEM_PROMPT,
        )

        response_text = message.content[0].text

        # TITLE / CONTENT 파싱
        title = draft["title"]
        content = response_text

        if "TITLE:" in response_text and "---" in response_text:
            parts = response_text.split("---", 1)
            title_line = parts[0].strip()
            title = title_line.replace("TITLE:", "").strip()

            if "CONTENT:" in parts[1]:
                content = parts[1].split("CONTENT:", 1)[1].strip()

        print(f"[rewriter] 재작성 완료: {title[:30]}...")
        return title, content

    except Exception as e:
        print(f"[rewriter] 재작성 실패: {e}")
        return draft["title"], draft.get("content", "")
