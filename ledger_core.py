"""당근과 채찍 가계부 — 계산·데이터 로직 (Streamlit 화면과 분리).

app.js 1~4절을 Python으로 옮긴 것이다. 모든 함수는 상태 dict(state)를 직접 받는다.
날짜는 "YYYY-MM-DD" 문자열로 저장하고, "오늘"은 today()로만 얻는다.
"""

from __future__ import annotations

import copy
import math
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ============================================================
# 1. 상수
# ============================================================

STORAGE_KEY = "ledger_v1"
BACKUP_KEY_PREFIX = "ledger_backup_"
SCHEMA_VERSION = 1
DEFAULT_CYCLE_START_DAY = 25
MAX_AMOUNT = 999_999_999_999  # 12자리, 최대 9,999억 원대
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]  # date.weekday() 순서
TIMEZONE = ZoneInfo("Asia/Seoul")  # 서버(Streamlit Cloud)는 UTC라서 한국 날짜로 맞춘다

# 대분류 색상 팔레트 (그래프용, 순서대로 배정)
CATEGORY_COLORS = [
    "#F4A261", "#2A9D8F", "#E76F51", "#8AB17D",
    "#6D597A", "#457B9D", "#B5838D", "#E9C46A",
]

# 자주 쓰는 이모지 (F-203)
EMOJI_CHOICES = [
    "🍚", "🍜", "🍔", "☕", "🍰", "🍺", "🏠", "🧴", "🛒", "🚌",
    "🚕", "🚗", "⛽", "✈️", "🏥", "💊", "💪", "📚", "👔", "💄",
    "🎁", "🎉", "🎮", "🎨", "🎬", "🎵", "📱", "💻", "🐶", "⛺",
]
DEFAULT_NEW_EMOJI = "🏷️"
MAX_NAME_LENGTH = 20

# PRD 4.2 기본 지출 카테고리 (대분류 > 소분류)
DEFAULT_EXPENSE_CATEGORIES = [
    {"id": "cat_living", "name": "생활비", "emoji": "🏠", "subs": [
        {"id": "sub_transit", "name": "대중교통", "emoji": "🚌"},
        {"id": "sub_taxi", "name": "택시", "emoji": "🚕"},
        {"id": "sub_car", "name": "자동차", "emoji": "🚗"},
        {"id": "sub_food", "name": "식비", "emoji": "🍚"},
        {"id": "sub_goods", "name": "생활용품", "emoji": "🧴"},
    ]},
    {"id": "cat_self", "name": "자기관리", "emoji": "💪", "subs": [
        {"id": "sub_health", "name": "건강", "emoji": "🏥"},
        {"id": "sub_growth", "name": "성장", "emoji": "📚"},
        {"id": "sub_dignity", "name": "품위유지", "emoji": "👔"},
    ]},
    {"id": "cat_relation", "name": "관계", "emoji": "🤝", "subs": [
        {"id": "sub_wedding", "name": "축의금", "emoji": "💒"},
        {"id": "sub_condolence", "name": "부의금", "emoji": "🕯️"},
        {"id": "sub_anniversary", "name": "기념일", "emoji": "🎂"},
        {"id": "sub_meetup", "name": "모임", "emoji": "🍻"},
        {"id": "sub_gift", "name": "선물", "emoji": "🎁"},
    ]},
    {"id": "cat_leisure", "name": "여가", "emoji": "🎈", "subs": [
        {"id": "sub_travel", "name": "여행", "emoji": "✈️"},
        {"id": "sub_hobby", "name": "취미", "emoji": "🎨"},
        {"id": "sub_luxury", "name": "사치", "emoji": "💎"},
    ]},
    {"id": "cat_fixed", "name": "고정지출", "emoji": "📌", "subs": [
        {"id": "sub_telecom", "name": "통신비", "emoji": "📱"},
        {"id": "sub_watcha", "name": "왓챠", "emoji": "🎬"},
        {"id": "sub_ytmusic", "name": "유튜브뮤직", "emoji": "🎵"},
        {"id": "sub_welaaa", "name": "윌라", "emoji": "🎧"},
        {"id": "sub_duolingo", "name": "듀오링고", "emoji": "🦉"},
    ]},
    {"id": "cat_church", "name": "교회", "emoji": "⛪", "subs": [
        {"id": "sub_offering", "name": "헌금", "emoji": "🙏"},
        {"id": "sub_fellowship", "name": "관계", "emoji": "☕"},
    ]},
    # 기타는 소분류가 없고 삭제할 수 없다 (F-205)
    {"id": "cat_etc", "name": "기타", "emoji": "📦", "subs": []},
]

