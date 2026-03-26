"""
bokjisosik 메인 실행 파일

모드:
  python main.py --fetch   : 정책 수집 + 저장 (GitHub Actions에서 실행)
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
        raw_items = fetch_welfare_policies(api_key, num_rows=10, page=page)
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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python main.py --fetch")
        sys.exit(1)

    if sys.argv[1] == "--fetch":
        run_fetch()
    else:
        print(f"알 수 없는 모드: {sys.argv[1]}")
        sys.exit(1)
