"""
복지소식 웹 대시보드
"""

import hashlib
import os

from dotenv import load_dotenv

load_dotenv()  # 맥북 등 로컬 서버에서 .env 파일의 설정을 읽음
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from src.github_store import GitHubStore
from src.wordpress import publish_post, build_post_html
from src.notifier import send_message
from src.rewriter import generate_article, generate_bundle, available_engine
from src.checker import run_checks, summarize_checks
from src.guidelines import load_guidelines_text, save_guidelines_text, parse_guidelines

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
        "count_wp_draft": sum(1 for d in all_drafts if d.get("status") == "wp_draft"),
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


# ── AI 초안 생성 ─────────────────────────────

@app.post("/draft/{draft_id}/generate")
def generate_ai_draft(request: Request, draft_id: str, extra_source: str = Form("")):
    # sync 함수로 두면 FastAPI가 스레드풀에서 실행해,
    # 생성이 오래 걸려도 대시보드의 다른 화면이 멈추지 않는다
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not available_engine(api_key):
        return RedirectResponse(f"/draft/{draft_id}?error=생성 엔진이 없습니다. API 키를 설정하거나 Claude Code가 설치된 컴퓨터에서 실행하세요", status_code=302)

    store = get_store()
    draft = store.load_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404)

    # 붙여넣은 규정/공고문 원문을 저장해두고 생성에 활용 (깊이 보강)
    draft["extra_source"] = extra_source

    result = generate_article(draft, api_key, store=store)
    if result["error"]:
        return RedirectResponse(f"/draft/{draft_id}?error=AI 생성 실패: {result['error'][:150]}", status_code=302)

    # 자동 검수
    banned = parse_guidelines(load_guidelines_text(store))["banned_words"]
    checks = run_checks(draft, result["title"], result["body"], banned)
    summary = summarize_checks(checks)

    draft["rewritten_title"] = result["title"]
    draft["rewritten_content"] = result["body"]
    draft["review_notes"] = result["notes"]
    draft["check_results"] = checks
    draft["status"] = "written"
    store.save_draft(draft)

    msg = f"AI 초안이 생성되었습니다 (검수: 통과 {summary['pass']} · 주의 {summary['warn']} · 실패 {summary['fail']})"
    return RedirectResponse(f"/draft/{draft_id}?msg={msg}", status_code=302)


# ── 워드프레스 초안 업로드 ────────────────────