ETC_CATEGORY_ID = "cat_etc"

# PRD 4.3 계좌 종류. needsDates: 가입일·만기일 필수 / monthly: 월 납입액·회차 / interest: 이자 방식 선택
ACCOUNT_KINDS = {
    "fixed_savings": {"name": "정기적금", "needsDates": True, "monthly": True, "interest": True},
    "free_savings": {"name": "자유적금", "needsDates": True, "monthly": False, "interest": True},
    "fixed_deposit": {"name": "정기예금", "needsDates": True, "monthly": False, "interest": True},
    "parking": {"name": "파킹통장", "needsDates": False, "monthly": False, "interest": False},
    "etc": {"name": "기타", "needsDates": False, "monthly": False, "interest": False},
}

INTEREST_NAMES = {"simple": "단리", "monthly_compound": "월복리"}
MATURITY_SOON_DAYS = 30

# PRD 4.1 F-104 수입 카테고리
DEFAULT_INCOME_CATEGORIES = [
    {"id": "inc_salary", "name": "월급", "emoji": "💰"},
    {"id": "inc_side", "name": "부수입", "emoji": "🎁"},
    {"id": "inc_etc", "name": "기타", "emoji": "💸"},
]

# PRD 4.7.2 사용률 구간. 사용률이 max 이하이면 그 점수 (경계값은 더 좋은 점수)
SCORE_STEPS = [(0.70, 5), (0.90, 4), (1.00, 3), (1.15, 2), (1.30, 1)]
INCOME_BASELINE_RATIO = 0.7  # 예산이 없을 때 수입의 70%를 기준으로 쓴다

# 대분류별 한 줄 코멘트. 인덱스 = 점수(0~5). {sub}는 가장 많이 쓴 소분류
CATEGORY_COMMENTS = [
    "{sub} 주범이에요.",
    "{sub} 너무 많이 나갔어요.",
    "살짝 넘었어요. {sub} 조금만 줄여 봐요.",
    "예산 안에서 잘 썼어요.",
    "알뜰하게 잘 지켰어요.",
    "아주 훌륭해요!",
]

# PRD 4.7.2 당근/채찍 메시지. 인덱스 = 점수(0~5). 각 단계 첫 문구가 대표 문구
# (항상 표시), 나머지는 주기마다 하나를 골라 한마디로 덧붙인다
MESSAGES = [
    [
        "다음 달 거지로 살아야 한다. 🥲 지갑을 봉인하세요.",
        "통장이 울고 있어요. 다음 달은 숨만 쉬고 살아요.",
        "이번 달은 카드가 주인공이었네요. 다음 달은 지갑이 쉴 차례예요.",
    ],
    [
        "다음 달은 허리띠를 졸라매야 해요.",
        "예산을 꽤 넘었어요. 다음 달엔 꼭 필요한 것만 사요.",
    ],
    [
        "살짝 넘었어요. 다음 달엔 커피 한 잔부터 줄여볼까요?",
        "아깝게 넘었어요. 조금만 더 아끼면 당근이 늘어나요.",
    ],
    [
        "예산 안에서 딱 맞게 썼어요. 나쁘지 않아요!",
        "계획대로 썼어요. 이 정도면 합격이에요.",
    ],
    [
        "훌륭해요. 이 페이스면 저축이 쑥쑥 늘어요.",
        "알뜰하게 잘 살았어요. 조금만 더 하면 만점이에요.",
    ],
    [
        "이번 달은 아주 합리적으로 살았다! 스스로에게 작은 상을 줘도 좋아요.",
        "완벽한 한 달이었어요. 당근 다섯 개 받으세요! 🥕",
        "이 정도면 가계부의 신이에요.",
    ],
]

# ============================================================
# 2. 유틸
# ============================================================

_today_override: str | None = None


def set_today_override(value: str | None) -> bool:
    """?today=YYYY-MM-DD 시간 여행. 올바른 날짜면 True."""
    global _today_override
    _today_override = value if value and parse_date_str(value) else None
    return _today_override is not None


def is_today_overridden() -> bool:
    return _today_override is not None


