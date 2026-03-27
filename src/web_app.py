"""
복지소식 웹 대시보드
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


# ── 로그인 ──────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    if password == DASHBOARD_PASSWORD:
        response = RedirectResponse("/", status_code=302)
        response.set_cookie("auth", DASHBOARD_PASSWORD, max_age=60 * 60 * 24 * 30)
        return response
    return templates.TemplateResponse(request=request, name="login.html", context={"error": "비밀번호가 틀렸습니다"})


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("auth")
    return response


# ── 대시보드 메인 ────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, category: str = "전체", status: str = "전체"):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    all_drafts = store.list_all()

    # 카테고리 목록 수집
    category_set = set()
    for d in all_drafts:
        for cat in d.get("categories", "").split(","):
            cat = cat.strip()
            if cat:
                category_set.add(cat)
    categories = ["전체"] + sorted(category_set)

    # 필터링
    filtered = all_drafts
    if category != "전체":
        filtered = [d for d in filtered if category in d.get("categories", "")]
    if status != "전체":
        filtered = [d for d in filtered if d.get("status") == status]

    return templates.TemplateResponse(request=request, name="index.html", context={
        "drafts": filtered,
        "categories": categories,
        "current_category": category,
        "current_status": status,
        "total": len(all_drafts),
        "count_pending": sum(1 for d in all_drafts if d.get("status") == "pending"),
        "count_written": sum(1 for d in all_drafts if d.get("status") == "written"),
        "count_published": sum(1 for d in all_drafts if d.get("status") == "published"),
    })


# ── 글 상세/편집 ─────────────────────────────

@app.get("/draft/{draft_id}", response_class=HTMLResponse)
async def draft_detail(request: Request, draft_id: str):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    draft = store.load_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="글을 찾을 수 없습니다")

    return templates.TemplateResponse(request=request, name="draft.html", context={
        "draft": draft,
        "msg": request.query_params.get("msg", ""),
        "error": request.query_params.get("error", ""),
    })


# ── 글 저장 ──────────────────────────────────

@app.post("/draft/{draft_id}/save")
async def save_draft(
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
        raise HTTPException(status_code=404)

    draft["rewritten_title"] = title
    draft["rewritten_content"] = content
    draft["status"] = "written"
    store.save_draft(draft)

    return RedirectResponse(f"/draft/{draft_id}?msg=저장되었습니다", status_code=302)


# ── 발행 ─────────────────────────────────────

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
        raise HTTPException(status_code=404)

    wp_url = os.environ.get("WP_URL", "")
    wp_user = os.environ.get("WP_USERNAME", "")
    wp_pass = os.environ.get("WP_APP_PASSWORD", "")

    if not all([wp_url, wp_user, wp_pass]):
        draft["rewritten_title"] = title
        draft["rewritten_content"] = content
        draft["status"] = "published"
        store.save_draft(draft)
        return RedirectResponse("/?msg=저장완료(워드프레스 미연결)", status_code=302)

    post = publish_post(
        wp_url=wp_url, username=wp_user, app_password=wp_pass,
        title=title, content=content,
        tags=["복지", "정부지원", draft.get("department", "")],
    )

    if post:
        draft["rewritten_title"] = title
        draft["rewritten_content"] = content
        draft["status"] = "published"
        draft["wp_post_id"] = post.get("id")
        store.save_draft(draft)

        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if bot_token and chat_id:
            send_message(bot_token, chat_id, f"✅ 발행: {title}\n{post.get('link', '')}")

        return RedirectResponse("/?msg=발행완료", status_code=302)

    return RedirectResponse(f"/draft/{draft_id}?error=발행에 실패했습니다", status_code=302)


# ── 제외 ─────────────────────────────────────

@app.post("/draft/{draft_id}/exclude")
async def exclude_draft(request: Request, draft_id: str):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    store.update_status(draft_id, "excluded")
    return RedirectResponse("/", status_code=302)
