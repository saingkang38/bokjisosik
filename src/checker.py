"""
생성된 글을 발행 전에 기계적으로 검수합니다.

핵심 검사: 글에 등장하는 숫자(금액·날짜·나이 등)가
정책 원문 데이터에 실제로 존재하는지 대조합니다.
AI가 숫자를 지어내거나 바꿨다면 여기서 걸립니다.

결과는 [{"name", "level", "detail"}] 형태이며
level은 "pass" / "warn" / "fail" 중 하나입니다.
"""

import re

# 숫자 + 단위 패턴 (예: 300,000원 / 20만원 / 65세 / 2025년 / 50%)
_NUMBER_PATTERN = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:원|만원|억원|천원|%|퍼센트|세|년|월|일|명|가구|인|회|개월|주|시간|점|㎡|평|호|건)"
)

# 필수 소제목 (띄어쓰기 변형 허용)
_REQUIRED_SECTIONS = [
    ("지원 대상", r"지원\s*대상"),
    ("지원 내용", r"지원\s*내용"),
    ("신청 방법", r"신청\s*방법"),
]


def _normalize(text: str) -> str:
    """숫자 비교용 정규화: 쉼표/공백 제거."""
    return text.replace(",", "").replace(" ", "")


def _extract_numbers(text: str) -> list[str]:
    return [m.group(0).strip() for m in _NUMBER_PATTERN.finditer(text)]


def _keyword_variants(draft: dict) -> list[str]:
    """정책 원문 제목에서 핵심 키워드(정책 이름)와 그 첫 단어를 뽑는다.

    예: "(산재근로자)사회심리재활지원" → ["산재근로자사회심리재활지원", "사회심리재활지원"]
    SEO 위치 검사에서 이 중 하나라도 매칭되면 키워드가 있는 것으로 본다.
    """
    raw = draft.get("title", "")
    raw = re.sub(r"[\(\[（【].*?[\)\]）】]", " ", raw)  # 괄호 안 수식어 제거
    full = _normalize(raw)
    variants = []
    if len(full) >= 2:
        variants.append(full)
    tokens = [t for t in re.split(r"[\s,·/~-]+", raw.strip()) if len(t) >= 2]
    for t in tokens:
        tn = _normalize(t)
        if tn and tn not in variants:
            variants.append(tn)
    return variants


def _first_paragraph(body: str) -> str:
    """본문에서 첫 소제목(##) 이전의 도입부만 잘라낸다."""
    lines = []
    for line in body.strip().splitlines():
        if line.strip().startswith("#"):
            break
        lines.append(line)
    return "\n".join(lines).strip() or body.strip()[:200]