def today() -> str:
    """앱 전체에서 "오늘"은 이 함수로만 얻는다 (한국 시간 기준)."""
    if _today_override:
        return _today_override
    return datetime.now(TIMEZONE).date().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_date_str(text) -> date | None:
    """"YYYY-MM-DD" → date. 형식이나 날짜가 틀리면 None."""
    if not isinstance(text, str) or len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        return None


def js_round(x: float) -> int:
    """JS Math.round와 같게 반올림한다 (Python round는 짝수 쪽으로 반올림)."""
    return math.floor(x + 0.5)


def format_won(amount) -> str:
    """1234567 → "₩1,234,567", -500 → "−₩500"."""
    sign = "−" if amount < 0 else ""
    return f"{sign}₩{abs(int(amount)):,}"


def parse_amount(text) -> int:
    """금액 글자 → 정수. 숫자가 아닌 글자(쉼표 등)는 무시한다."""
    digits = "".join(ch for ch in str(text) if ch.isascii() and ch.isdigit())[:12]
    return int(digits) if digits else 0


def percent(ratio: float) -> str:
    return f"{js_round(ratio * 100)}%"


def _is_regional(ch: str) -> bool:
    return 0x1F1E6 <= ord(ch) <= 0x1F1FF


def first_grapheme(text) -> str:
    """글자 하나(이모지는 국기·피부색·ZWJ 조합까지 한 덩어리)만 꺼낸다."""
    s = str(text).strip()
    if not s:
        return ""
    i = 1
    if _is_regional(s[0]) and len(s) > 1 and _is_regional(s[1]):
        return s[:2]
    while i < len(s):
        ch = s[i]
        code = ord(ch)
        if code == 0x200D and i + 1 < len(s):  # ZWJ: 다음 글자까지 붙인다
            i += 2
        elif (code in (0xFE0E, 0xFE0F, 0x20E3) or 0x1F3FB <= code <= 0x1F3FF
              or 0xE0020 <= code <= 0xE007F or unicodedata.combining(ch)):
            i += 1
        else:
            break
    return s[:i]


def weekday_of(date_str: str) -> str:
    return WEEKDAYS[parse_date_str(date_str).weekday()]


def gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4()}"


def add_months(d: date, months: int, day: int | None = None) -> date:
    """몇 달 뒤(음수면 전) 같은 날. 그 달에 없는 날이면 말일로 맞춘다."""
    index = d.year * 12 + (d.month - 1) + months
    y, m = divmod(index, 12)
    m += 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(day if day is not None else d.day, last))


def diff_days(a: date, b: date) -> int:
    return (b - a).days


def months_between(a: date, b: date) -> int:
    """a일부터 b일까지 꽉 찬 개월 수 (2026-01-25 → 2027-01-25 = 12)."""
    return (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)


def with_josa(word: str, consonant: str, vowel: str) -> str:
    """받침 여부에 따라 조사를 고른다: with_josa('사치', '이', '가') → "사치가"."""
    code = ord(word[-1]) - 0xAC00 if word else -1
    has_final = 0 <= code <= 11171 and code % 28 != 0
    return f"{word}{consonant if has_final else vowel}"


def seeded_pick(items: list, seed: str):
    """같은 주기·점수면 새로고침해도 같은 문구가 나오도록 label로 고정된 난수를 만든다."""
    h = 0
    for ch in seed:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return items[h % len(items)]


# ============================================================
# 3. 상태와 데이터 변경
# ============================================================

def create_initial_state() -> dict:
    categories = []
    subcategories = []
    for index, cat in enumerate(DEFAULT_EXPENSE_CATEGORIES):
        categories.append({
            "id": cat["id"], "type": "expense", "name": cat["name"], "emoji": cat["emoji"],
            "budget": 0, "color": CATEGORY_COLORS[index % len(CATEGORY_COLORS)],
            "order": index, "isDefault": True,
        })
        for sub_index, sub in enumerate(cat["subs"]):
            subcategories.append({
                "id": sub["id"], "categoryId": cat["id"], "name": sub["name"],
                "emoji": sub["emoji"], "order": sub_index, "isDefault": True,
            })
    for index, cat in enumerate(DEFAULT_INCOME_CATEGORIES):
        categories.append({
            "id": cat["id"], "type": "income", "name": cat["name"], "emoji": cat["emoji"],
            "budget": 0, "color": None, "order": index, "isDefault": True,
        })
    return {
        "schemaVersion": SCHEMA_VERSION,
        "settings": {
            "startingCash": 0,
            "cycleStartDay": DEFAULT_CYCLE_START_DAY,
            "lastBackupAt": None,
        },
        "categories": categories,
        "subcategories": subcategories,
        "transactions": [],
        "accounts": [],
        "cycleHistory": [],
        "currentCycle": None,  # renew_cycles()에서 채운다
    }


