"""
bokjisosik 메인 실행 파일

모드:
  python main.py --fetch      : 정책 수집 + 저장 (GitHub Actions에서 매일 실행)
  python main.py --generate   : 미작성 정책 AI 초안 자동 생성 + 검수 (수집 직후 실행)
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()


def run_fetch():
    """전체 페이지 순환하며 모든 복지 정책 수집 → 저장."""
    from src.fetcher import fetch_welfare_policies, normalize_policy
    from src.github_store import GitHubStore
    from src.notifier import send_draft_notification, send_message

    api_key = os.environ.get("PUBLIC_DATA_API_KEY", "")
    github_token = os.environ["GITHUB_TOKEN"]
    github_repo = os.environ["GITHUB_REPO"]
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    store = GitHubStore(token=github_token, repo=github_repo)

    print("=== 복지 정책 수집 시작 ===")

    if not api_key:
        print("[main] PUBLIC_DATA_API_KEY 없음 - 건너뜀")
        send_message(bot_token, chat_id, "⚠️ 공공데이터 API 키가 없어 수집을 건너뜁니다.")
        return

    new_count = 0
    page = 1

    while True:
        raw_items = fetch_welfare_policies(api_key, num_rows=100, page=page)
        if not raw_items:
            print(f"[main] {page}페이지 데이터 없음 - 수집 완료")
            break

        print(f"[main] {page}페이지 수집: {len(raw_items)}건")

        for item in raw_items:
            draft = normalize_policy(item)
            draft_id = draft["id"]

            existing = store.load_draft(draft_id)
            if existing:
                print(f"[main] 이미 존재: {draft_id}")
                continue

            if store.save_draft(draft):
                send_draft_notification(bot_token, chat_id, draft)
                new_count += 1

        page += 1

    print(f"=== 완료: {new_count}개 새 초안 생성 ===")

    if new_count == 0:
        send_message(bot_token, chat_id, "ℹ️ 새로운 복지 정책이 없습니다.")


def run_generate():
    """미작성(pending) 정책에 대해 AI 초안을 자동 생성하고 검수합니다.

    한 번 실행에 AUTO_GENERATE_LIMIT개(기본 5개)까지만 생성합니다.
    (API 비용과 실행 시간을 통제하기 위한 상한)
    """
    from src.github_store import GitHubStore
    from src.rewriter import generate_article, available_engine
    from src.checker import run_checks, summarize_checks
    from src.guidelines import load_guidelines_text, parse_guidelines
    from src.notifier import send_message

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    github_token = os.environ["GITHUB_TOKEN"]
    github_repo = os.environ["GITHUB_REPO"]
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    dashboard_url = os.environ.get("DASHBOARD_URL", "").rstrip("/")
    limit = int(os.environ.get("AUTO_GENERATE_LIMIT", "5"))

    engine = available_engine(api_key)
    if not engine:
        print("[main] 생성 엔진 없음 (API 키도, Claude Code도 없음) - AI 생성 건너뜀")
        send_message(bot_token, chat_id, "⚠️ 생성 엔진이 없어 AI 초안 생성을 건너뜁니다. (API 키 또는 Claude Code 필요)")
        return
    print(f"[main] 생성 엔진: {engine}")

    store = GitHubStore(token=github_token, repo=github_repo)
    banned_words = parse_guidelines(load_guidelines_text(store))["banned_words"]

    pending = [d for d in store.list_all()
               if d.get("status") == "pending" and not d.get("rewritten_content")]
    pending.sort(key=lambda x: x.get("fetched_at", ""))
    targets = pending[:limit]

    print(f"=== AI 초안 자동 생성 시작: 대기 {len(pending)}건 중 {len(targets)}건 처리 ===")

    generated, failed = 0, 0
    for draft in targets:
        result = generate_article(draft, api_key, store=store)

        if result["error"]:
            failed += 1
            print(f"[main] 생성 실패: {draft.get('title', '')} - {result['error']}")
            continue

        checks = run_checks(draft, result["title"], result["body"], banned_words)
        summary = summarize_checks(checks)

        draft["rewritten_title"] = result["title"]
        draft["rewritten_content"] = result["body"]
        draft["review_notes"] = result["notes"]
        draft["check_results"] = checks
        draft["status"] = "written"
        store.save_draft(draft)
        generated += 1

        icon = "✅" if summary["ok"] else "❌"
        link = f"\n{dashboard_url}/draft/{draft['id']}" if dashboard_url else ""
        send_message(
            bot_token, chat_id,
            f"🤖 AI 초안 완성: {result['title']}\n"
            f"자동 검수 {icon} 통과 {summary['pass']} · 주의 {summary['warn']} · 실패 {summary['fail']}\n"
            f"대시보드에서 확인 후 워드프레스에 올려주세요.{link}",
        )

    print(f"=== 완료: 생성 {generated}건, 실패 {failed}건, 남은 대기 {len(pending) - len(targets)}건 ===")

    if generated == 0 and failed == 0:
        print("[main] 생성할 미작성 정책이 없습니다.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python main.py --fetch | --generate")
        sys.exit(1)

    if sys.argv[1] == "--fetch":
        run_fetch()
    elif sys.argv[1] == "--generate":
        run_generate()
    else:
        print(f"알 수 없는 모드: {sys.argv[1]}")
        sys.exit(1)