def run_checks(draft: dict, title: str, body: str, banned_words: list[str]) -> list[dict]:
    """글을 검수하고 검사 결과 목록을 반환합니다."""
    results = []

    source = " ".join([
        draft.get("title", ""),
        draft.get("target", ""),
        draft.get("criteria", ""),
        draft.get("content", ""),
        draft.get("summary", ""),
        draft.get("apply_method", ""),
        draft.get("contact", ""),
    ])
    source_normalized = _normalize(source)
    article_text = f"{title}\n{body}"

    # 1. 숫자 대조 (가장 중요)
    unmatched = []
    for token in set(_extract_numbers(article_text)):
        if _normalize(token) not in source_normalized:
            unmatched.append(token)

    if unmatched:
        results.append({
            "name": "숫자 원문 대조",
            "level": "fail",
            "detail": "원문 데이터에 없는 숫자가 글에 있습니다. 직접 확인하세요: " + ", ".join(sorted(unmatched)),
        })
    else:
        found = len(set(_extract_numbers(article_text)))
        results.append({
            "name": "숫자 원문 대조",
            "level": "pass",
            "detail": f"글의 숫자 {found}개가 모두 원문 데이터와 일치합니다." if found else "글에 검사할 숫자가 없습니다.",
        })

    # 2. 금지 표현
    found_banned = [w for w in banned_words if w and w in article_text]
    if found_banned:
        results.append({
            "name": "금지 표현",
            "level": "fail",
            "detail": "금지 표현이 사용되었습니다: " + ", ".join(found_banned),
        })
    else:
        results.append({
            "name": "금지 표현",
            "level": "pass",
            "detail": f"금지 표현 {len(banned_words)}개 목록 기준 통과.",
        })

    # 3. 필수 섹션
    missing = [name for name, pattern in _REQUIRED_SECTIONS if not re.search(pattern, body)]
    if missing:
        results.append({
            "name": "글 구조",
            "level": "warn",
            "detail": "빠진 섹션: " + ", ".join(missing),
        })
    else:
        results.append({
            "name": "글 구조",
            "level": "pass",
            "detail": "필수 섹션(지원 대상·지원 내용·신청 방법)이 모두 있습니다.",
        })

    # 4. 제목 길이
    if not title.strip():
        results.append({"name": "제목", "level": "fail", "detail": "제목이 비어 있습니다."})
    elif len(title) > 40:
        results.append({
            "name": "제목",
            "level": "warn",
            "detail": f"제목이 {len(title)}자입니다. 40자 이내를 권장합니다 (검색 결과에서 잘릴 수 있음).",
        })
    else:
        results.append({"name": "제목", "level": "pass", "detail": f"제목 길이 {len(title)}자, 적절합니다."})

    # 5. 본문 분량
    body_length = len(body.strip())
    if body_length < 400:
        results.append({
            "name": "본문 분량",
            "level": "warn",
            "detail": f"본문이 {body_length}자로 짧습니다. 정보가 부족하지 않은지 확인하세요.",
        })
    else:
        results.append({"name": "본문 분량", "level": "pass", "detail": f"본문 {body_length}자."})

    # 6. SEO — 제목에 핵심 키워드가 앞부분에 있는가
    variants = _keyword_variants(draft)
    title_norm = _normalize(title)
    kw_pos = -1
    for v in variants:
        p = title_norm.find(v)
        if p != -1:
            kw_pos = p if kw_pos == -1 else min(kw_pos, p)
    if not variants:
        pass  # 원문 제목이 없으면 검사 생략
    elif kw_pos == -1:
        results.append({
            "name": "SEO 제목 키워드",
            "level": "warn",
            "detail": "제목에 정책 이름(핵심 키워드)이 보이지 않습니다. 검색 노출을 위해 정책명을 제목에 넣으세요.",
        })
    elif kw_pos <= max(2, len(title_norm) // 2):
        results.append({
            "name": "SEO 제목 키워드",
            "level": "pass",
            "detail": "핵심 키워드가 제목 앞부분에 있습니다 (검색 노출·클릭에 유리).",
        })
    else:
        results.append({
            "name": "SEO 제목 키워드",
            "level": "warn",
            "detail": "핵심 키워드가 제목 뒤쪽에 있습니다. 정책명을 제목 맨 앞으로 옮기는 것을 권장합니다.",
        })

    # 7. SEO — 도입 첫 문단에 핵심 키워드가 있는가
    if variants:
        intro_norm = _normalize(_first_paragraph(body))
        if any(v in intro_norm for v in variants):
            results.append({
                "name": "SEO 도입부 키워드",
                "level": "pass",
                "detail": "도입 첫 문단에 핵심 키워드가 들어 있습니다.",
            })
        else:
            results.append({
                "name": "SEO 도입부 키워드",
                "level": "warn",
                "detail": "도입 첫 문단에 정책 이름이 없습니다. 첫 2~3문장 안에 자연스럽게 넣으면 검색에 유리합니다.",
            })

    # 8. 출처 링크 확보 여부
    if draft.get("detail_link"):
        results.append({
            "name": "출처 링크",
            "level": "pass",
            "detail": "복지로 원문 링크가 있어 발행 시 자동으로 출처가 붙습니다.",
        })
    else:
        results.append({
            "name": "출처 링크",
            "level": "warn",
            "detail": "복지로 원문 링크가 없습니다. 출처 표기를 직접 확인하세요.",
        })

    return results


def summarize_checks(results: list[dict]) -> dict:
    """검사 결과 요약: {"pass": n, "warn": n, "fail": n, "ok": bool}"""
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for r in results:
        counts[r["level"]] = counts.get(r["level"], 0) + 1
    counts["ok"] = counts["fail"] == 0
    return counts