def is_valid_state(data) -> bool:
    return (isinstance(data, dict)
            and isinstance(data.get("schemaVersion"), int)
            and isinstance(data.get("settings"), dict)
            and all(isinstance(data.get(key), list)
                    for key in ("categories", "subcategories", "transactions", "accounts", "cycleHistory")))


# 스키마 버전별 변환 함수. MIGRATIONS[n]은 버전 n 데이터를 n+1로 바꾼다 (F-804)
MIGRATIONS: dict = {}


def migrate(data: dict) -> dict:
    migrated = data
    while migrated["schemaVersion"] < SCHEMA_VERSION:
        step = MIGRATIONS.get(migrated["schemaVersion"])
        if not step:
            raise ValueError(f"schemaVersion {migrated['schemaVersion']}을(를) 변환할 수 없어요.")
        migrated = step(migrated)
    return migrated


def add_notice(notices: list, level: str, text: str) -> None:
    """같은 알림은 한 번만 띄운다. level: 'warn' | 'error' | 'info'."""
    if not any(n["text"] == text for n in notices):
        notices.append({"level": level, "text": text})


def find_by_id(items: list, item_id):
    return next((item for item in items if item.get("id") == item_id), None)


def categories_of(state: dict, cat_type: str) -> list:
    return sorted((c for c in state["categories"] if c["type"] == cat_type), key=lambda c: c["order"])


def subcategories_of(state: dict, category_id) -> list:
    return sorted((s for s in state["subcategories"] if s["categoryId"] == category_id), key=lambda s: s["order"])


# --- 내역 변경 ---
def _apply_transfer(state: dict, tx: dict, sign: int) -> None:
    """저축 이체는 계좌 잔고를 함께 바꾼다. sign = +1(반영) / -1(되돌리기)."""
    if tx.get("type") != "transfer":
        return
    account = find_by_id(state["accounts"], tx.get("accountId"))
    if account:
        account["balance"] += sign * tx["amount"]


def add_transaction(state: dict, data: dict) -> dict:
    tx = {"id": gen_id("tx"), **data, "createdAt": now_iso()}
    state["transactions"].append(tx)
    _apply_transfer(state, tx, +1)
    return tx


def update_transaction(state: dict, tx_id: str, data: dict) -> dict | None:
    for index, old in enumerate(state["transactions"]):
        if old["id"] == tx_id:
            _apply_transfer(state, old, -1)
            updated = {**old, **data}
            state["transactions"][index] = updated
            _apply_transfer(state, updated, +1)
            return updated
    return None


def delete_transaction(state: dict, tx_id: str) -> None:
    for index, tx in enumerate(state["transactions"]):
        if tx["id"] == tx_id:
            _apply_transfer(state, tx, -1)
            del state["transactions"][index]
            return


# --- 카테고리 변경 ---
def _renumber_expense_categories(state: dict) -> None:
    """대분류 순서를 0부터 다시 매긴다. "기타"는 항상 맨 뒤."""
    cats = categories_of(state, "expense")
    others = [c for c in cats if c["id"] != ETC_CATEGORY_ID]
    etc = [c for c in cats if c["id"] == ETC_CATEGORY_ID]
    for index, cat in enumerate(others + etc):
        cat["order"] = index


def _next_category_color(state: dict) -> str:
    cats = categories_of(state, "expense")
    used = {c["color"] for c in cats}
    free = next((color for color in CATEGORY_COLORS if color not in used), None)
    return free or CATEGORY_COLORS[len(cats) % len(CATEGORY_COLORS)]


def add_category(state: dict, name: str, emoji: str, budget: int) -> dict:
    category = {
        "id": gen_id("cat"), "type": "expense", "name": name, "emoji": emoji, "budget": budget,
        "color": _next_category_color(state), "order": 2**53 - 1, "isDefault": False,
    }
    state["categories"].append(category)
    _renumber_expense_categories(state)
    return category