@app.post("/draft/{draft_id}/wp-draft")
async def upload_wp_draft(
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
        return RedirectResponse(f"/draft/{draft_id}?error=워드프레스 연결 정보(WP_URL 등)가 설정되지 않았습니다", status_code=302)

    html = build_post_html(content, draft.get("detail_link", ""))
    post = publish_post(
        wp_url=wp_url, username=wp_user, app_password=wp_pass,
        title=title, content=html, status="draft",
        tags=["복지", "정부지원", draft.get("department", "")],
    )

    if not post:
        return RedirectResponse(f"/draft/{draft_id}?error=워드프레스 초안 업로드에 실패했습니다", status_code=302)

    draft["rewritten_title"] = title
    draft["rewritten_content"] = content
    draft["status"] = "wp_draft"
    draft["wp_post_id"] = post.get("id")
    store.save_draft(draft)

    return RedirectResponse(f"/draft/{draft_id}?msg=워드프레스 초안함에 올라갔습니다. 관리자 화면에서 확인 후 발행하세요", status_code=302)


# ── 지침 관리 ─────────────────────────────────

@app.get("/guidelines", response_class=HTMLResponse)
async def guidelines_page(request: Request):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    text = load_guidelines_text(store)
    return templates.TemplateResponse(request=request, name="guidelines.html", context={
        "guidelines": text,
        "msg": request.query_params.get("msg", ""),
        "error": request.query_params.get("error", ""),
    })


@app.post("/guidelines")
async def save_guidelines(request: Request, content: str = Form(...)):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    # 필수 섹션이 있는지 확인 (없으면 AI 생성이 멈추므로 저장 거부)
    parsed = parse_guidelines(content)
    if not parsed["draft"] or not parsed["review"]:
        return RedirectResponse("/guidelines?error=저장 실패: '## 1차 초안 생성 프롬프트'와 '## 2단계 검수 프롬프트' 제목은 지우면 안 됩니다", status_code=302)

    store = get_store()
    if save_guidelines_text(content, store):
        return RedirectResponse("/guidelines?msg=저장되었습니다. 다음 글부터 바로 적용됩니다", status_code=302)
    return RedirectResponse("/guidelines?error=저장에 실패했습니다", status_code=302)


# ── 상황별 묶음글 ─────────────────────────────

@app.get("/bundles", response_class=HTMLResponse)
async def bundles_page(request: Request):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    store = get_store()
    all_drafts = store.list_all()

    # 카테고리별로 묶을 수 있는 정책 개수 집계 (제외/묶음글 자체는 제외)
    cats = {}
    for d in all_drafts:
        if d.get("is_bundle"):
            continue
        for cat in d.get("categories", "").split(","):
            cat = cat.strip()
            if cat:
                cats[cat] = cats.get(cat, 0) + 1
    categories = sorted(cats.items(), key=lambda x: -x[1])

    return templates.TemplateResponse(request=request, name="bundles.html", context={
        "categories": categories,
        "msg": request.query_params.get("msg", ""),
        "error": request.query_params.get("error", ""),
    })


@app.post("/bundles/generate")
def generate_bundle_article(request: Request, category: str = Form(...)):
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not available_engine(api_key):
        return RedirectResponse("/bundles?error=생성 엔진이 없습니다", status_code=302)

    store = get_store()
    members = [
        d for d in store.list_all()
        if not d.get("is_bundle") and category in d.get("categories", "")
    ]
    if len(members) < 2:
        return RedirectResponse(f"/bundles?error={category} 카테고리에 묶을 정책이 2개 이상 필요합니다", status_code=302)

    members = members[:12]  # 너무 많으면 상한
    policies = [{
        "title": m.get("title", ""),
        "summary": m.get("summary", ""),
        "content": m.get("content", ""),
        "target": m.get("target", ""),
        "link": m.get("detail_link", ""),
    } for m in members]

    result = generate_bundle(category, policies, api_key, store=store)
    if result["error"]:
        return RedirectResponse(f"/bundles?error=묶음글 생성 실패: {result['error'][:120]}", status_code=302)

    # 검수용 원본: 멤버 정책들의 데이터를 합쳐 숫자 대조가 되게 한다
    merged_source = {
        "title": category,
        "target": " ".join(m.get("target", "") for m in members),
        "content": " ".join(m.get("content", "") for m in members),
        "summary": " ".join(m.get("summary", "") for m in members),
        "criteria": "", "apply_method": "", "contact": "",
        "detail_link": "",
    }
    banned = parse_guidelines(load_guidelines_text(store))["banned_words"]
    checks = run_checks(merged_source, result["title"], result["body"], banned)

    bundle_id = "bundle_" + hashlib.md5(category.encode()).hexdigest()[:8]
    bundle = store.load_draft(bundle_id) or {"id": bundle_id, "fetched_at": ""}
    bundle.update({
        "id": bundle_id,
        "is_bundle": True,
        "status": "written",
        "title": f"[묶음] {category}",
        "department": f"{len(members)}개 정책 묶음",
        "categories": category,
        "rewritten_title": result["title"],
        "rewritten_content": result["body"],
        "review_notes": result["notes"],
        "check_results": checks,
        "detail_link": "",
    })
    store.save_draft(bundle)
    return RedirectResponse(f"/draft/{bundle_id}?msg={category} 묶음글이 생성되었습니다", status_code=302)


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

    html = build_post_html(content, draft.get("detail_link", ""))
    post = publish_post(
        wp_url=wp_url, username=wp_user, app_password=wp_pass,
        title=title, content=html,
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
