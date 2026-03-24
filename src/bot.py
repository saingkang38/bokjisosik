"""
텔레그램 봇 - Railway에서 항상 실행됩니다.
모바일에서 복지 정책 초안을 검토하고 승인/거절할 수 있습니다.

명령어:
  /start    - 봇 소개
  /pending  - 대기 중인 초안 목록
  /status   - 전체 현황
"""

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from src.github_store import GitHubStore
from src.wordpress import publish_post
from src.notifier import send_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_store() -> GitHubStore:
    return GitHubStore(
        token=os.environ["GITHUB_TOKEN"],
        repo=os.environ["GITHUB_REPO"],
    )


# ──────────────────────────────────────────
# 명령어 핸들러
# ──────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 복지소식 봇입니다!\n\n"
        "/pending - 승인 대기 중인 포스팅 보기\n"
        "/status  - 발행 현황 보기"
    )


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_store()
    drafts = store.list_pending()

    if not drafts:
        await update.message.reply_text("✅ 대기 중인 초안이 없습니다.")
        return

    for draft in drafts[:5]:  # 최대 5개씩 표시
        await _send_draft_card(update.message.chat_id, draft, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_store()
    pending = store.list_pending()
    await update.message.reply_text(
        f"📊 현황\n\n대기 중: {len(pending)}건"
    )


# ──────────────────────────────────────────
# 인라인 버튼 콜백
# ──────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, draft_id = query.data.split(":", 1)
    store = get_store()
    draft = store.load_draft(draft_id)

    if not draft:
        await query.edit_message_text("❌ 초안을 찾을 수 없습니다.")
        return

    if action == "approve":
        await _handle_approve(query, draft, store)
    elif action == "reject":
        await _handle_reject(query, draft, store)
    elif action == "preview":
        await _handle_preview(query, draft)


async def _handle_approve(query, draft: dict, store: GitHubStore):
    """승인 → 워드프레스 발행."""
    title = draft.get("rewritten_title") or draft.get("title", "")
    content = draft.get("rewritten_content") or draft.get("content", "")

    await query.edit_message_text(f"⏳ 발행 중...\n{title}")

    post = publish_post(
        wp_url=os.environ["WP_URL"],
        username=os.environ["WP_USERNAME"],
        app_password=os.environ["WP_APP_PASSWORD"],
        title=title,
        content=content,
        tags=["복지", "정부지원", draft.get("department", "")],
    )

    if post:
        store.update_status(draft["id"], "published")
        draft["wp_post_id"] = post.get("id")
        store.save_draft(draft)
        await query.edit_message_text(
            f"✅ 발행 완료!\n\n"
            f"*{title}*\n"
            f"{post.get('link', '')}",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text("❌ 워드프레스 발행에 실패했습니다. 설정을 확인해주세요.")


async def _handle_reject(query, draft: dict, store: GitHubStore):
    """거절 → 상태 업데이트."""
    store.update_status(draft["id"], "rejected")
    title = draft.get("rewritten_title") or draft.get("title", "")
    await query.edit_message_text(f"❌ 거절됨\n\n{title}")


async def _handle_preview(query, draft: dict):
    """전체 본문 미리보기."""
    content = draft.get("rewritten_content", "")
    # HTML 태그 제거 (텔레그램 표시용)
    import re
    plain = re.sub(r"<[^>]+>", "", content)[:3000]

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 발행", callback_data=f"approve:{draft['id']}"),
            InlineKeyboardButton("❌ 거절", callback_data=f"reject:{draft['id']}"),
        ]
    ])
    await query.message.reply_text(plain, reply_markup=keyboard)


# ──────────────────────────────────────────
# 초안 카드 전송
# ──────────────────────────────────────────

async def _send_draft_card(chat_id: int, draft: dict, context: ContextTypes.DEFAULT_TYPE):
    draft_id = draft["id"]
    title = draft.get("rewritten_title") or draft.get("title", "")
    preview = draft.get("rewritten_content", "")[:300]

    import re
    plain_preview = re.sub(r"<[^>]+>", "", preview)

    text = (
        f"📋 *{title}*\n\n"
        f"{plain_preview}...\n\n"
        f"부처: {draft.get('department', '')}\n"
        f"대상: {draft.get('target', '')[:100]}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 발행", callback_data=f"approve:{draft_id}"),
            InlineKeyboardButton("👁 미리보기", callback_data=f"preview:{draft_id}"),
            InlineKeyboardButton("❌ 거절", callback_data=f"reject:{draft_id}"),
        ]
    ])

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ──────────────────────────────────────────
# 봇 실행
# ──────────────────────────────────────────

def run_bot():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("[bot] 텔레그램 봇 시작...")
    app.run_polling(drop_pending_updates=True)