def delete_category(state: dict, category_id: str) -> None:
    """대분류 삭제: 소분류는 지우고, 내역은 "기타"(소분류 없음)로 옮긴다 (F-205)."""
    if category_id == ETC_CATEGORY_ID:
        return
    for tx in state["transactions"]:
        if tx.get("categoryId") == category_id:
            tx["categoryId"] = ETC_CATEGORY_ID
            tx["subcategoryId"] = None
    state["subcategories"] = [s for s in state["subcategories"] if s["categoryId"] != category_id]
    state["categories"] = [c for c in state["categories"] if c["id"] != category_id]
    _renumber_expense_categories(state)


def add_subcategory(state: dict, category_id: str, name: str, emoji: str) -> dict:
    subs = subcategories_of(state, category_id)
    sub = {
        "id": gen_id("sub"), "categoryId": category_id, "name": name, "emoji": emoji,
        "order": subs[-1]["order"] + 1 if subs else 0, "isDefault": False,
    }
    state["subcategories"].append(sub)
    return sub


def delete_subcategory(state: dict, sub_id: str, move_to_id: str | None = None) -> None:
    """소분류 삭제: 내역이 있으면 같은 대분류의 다른 소분류(move_to_id)로 옮긴다 (F-205)."""
    if move_to_id:
        for tx in state["transactions"]:
            if tx.get("subcategoryId") == sub_id:
                tx["subcategoryId"] = move_to_id
    state["subcategories"] = [s for s in state["subcategories"] if s["id"] != sub_id]


def category_name_problem(state: dict, name: str, except_id: str | None = None) -> str | None:
    if not name:
        return "이름을 입력해 주세요."
    if any(c["id"] != except_id and c["name"] == name for c in categories_of(state, "expense")):
        return f'"{name}" 대분류가 이미 있어요.'
    return None


def subcategory_name_problem(state: dict, category_id: str, name: str, except_id: str | None = None) -> str | None:
    if not name:
        return "이름을 입력해 주세요."
    if any(s["id"] != except_id and s["name"] == name for s in subcategories_of(state, category_id)):
        return f'이 대분류에 "{name}" 소분류가 이미 있어요.'
    return None


# --- 계좌 변경 ---
def add_account(state: dict, data: dict) -> dict:
    account = {"id": gen_id("acc"), **data}
    state["accounts"].append(account)
    return account


def update_account(state: dict, account_id: str, data: dict) -> dict | None:
    account = find_by_id(state["accounts"], account_id)
    if account:
        account.update(data)
    return account


def delete_account(state: dict, account_id: str) -> None:
    """저축 이체 내역은 남긴다. 목록에는 "삭제된 계좌"로 보인다 (PRD 8장)."""
    state["accounts"] = [a for a in state["accounts"] if a["id"] != account_id]


# ============================================================
# 4. 계산
# ============================================================

def get_cycle(state: dict | None, date_str: str) -> dict | None:
    """날짜가 속한 정산 주기 (PRD 3.1). 결산일 ~ 다음 결산일 전날이고, 끝나는 달 이름을 붙인다."""
    d = parse_date_str(date_str)
    if not d:
        return None
    start_day = (state and state["settings"].get("cycleStartDay")) or DEFAULT_CYCLE_START_DAY
    if d.day >= start_day:
        start = date(d.year, d.month, start_day)
    else:
        start = add_months(date(d.year, d.month, 1), -1, start_day)
    end = add_months(start, 1, start_day) - timedelta(days=1)
    return {
        "label": f"{end.year}-{end.month:02d}",
        "title": f"{end.year}년 {end.month}월 가계부",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "daysTotal": diff_days(start, end) + 1,
        "daysPassed": diff_days(start, d) + 1,  # 오늘 포함
        "daysLeft": diff_days(d, end),
    }


def transactions_in(state: dict, cycle: dict) -> list:
    return [tx for tx in state["transactions"] if cycle["start"] <= tx["date"] <= cycle["end"]]


def totals(state: dict, cycle: dict) -> dict:
    """주기의 수입·지출·저축 이체 합계. 잔액 = 수입 − 지출 − 이체."""
    sums = {"income": 0, "expense": 0, "transfer": 0}
    for tx in transactions_in(state, cycle):
        sums[tx["type"]] += tx["amount"]
    return {**sums, "balance": sums["income"] - sums["expense"] - sums["transfer"]}


