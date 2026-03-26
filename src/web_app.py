"""
복지소식 웹 대시보드
"""

import os
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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
async def index(request: Request, category: str = "전체"):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    all_drafts = store.list_pending()

    # 카테고리 목록 수집
    category_set = set()
    for d in all_drafts:
        for cat in d.get("categories", "").split(","):
            cat = cat.strip()
            if cat:
                category_set.add(cat)
    categories = ["전체"] + sorted(category_set)

    # 카테고리 필터
    if category != "전체":
        filtered = [d for d in all_drafts if category in d.get("categories", "")]
    else:
        filtered = all_drafts

    return templates.TemplateResponse(request=request, name="index.html", context={
        "drafts": filtered,
        "categories": categories,
        "current_category": category,
        "total": len(all_drafts),
    })


# ── 초안 상세 ────────────────────────────────

@app.get("/draft/{draft_id}", response_class=HTMLResponse)
async def draft_detail(request: Request, draft_id: str):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    draft = store.load_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="초안을 찾을 수 없습니다")

    return templates.TemplateResponse(request=request, name="draft.html", context={
        "draft": draft,
        "msg": request.query_params.get("msg", ""),
        "error": request.query_params.get("error", ""),
    })


# ── 1단계: 초안 생성 ─────────────────────────

@app.post("/draft/{draft_id}/generate")
async def generate_draft(request: Request, draft_id: str):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    draft = store.load_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404)

    from src.rewriter import generate_draft as _generate
    result = _generate(draft, os.environ["ANTHROPIC_API_KEY"])

    draft["draft_content"] = result
    draft["status"] = "draft_generated"
    store.save_draft(draft)

    return RedirectResponse(f"/draft/{draft_id}?msg=초안이 생성되었습니다", status_code=302)


# ── 2단계: 초안 검수 ─────────────────────────

@app.post("/draft/{draft_id}/review")
async def review_draft(request: Request, draft_id: str):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    draft = store.load_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404)

    if not draft.get("draft_content"):
        return RedirectResponse(f"/draft/{draft_id}?error=초안을 먼저 생성해주세요", status_code=302)

    from src.rewriter import review_draft as _review
    result = _review(draft, draft["draft_content"], os.environ["ANTHROPIC_API_KEY"])

    draft["reviewed_content"] = result
    draft["status"] = "reviewed"
    store.save_draft(draft)

    return RedirectResponse(f"/draft/{draft_id}?msg=검수가 완료되었습니다", status_code=302)


# ── 이미지 생성 (준비중) ──────────────────────

@app.post("/draft/{draft_id}/image")
async def generate_image(request: Request, draft_id: str):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)
    return RedirectResponse(f"/draft/{draft_id}?msg=이미지 생성 기능은 준비 중입니다", status_code=302)


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
        return RedirectResponse("/?msg=saved", status_code=302)

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

        return RedirectResponse("/?msg=published", status_code=302)

    return RedirectResponse(f"/draft/{draft_id}?error=발행에 실패했습니다", status_code=302)


# ── 예약발행 ──────────────────────────────────

@app.post("/draft/{draft_id}/schedule")
async def schedule_draft(
    request: Request,
    draft_id: str,
    scheduled_at: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    draft = store.load_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404)

    draft["scheduled_at"] = scheduled_at
    draft["rewritten_title"] = title
    draft["rewritten_content"] = content
    draft["status"] = "scheduled"
    store.save_draft(draft)

    return RedirectResponse(f"/?msg={scheduled_at}에 예약되었습니다", status_code=302)


# ── 제외 ─────────────────────────────────────

@app.post("/draft/{draft_id}/exclude")
async def exclude_draft(request: Request, draft_id: str):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    store.update_status(draft_id, "excluded")
    return RedirectResponse("/", status_code=302)
