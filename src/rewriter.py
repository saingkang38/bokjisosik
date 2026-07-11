"""
복지 정책 글을 2단계로 생성합니다.
1단계: 초안 생성 (지침의 "1차 초안 생성 프롬프트")
2단계: 원문 대조 검수 및 교정 (지침의 "2단계 검수 프롬프트")

생성 엔진은 두 가지를 지원합니다:
  - "api"         : Anthropic API 직접 호출 (ANTHROPIC_API_KEY 필요, 종량제 과금)
  - "claude_code" : 맥북 등에 설치된 Claude Code CLI 사용 (Max 요금제에 포함, 추가 비용 없음)

GENERATION_ENGINE 환경변수로 강제할 수 있고(auto/api/claude_code),
기본값 auto는 API 키가 있으면 api, 없으면 claude_code를 씁니다.

지침은 src/guidelines.py를 통해 읽습니다 (GitHub 우선, 로컬 fallback).
"""

import os
import re
import shutil
import subprocess
import time

from src.guidelines import load_guidelines_text, parse_guidelines

API_MODEL = "claude-sonnet-5"


# ── 엔진 선택 ─────────────────────────────────

def _find_claude_cli():
    """Claude Code 실행 파일을 찾습니다. launchd/cron에서는 PATH가 좁아서 직접 뒤져봅니다."""
    explicit = os.environ.get("CLAUDE_CODE_PATH", "")
    if explicit and os.path.exists(explicit):
        return explicit

    found = shutil.which("claude")
    if found:
        return found

    home = os.path.expanduser("~")
    for path in [
        os.path.join(home, ".claude", "local", "claude"),
        os.path.join(home, ".local", "bin", "claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ]:
        if os.path.exists(path):
            return path
    return None


def available_engine(api_key=""):
    """사용 가능한 생성 엔진을 반환합니다. ("api" / "claude_code" / None)"""
    engine = os.environ.get("GENERATION_ENGINE", "auto")

    if engine == "api":
        return "api" if api_key else None
    if engine == "claude_code":
        return "claude_code" if _find_claude_cli() else None

    # auto: API 키 우선, 없으면 Claude Code
    if api_key:
        return "api"
    if _find_claude_cli():
        return "claude_code"
    return None


# ── 엔진별 호출 ───────────────────────────────

def _call_api(api_key, system_prompt, user_content, max_tokens=4000):
    """Anthropic API 호출. 일시적 오류는 2회까지 재시도합니다."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    last_error = None

    for attempt in range(3):
        try:
            message = client.messages.create(
                model=API_MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
            return message.content[0].text
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            last_error = e
            print(f"[rewriter] API 오류 (시도 {attempt + 1}/3): {e}")
            time.sleep(10 * (attempt + 1))

    raise RuntimeError(f"Claude API 호출 실패: {last_error}")


def _call_claude_code(system_prompt, user_content):
    """Claude Code CLI를 headless 모드(-p)로 호출합니다. Max 구독 사용량에 포함됩니다."""
    cli = _find_claude_cli()
    if not cli:
        raise RuntimeError("Claude Code 실행 파일을 찾을 수 없습니다. (CLAUDE_CODE_PATH 설정 또는 claude 설치 필요)")

    model = os.environ.get("CLAUDE_CODE_MODEL", "sonnet")
    prompt = f"{system_prompt}\n\n---\n\n{user_content}"

    # 다른 Claude 세션/스크립트가 남긴 환경변수가 하위 Claude의 인증을 방해하지 않도록 제거
    # (Max 구독 로그인 정보는 환경변수가 아니라 홈 디렉토리 설정에서 읽으므로 영향 없음)
    clean_env = {
        k: v for k, v in os.environ.items()
        if not k.startswith("ANTHROPIC_") and not (k.startswith("CLAUDE") and k != "CLAUDE_CONFIG_DIR")
    }
    last_error = None

    for attempt in range(2):
        try:
            result = subprocess.run(
                [cli, "-p", "--model", model],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=900,
                env=clean_env,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
            last_error = (result.stderr or result.stdout or "출력 없음").strip()[:300]
            print(f"[rewriter] Claude Code 오류 (시도 {attempt + 1}/2): {last_error}")
        except subprocess.TimeoutExpired:
            last_error = "시간 초과 (15분)"
            print(f"[rewriter] Claude Code 시간 초과 (시도 {attempt + 1}/2)")
        time.sleep(10)

    raise RuntimeError(f"Claude Code 실행 실패: {last_error}")


# ── 글 생성 ───────────────────────────────────

def _source_text(draft):
    """정책 원문 데이터를 프롬프트용 텍스트로 만듭니다."""
    base = f"""[원문 데이터]
서비스명: {draft.get('title', '')}
소관부처: {draft.get('department', '')}
카테고리: {draft.get('categories', '')}
지원대상: {draft.get('target', '')}
선정기준: {draft.get('criteria', '')}
지원내용: {draft.get('content', '')}
서비스요약: {draft.get('summary', '')}
신청방법: {draft.get('apply_method', '')}
연락처: {draft.get('contact', '')}
복지로 원문 링크: {draft.get('detail_link', '')}
"""

    extra = (draft.get("extra_source") or "").strip()
    if extra:
        base += f"""
[추가 공식 자료 — 규정/공고문 원문]
아래는 이 정책의 공식 규정·공고문에서 가져온 더 상세한 자료다.
위 [원문 데이터]와 함께, 이 자료에 있는 사실(대상·금액·조건·절차)까지 활용해 더 깊고 정확한 글을 써라.
단, 여기에 없는 내용을 지어내지 마라. 사실 보존 원칙은 동일하게 적용된다.

{extra[:12000]}
"""
    return base


def _extract_tag(text, tag):
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def generate_article(draft, api_key=None, store=None):
    """
    정책 원문 데이터로 최종 글을 생성합니다.

    Returns:
        {
          "title": str,        # 최종 제목
          "body": str,         # 최종 본문 (마크다운)
          "notes": str,        # AI 검수 메모 (사람 확인용)
          "engine": str,       # 사용한 엔진 ("api" / "claude_code")
          "error": str|None,   # 실패 시 오류 메시지
        }
    """
    engine = available_engine(api_key or "")
    if not engine:
        return {"title": "", "body": "", "notes": "", "engine": "",
                "error": "생성 엔진이 없습니다. ANTHROPIC_API_KEY를 설정하거나, Claude Code가 설치된 컴퓨터에서 실행하세요."}

    guidelines = parse_guidelines(load_guidelines_text(store))
    if not guidelines["draft"] or not guidelines["review"]:
        return {"title": "", "body": "", "notes": "", "engine": engine,
                "error": "지침에서 프롬프트 섹션을 찾을 수 없습니다. 지침 관리 페이지에서 '## 1차 초안 생성 프롬프트'와 '## 2단계 검수 프롬프트' 제목이 있는지 확인하세요."}

    def call(system_prompt, user_content):
        if engine == "api":
            return _call_api(api_key, system_prompt, user_content)
        return _call_claude_code(system_prompt, user_content)

    source = _source_text(draft)

    try:
        # 1단계: 초안 생성
        print(f"[rewriter] 초안 생성 시작 ({engine}): {draft.get('title', '')}")
        first = call(guidelines["draft"], source)

        draft_title = _extract_tag(first, "title") or draft.get("title", "")
        draft_body = _extract_tag(first, "article") or first

        # 2단계: 원문 대조 검수
        print(f"[rewriter] 검수 시작 ({engine}): {draft_title}")
        review_input = f"{source}\n[1차 초안 제목]\n{draft_title}\n\n[1차 초안 본문]\n{draft_body}"
        second = call(guidelines["review"], review_input)

        final_title = _extract_tag(second, "title") or draft_title
        final_body = _extract_tag(second, "article") or draft_body
        notes = _extract_tag(second, "notes")

        return {"title": final_title, "body": final_body, "notes": notes, "engine": engine, "error": None}

    except Exception as e:
        print(f"[rewriter] 글 생성 실패: {e}")
        return {"title": "", "body": "", "notes": "", "engine": engine, "error": str(e)}


_BUNDLE_PROMPT = """너는 "복지소식" 블로그의 정보성 콘텐츠 작성 엔진이다.
여러 개의 복지 정책을 하나로 묶어, 특정 상황에 놓인 독자가 "나는 어떤 지원을 받을 수 있나"를 한 번에 파악하도록 돕는 '묶음 안내 글'을 쓴다.
이런 묶음 글은 개별 정책 글보다 검색·신뢰 면에서 가치가 크다. 여러 정책을 상황 중심으로 엮는 것이 핵심이다.

[최우선 원칙 — 사실 보존]
1. 아래 제공된 정책 목록의 정보만 사용한다. 없는 사실(금액·대상·조건)을 지어내지 마라.
2. 각 정책의 자세한 내용은 링크로 넘긴다. 이 글은 "어떤 지원이 있는지 한눈에 보여주고, 자세한 건 링크로" 안내하는 역할이다.
3. 금액·수치는 제공된 요약에 있는 것만, 원문 표기 그대로 쓴다.

[문체]
- "~합니다" 체. 옆에서 짚어주듯 따뜻하고 읽기 쉽게.
- 독자를 상황으로 부른다. 공공문서 말투 금지.
- 톤·공감은 자유롭게, 정책 사실은 정확하게.

[구조] 마크다운으로 쓰고 소제목은 ## 로 시작한다. (워드프레스에서 목차가 자동 생성된다)
1. 도입 (소제목 없이 3~4문장): 독자가 처한 상황으로 시작해, "이럴 때 받을 수 있는 지원을 한데 모았다"고 안내한다.
2. ## 한눈에 보기 : 정책 이름과 핵심 혜택을 마크다운 표로 정리한다.
3. 정책마다 ## 소제목 : 각 정책을 2~4문장으로 소개한다 — 누가 받는지, 무엇을 받는지, 그리고 반드시 "[자세히 보기](링크)" 형식으로 해당 정책 링크를 넣는다.
4. ## 어떤 것부터 신청할까요 : 상황별로 우선순위나 팁을 간단히 정리한다(제공된 정보 범위 내에서만).

[출력 형식] 태그 밖에 다른 말을 쓰지 마라.
<title>글 제목 (핵심 키워드를 앞에, 40자 이내)</title>
<article>
마크다운 본문
</article>
<notes>
- 사람이 확인해야 할 항목. 없으면 "없음".
</notes>
"""


def generate_bundle(theme, policies, api_key=None, store=None):
    """여러 정책을 하나의 상황별 묶음 안내 글로 생성한다.

    theme: 묶음 주제(예: "출산·육아 지원", "노인 돌봄")
    policies: [{"title","summary","target","link"}] 목록
    """
    engine = available_engine(api_key or "")
    if not engine:
        return {"title": "", "body": "", "notes": "", "engine": "",
                "error": "생성 엔진이 없습니다."}

    lines = [f"[묶음 주제] {theme}", "", "[포함할 정책 목록]"]
    for i, p in enumerate(policies, 1):
        lines.append(f"""
{i}. {p.get('title', '')}
   - 대상: {p.get('target', '')[:200]}
   - 요약: {p.get('summary', '') or p.get('content', '')[:300]}
   - 링크: {p.get('link', '')}""")
    user_content = "\n".join(lines)

    def call(system_prompt, content):
        if engine == "api":
            return _call_api(api_key, system_prompt, content, max_tokens=4000)
        return _call_claude_code(system_prompt, content)

    try:
        print(f"[rewriter] 묶음글 생성 시작 ({engine}): {theme} ({len(policies)}개 정책)")
        out = call(_BUNDLE_PROMPT, user_content)
        title = _extract_tag(out, "title") or f"{theme} 총정리"
        body = _extract_tag(out, "article") or out
        notes = _extract_tag(out, "notes")
        return {"title": title, "body": body, "notes": notes, "engine": engine, "error": None}
    except Exception as e:
        print(f"[rewriter] 묶음글 생성 실패: {e}")
        return {"title": "", "body": "", "notes": "", "engine": engine, "error": str(e)}
