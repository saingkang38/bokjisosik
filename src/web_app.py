"""
복지소식 웹 대시보드
모바일 브라우저에서 초안을 검토하고 워드프레스에 발행합니다.
"""

import os
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from src.github_store import GitHubStore
from src.wordpress import publish_post
from src.notifier import send_message

app = FastAPI()
templates = Jinja2Templates(directory="templates")

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "bokji1234")


def get_store() -> GitHubStore:
    return GitHubStore(
        token=os.environ["GITHUB_TOKEN"],
        repo=os.environ["GITHUB_REPO"],
    )


def check_auth(request: Request) -> bool:
    return request.cookies.get("auth") == DASHBOARD_PASSWORD


# ──────────────────────────────────────────
# 로그인
# ──────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    if password == DASHBOARD_PASSWORD:
        response = RedirectResponse("/", status_code=302)
        response.set_cookie("auth", DASHBOARD_PASSWORD, max_age=60 * 60 * 24 * 30)
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "비밀번호가 틀렸습니다"})


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("auth")
    return response


# ──────────────────────────────────────────
# 대시보드 메인 (초안 목록)
# ──────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    pending = store.list_pending()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "drafts": pending,
    })


# ──────────────────────────────────────────
# 초안 상세 보기
# ──────────────────────────────────────────

@app.get("/draft/{draft_id}", response_class=HTMLResponse)
async def draft_detail(request: Request, draft_id: str):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    draft = store.load_draft(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="초안을 찾을 수 없습니다")

    return templates.TemplateResponse("draft.html", {
        "request": request,
        "draft": draft,
    })


# ──────────────────────────────────────────
# 발행
# ──────────────────────────────────────────

@app.post("/draft/{draft_id}/publish")
async def publish_draft(
    request: Request,
    draft_id: str,
    title: str = Form(...),
    content: str = Form(...),
):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    draft = store.load_draft(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="초안을 찾을 수 없습니다")

    wp_url = os.environ.get("WP_URL", "")
    wp_user = os.environ.get("WP_USERNAME", "")
    wp_pass = os.environ.get("WP_APP_PASSWORD", "")

    if not all([wp_url, wp_user, wp_pass]):
        # 워드프레스 미설정 시 상태만 업데이트
        draft["rewritten_title"] = title
        draft["rewritten_content"] = content
        draft["status"] = "published"
        store.save_draft(draft)
        return RedirectResponse("/?msg=saved", status_code=302)

    post = publish_post(
        wp_url=wp_url,
        username=wp_user,
        app_password=wp_pass,
        title=title,
        content=content,
        tags=["복지", "정부지원", draft.get("department", "")],
    )

    if post:
        draft["rewritten_title"] = title
        draft["rewritten_content"] = content
        draft["status"] = "published"
        draft["wp_post_id"] = post.get("id")
        store.save_draft(draft)

        # 텔레그램 알림 (선택)
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if bot_token and chat_id:
            send_message(bot_token, chat_id, f"✅ 발행 완료: {title}\n{post.get('link', '')}")

        return RedirectResponse("/?msg=published", status_code=302)

    return RedirectResponse(f"/draft/{draft_id}?error=1", status_code=302)


# ──────────────────────────────────────────
# 거절
# ──────────────────────────────────────────

@app.post("/draft/{draft_id}/reject")
async def reject_draft(request: Request, draft_id: str):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    store.update_status(draft_id, "rejected")
    return RedirectResponse("/", status_code=302)
