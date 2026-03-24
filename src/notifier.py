"""
GitHub Actions에서 실행 후 텔레그램으로 초안을 전송합니다.
(python-telegram-bot 없이 requests만 사용 - Actions 환경 경량화)
"""

import requests


def send_draft_notification(bot_token: str, chat_id: str, draft: dict) -> int | None:
    """
    초안을 텔레그램으로 전송하고 메시지 ID를 반환합니다.
    승인/거절 버튼이 포함된 인라인 키보드를 함께 전송합니다.
    """
    draft_id = draft["id"]
    title = draft.get("rewritten_title") or draft.get("title", "")
    content_preview = draft.get("rewritten_content", "")[:500]
    department = draft.get("department", "")
    target = draft.get("target", "")

    text = (
        f"📋 *새 복지 정책 초안*\n\n"
        f"*제목:* {title}\n"
        f"*부처:* {department}\n"
        f"*대상:* {target}\n\n"
        f"*미리보기:*\n{content_preview}...\n\n"
        f"_ID: {draft_id}_"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ 발행", "callback_data": f"approve:{draft_id}"},
                {"text": "❌ 거절", "callback_data": f"reject:{draft_id}"},
            ]
        ]
    }

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": keyboard,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        message_id = response.json()["result"]["message_id"]
        print(f"[notifier] 텔레그램 전송 완료 (msg_id: {message_id})")
        return message_id
    except Exception as e:
        print(f"[notifier] 텔레그램 전송 실패: {e}")
        return None


def send_message(bot_token: str, chat_id: str, text: str) -> None:
    """단순 텍스트 메시지 전송."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print(f"[notifier] 메시지 전송 실패: {e}")