def total_assets(state: dict) -> dict:
    """총 자산 = 현금성 자산 + 계좌 잔고 합계 (PRD 3.3). 현금성 자산은 전체 기간 내역으로 계산한다."""
    cash = state["settings"].get("startingCash") or 0
    for tx in state["transactions"]:
        cash += tx["amount"] if tx["type"] == "income" else -tx["amount"]
    accounts = sum(a["balance"] for a in state["accounts"])
    return {"cash": cash, "accounts": accounts, "total": cash + accounts}


def suggested_paid_count(open_date: str, maturity_date: str | None) -> int:
    """가입일부터 오늘까지 냈어야 하는 회차 (가입일에 1회차). 납입 회차 기본값으로 쓴다."""
    opened = parse_date_str(open_date)
    now = parse_date_str(today())
    if not opened or diff_days(opened, now) < 0:
        return 0
    count = months_between(opened, now) + 1
    maturity = parse_date_str(maturity_date)
    return min(count, months_between(opened, maturity)) if maturity else count


def maturity_amount(account: dict) -> dict | None:
    """만기 예상 수령액 (세전, PRD 4.4). 계산할 수 없으면 {problem}, 해당 없는 계좌는 None."""
    kind = account.get("kind")
    if kind not in ("fixed_savings", "fixed_deposit"):
        return None
    opened = parse_date_str(account.get("openDate"))
    maturity = parse_date_str(account.get("maturityDate"))
    if not opened or not maturity:
        return {"problem": "가입일과 만기일을 입력해 주세요."}
    n = months_between(opened, maturity)
    if n < 1:
        return {"problem": "가입 기간이 1개월보다 짧아요."}

    # 단리는 정수 계산으로 부동소수점 오차 없이 버림한다. 이율은 0.001% 단위까지 쓴다
    rate = account.get("annualRate") or 0
    rate_milli = js_round(rate * 1000)  # 연 4.5% → 4500
    divisor = 1200 * 1000               # 100(%) × 12(개월) × 1000
    monthly_rate = rate / 100 / 12
    epsilon = 1e-6  # 복리 부동소수점 오차 보정 (1199.9999999 → 1200)

    if kind == "fixed_savings":
        p = account.get("monthlyPayment")
        if not p:
            return {"problem": "월 납입액을 입력해 주세요."}
        principal = p * n
        if account.get("interest") == "monthly_compound":
            total = sum(p * (1 + monthly_rate) ** k for k in range(1, n + 1))
            interest = math.floor(total + epsilon) - principal
        else:
            interest = (p * rate_milli * (n * (n + 1) // 2)) // divisor
    else:
        principal = account.get("balance") or 0
        if account.get("interest") == "monthly_compound":
            interest = math.floor(principal * (1 + monthly_rate) ** n + epsilon) - principal
        else:
            interest = (principal * rate_milli * n) // divisor
    return {"months": n, "principal": principal, "interest": interest, "total": principal + interest}


def spending_by(state: dict, cycle: dict, key: str) -> dict:
    """주기의 지출을 categoryId 또는 subcategoryId 별로 합친다 → {id: 금액}."""
    result: dict = {}
    for tx in transactions_in(state, cycle):
        if tx["type"] != "expense":
            continue
        item_id = tx.get(key) or "none"
        result[item_id] = result.get(item_id, 0) + tx["amount"]
    return result


def score_for(usage: float) -> int:
    eps = 1e-9  # 0.7000000001 같은 부동소수점 오차가 경계값을 넘지 않게
    return next((score for limit, score in SCORE_STEPS if usage <= limit + eps), 0)


def current_budgets(state: dict) -> dict:
    return {c["id"]: c["budget"] for c in categories_of(state, "expense") if c.get("budget", 0) > 0}


def evaluate(state: dict, cycle: dict, budgets: dict | None = None) -> dict | None:
    """당근/채찍 평가 (PRD 4.7). 기준 금액이 없으면 None.
    budgets: {대분류 id: 예산}. 지난 주기는 마감 당시 예산을 넘긴다."""
    if budgets is None:
        budgets = current_budgets(state)
    sums = totals(state, cycle)
    budget_total = sum(budgets.values())
    if budget_total > 0:
        baseline, basis = budget_total, "budget"
    elif sums["income"] > 0:
        baseline, basis = sums["income"] * INCOME_BASELINE_RATIO, "income"
    else:
        return None

    # 진행 중인 주기는 지난 날짜만큼만 기준을 잡는다 (중간 평가)
    today_str = today()
    final = today_str > cycle["end"]
    info = get_cycle(state, cycle["start"])
    days_passed = info["daysTotal"] if final else max(
        1, diff_days(parse_date_str(cycle["start"]), parse_date_str(today_str)) + 1)
    ratio = min(1, days_passed / info["daysTotal"])

    usage = sums["expense"] / (baseline * ratio)
    score = score_for(usage)

    by_category = spending_by(state, cycle, "categoryId")
    by_sub = spending_by(state, cycle, "subcategoryId")
    categories = []
    for cat_id, budget in budgets.items():
        category = find_by_id(state["categories"], cat_id)
        if not category:
            continue
        spent = by_category.get(cat_id, 0)
        cat_usage = spent / (budget * ratio)
        cat_score = score_for(cat_usage)
        subs = [(sub, by_sub.get(sub["id"], 0)) for sub in subcategories_of(state, cat_id)]
        subs = sorted((pair for pair in subs if pair[1] > 0), key=lambda pair: -pair[1])
        sub_text = f"{subs[0][0]['emoji']} {subs[0][0]['name']}" if subs else category["name"]
        comment = CATEGORY_COMMENTS[cat_score].replace("{sub}", with_josa(sub_text, "이", "가"))
        categories.append({
            "category": category, "budget": budget, "spent": spent,
            "usage": cat_usage, "score": cat_score, "comment": comment,
        })
    categories.sort(key=lambda item: item["category"]["order"])

    return {
        "score": score,
        "usage": usage,
        "basis": basis,
        "baseline": baseline,
        "spent": sums["expense"],
        "remaining": baseline - sums["expense"],
        "final": final,
        "daysPassed": days_passed,
        "daysTotal": info["daysTotal"],
        # 첫 문구는 PRD 4.7.2의 대표 문구로 항상 보여주고, 나머지 중 하나를 한마디로 덧붙인다
        "message": MESSAGES[score][0],
        "extraMessage": seeded_pick(MESSAGES[score][1:], f"{cycle['label']}-{score}"),
        "categories": categories,
    }


# --- 주기 갱신 (F-501, F-502, F-505) ---
def summarize_cycle(state: dict, cycle: dict, budgets: dict) -> dict:
    """주기 기록 요약. budgets는 마감 당시 예산 (나중에 예산을 바꿔도 지난 평가가 바뀌지 않게)."""
    sums = totals(state, cycle)
    result = evaluate(state, cycle, budgets)
    return {
        "label": cycle["label"],
        "start": cycle["start"],
        "end": cycle["end"],
        "income": sums["income"],
        "expense": sums["expense"],
        "transfer": sums["transfer"],
        "byCategory": spending_by(state, cycle, "categoryId"),
        "bySubcategory": spending_by(state, cycle, "subcategoryId"),
        "budgets": budgets,
        "score": result["score"] if result else None,
    }


def refresh_cycle_history(state: dict) -> None:
    """지난 주기 내역이 바뀌었을 수 있으니 저장 전에 주기 기록 요약을 다시 계산한다 (F-502)."""
    state["cycleHistory"] = [
        {**summarize_cycle(state, entry, entry.get("budgets") or {}), "closedAt": entry.get("closedAt")}
        for entry in state["cycleHistory"]
    ]


def renew_cycles(state: dict, notices: list) -> list:
    """오늘이 현재 주기 끝을 지났으면 밀린 주기를 순서대로 모두 마감한다.
    마감한 주기 요약 목록을 돌려준다 (없으면 빈 리스트)."""
    today_str = today()
    if not state.get("currentCycle"):
        cycle = get_cycle(state, today_str)
        state["currentCycle"] = {"label": cycle["label"], "start": cycle["start"], "end": cycle["end"]}
        return []
    current = state["currentCycle"]
    if today_str < current["start"]:
        add_notice(notices, "warn",
                   f"기기 날짜({today_str})가 현재 주기 시작일({current['start']})보다 빨라요. 날짜 설정을 확인해 주세요.")
        return []

    closed = []
    budgets = current_budgets(state)
    while state["currentCycle"]["end"] < today_str:
        cycle = get_cycle(state, state["currentCycle"]["start"])
        summary = {**summarize_cycle(state, cycle, budgets), "closedAt": now_iso()}
        state["cycleHistory"] = [e for e in state["cycleHistory"] if e["label"] != summary["label"]] + [summary]
        closed.append(summary)
        after = parse_date_str(state["currentCycle"]["end"]) + timedelta(days=1)
        nxt = get_cycle(state, after.isoformat())
        state["currentCycle"] = {"label": nxt["label"], "start": nxt["start"], "end": nxt["end"]}
    return closed


def pay_dates_for(closed: list) -> list:
    """자동 납입일 = 마감된 각 주기 다음 날(새 주기 시작일)."""
    return [(parse_date_str(entry["end"]) + timedelta(days=1)).isoformat() for entry in closed]


def auto_pay_candidates(state: dict, pay_dates: list) -> list:
    """자동 납입 반영 (F-504): 만기일이 지난 납입일과 남은 회차를 넘는 납입은 빼고
    [{"account", "dates"}] 목록을 돌려준다."""
    result = []
    for account in state["accounts"]:
        if not (account.get("kind") == "fixed_savings" and account.get("autoPay")
                and (account.get("monthlyPayment") or 0) > 0):
            continue
        info = maturity_amount(account)
        remaining = (max(0, info["months"] - (account.get("paidCount") or 0))
                     if info and info.get("months") else len(pay_dates))
        dates = [d for d in pay_dates if not account.get("maturityDate") or d <= account["maturityDate"]][:remaining]
        if dates:
            result.append({"account": account, "dates": dates})
    return result


def apply_auto_pay(state: dict, account: dict, dates: list) -> None:
    for d in dates:
        add_transaction(state, {
            "type": "transfer", "date": d, "amount": account["monthlyPayment"],
            "categoryId": None, "subcategoryId": None, "accountId": account["id"], "memo": "자동 납입",
        })
    account["paidCount"] = (account.get("paidCount") or 0) + len(dates)


# --- 표시용 ---
def describe_transaction(state: dict, tx: dict) -> tuple[str, str]:
    """내역 한 건의 (이모지, "대분류 > 소분류" 이름)."""
    if tx["type"] == "transfer":
        account = find_by_id(state["accounts"], tx.get("accountId"))
        return "🏦", f"저축 이체 > {account['name'] if account else '삭제된 계좌'}"
    category = find_by_id(state["categories"], tx.get("categoryId"))
    if not category:
        return "❔", "삭제된 카테고리"
    if tx["type"] == "income":
        return category["emoji"], f"수입 > {category['name']}"
    sub = find_by_id(state["subcategories"], tx.get("subcategoryId"))
    if not sub:
        return category["emoji"], category["name"]
    return sub["emoji"], f"{category['name']} > {sub['name']}"


# --- 백업 (F-803) ---
def backup_problem(data) -> str | None:
    """가져올 수 없는 이유. 괜찮으면 None."""
    if not isinstance(data, dict):
        return "가계부 백업 파일이 아니에요."
    missing = [key for key in ("categories", "subcategories", "transactions", "accounts")
               if not isinstance(data.get(key), list)]
    if missing or not isinstance(data.get("schemaVersion"), int):
        detail = f"{', '.join(missing)} 항목이 없어요" if missing else "schemaVersion이 없어요"
        return f"가계부 백업 파일이 아니에요. ({detail})"
    if data["schemaVersion"] > SCHEMA_VERSION:
        return "더 새로운 버전의 앱에서 만든 백업이라 읽을 수 없어요."
    for index, tx in enumerate(data["transactions"]):
        amount = tx.get("amount") if isinstance(tx, dict) else None
        if (not isinstance(tx, dict) or tx.get("type") not in ("income", "expense", "transfer")
                or not parse_date_str(tx.get("date"))
                or not isinstance(amount, int) or isinstance(amount, bool) or amount < 1):
            return f"{index + 1}번째 내역의 형식이 올바르지 않아요."
    return None


def state_from_backup(data: dict) -> dict:
    defaults = create_initial_state()
    return migrate({
        **copy.deepcopy(data),
        "settings": {**defaults["settings"], **(data.get("settings") or {})},
        "cycleHistory": data["cycleHistory"] if isinstance(data.get("cycleHistory"), list) else [],
        "currentCycle": data.get("currentCycle"),
    })
