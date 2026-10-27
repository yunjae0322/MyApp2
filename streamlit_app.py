"""당근과 채찍 가계부 — Streamlit 화면.

실행: streamlit run streamlit_app.py
시간 여행: 주소 뒤에 ?today=YYYY-MM-DD

계산과 데이터 변경은 ledger_core, 저장은 storage에 맡기고 여기서는 화면만 그린다.
상태(state)는 세션마다 st.session_state.state에 두고, 바꿀 때마다 commit()으로 저장한다.
"""

from __future__ import annotations

import hmac
import html
import json
import re
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import ledger_core as core
import storage

st.set_page_config(page_title="당근과 채찍 가계부", page_icon="🥕", layout="wide")
# 큰 금액이 "₩887,…"처럼 잘리지 않게 지표 글자를 줄인다
st.html("<style>[data-testid='stMetricValue'] { font-size: 1.5rem; }</style>")

ss = st.session_state
TYPE_LABELS = {"expense": "지출", "income": "수입", "transfer": "저축 이체"}
DATE_MIN, DATE_MAX = date(2000, 1, 1), date(2100, 12, 31)

# ============================================================
# 1. 유틸
# ============================================================

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def md(text) -> str:
    """사용자 글자를 마크다운에 넣을 때 쓴다. 마크다운·HTML·수식으로 해석되지 않게 한다."""
    return _MD_SPECIAL.sub(r"\\\1", str(text))


def esc(text) -> str:
    return html.escape(str(text))


def secret(key):
    try:
        return st.secrets[key] if key in st.secrets else None
    except Exception:  # secrets.toml이 아예 없을 때
        return None


def flash(text: str, icon: str = "✅") -> None:
    """다음 화면에 토스트로 한 번 보여준다."""
    ss.setdefault("flash", []).append((text, icon))


def state() -> dict:
    return ss.state


def to_date(value: str | None) -> date | None:
    return core.parse_date_str(value)


# ============================================================
# 2. 저장소 · 로그인 · 불러오기
# ============================================================

@st.cache_resource(show_spinner="Google Sheets에 연결하는 중…")
def get_store():
    account_info = secret("gcp_service_account")
    sheet_url = secret("sheet_url")
    if account_info and sheet_url:
        return storage.SheetStore(account_info, sheet_url)
    return storage.LocalStore()


def password_gate(remote: bool) -> None:
    password = secret("password")
    if not password:
        if remote:
            st.error("secrets에 password가 없어요. 배포한 앱은 비밀번호를 꼭 설정해 주세요. (README_STREAMLIT.md 참고)")
            st.stop()
        return
    if ss.get("authed"):
        return
    st.title("🥕 당근과 채찍 가계부")
    with st.form("login"):
        entered = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("들어가기", type="primary")
    if submitted:
        if hmac.compare_digest(entered.encode("utf-8"), str(password).encode("utf-8")):
            ss.authed = True
            st.rerun()
        st.error("비밀번호가 틀렸어요.")
    st.stop()


def reset_widget_keys() -> None:
    """데이터를 새로 불러오면 설정 화면 입력칸이 옛 값을 붙들고 있지 않게 지운다."""
    prefixes = ("cat_", "sub_", "newsub_", "entry_", "autopay_", "starting_cash")
    for key in [k for k in ss.keys() if isinstance(k, str) and k.startswith(prefixes)]:
        del ss[key]
    ss.editing_id = None


def load_session() -> None:
    notices: list = []
    loaded, rev = storage.load_state(get_store(), notices)
    ss.state, ss.rev = loaded, rev
    ss.notices = notices
    reset_widget_keys()


def commit() -> bool:
    """state를 저장한다. 다른 기기에서 먼저 저장했으면 덮어쓰지 않고 새로 불러온다."""
    try:
        ss.rev = storage.save_state(get_store(), state(), ss.rev)
        return True
    except storage.ConflictError:
        load_session()
        core.add_notice(ss.notices, "warn",
                        "다른 기기(또는 탭)에서 먼저 저장한 내용이 있어 새로 불러왔어요. 방금 한 변경은 저장되지 않았으니 다시 해 주세요.")
    except Exception as error:  # 네트워크·권한 문제
        core.add_notice(ss.notices, "error", f"저장하지 못했어요: {error}")
    return False


def renew() -> None:
    """밀린 주기를 마감한다. 앱을 켜 둔 채 날짜가 바뀌어도 동작하도록 매번 확인한다."""
    was_empty = state().get("currentCycle") is None
    closed = core.renew_cycles(state(), ss.notices)
    if closed or was_empty:
        commit()
    if closed:
        ss.settlement = closed


# ============================================================
# 3. 당근과 채찍
# ============================================================

WHIP_SVG = (
    '<svg viewBox="0 0 24 24" width="1em" height="1em" style="vertical-align:-0.12em" aria-hidden="true">'
    '<line x1="4" y1="21" x2="9.5" y2="14.5" stroke="currentColor" stroke-width="4" stroke-linecap="round"/>'
    '<path d="M9.5 14.5 C 12 7, 20 3, 21 8 S 14 15, 19 20" fill="none" stroke="currentColor" '
    'stroke-width="2.4" stroke-linecap="round"/></svg>'
)


def rating_html(score: int, size: str = "1.2em") -> str:
    """5칸: 점수만큼 당근, 나머지는 채찍 (채찍 이모지가 없어서 SVG로 그린다)."""
    icons = "".join("🥕" if i < score else WHIP_SVG for i in range(5))
    label = f"5점 만점에 {score}점 (당근 {score}개, 채찍 {5 - score}개)"
    return f'<span role="img" aria-label="{label}" style="font-size:{size};letter-spacing:0.1em;white-space:nowrap">{icons}</span>'


def render_evaluation(cycle: dict, budgets: dict) -> None:
    result = core.evaluate(state(), cycle, budgets)
    if not result:
        st.info("예산이나 수입을 입력하면 평가해 드려요. ⚙ 설정 탭에서 대분류 예산을 정해 보세요.")
        return
    basis_name = "예산 합계" if result["basis"] == "budget" else "수입의 70%"
    stage = "확정 평가" if result["final"] else f"중간 평가 ({result['daysPassed']}/{result['daysTotal']}일 기준)"
    remaining = (f"남은 예산 {core.format_won(result['remaining'])}" if result["remaining"] >= 0
                 else f"{core.format_won(-result['remaining'])} 초과")

    st.html(f'<div style="margin:0.25rem 0">{rating_html(result["score"], "2em")}</div>'
            f'<p style="font-weight:700;font-size:1.1rem;margin:0.5rem 0 0.25rem">{esc(result["message"])}</p>'
            f'<p style="margin:0">{esc(result["extraMessage"])}</p>')
    st.caption(md(f"{stage} · {basis_name} 기준 · 사용률 {core.percent(result['usage'])}"))
    st.caption(md(f"{basis_name} {core.format_won(core.js_round(result['baseline']))} 중 "
                  f"{core.format_won(result['spent'])} 사용 · {remaining}"))

    if not result["categories"]:
        st.caption("대분류에 예산을 정하면 카테고리별 평가도 볼 수 있어요.")
        return
    rows = []
    for item in result["categories"]:
        cat = item["category"]
        over = ' <span style="color:#c62828;font-weight:700">· 예산 초과</span>' if item["spent"] > item["budget"] else ""
        rows.append(
            '<li style="display:flex;flex-wrap:wrap;gap:0.25rem 0.75rem;align-items:center;padding:0.35rem 0;'
            'border-top:1px solid rgba(128,128,128,0.25)">'
            f'{rating_html(item["score"], "0.95em")}'
            f'<strong>{esc(cat["emoji"])} {esc(cat["name"])}</strong>'
            f'<span>{core.percent(item["usage"])}{over}</span>'
            f'<span style="opacity:0.8">{esc(item["comment"])}</span></li>')
    st.html('<ul aria-label="대분류별 평가" style="list-style:none;padding:0;margin:0.5rem 0 0">' + "".join(rows) + "</ul>")


# ============================================================
# 4. 입력 폼
# ============================================================

def init_entry_keys() -> None:
    ss.setdefault("entry_type", "expense")
    for key in ("entry_cat", "entry_sub", "entry_acc", "entry_amount"):
        ss.setdefault(key, None)
    ss.setdefault("entry_memo", "")
    ss.setdefault("entry_date", to_date(core.today()))
    ss.setdefault("editing_id", None)


def sanitize_entry() -> None:
    """카테고리·계좌가 삭제됐거나 유형과 맞지 않으면 선택을 비운다."""
    s = state()
    cat = core.find_by_id(s["categories"], ss.entry_cat)
    if ss.entry_type == "transfer" or not cat or cat["type"] != ss.entry_type:
        ss.entry_cat = None
    sub = core.find_by_id(s["subcategories"], ss.entry_sub)
    if not sub or sub["categoryId"] != ss.entry_cat:
        ss.entry_sub = None
    if not core.find_by_id(s["accounts"], ss.entry_acc):
        ss.entry_acc = None


def entry_problem() -> str | None:
    s = state()
    if ss.entry_type == "expense":
        if not ss.entry_cat:
            return "대분류를 골라 주세요."
        if core.subcategories_of(s, ss.entry_cat) and not ss.entry_sub:
            return "소분류를 골라 주세요."
    elif ss.entry_type == "income":
        if not ss.entry_cat:
            return "수입 종류를 골라 주세요."
    elif not ss.entry_acc:
        return "넣을 계좌를 골라 주세요." if s["accounts"] else "자산 탭에서 계좌를 먼저 추가하세요."
    if not ss.entry_date:
        return "날짜를 입력해 주세요."
    if ss.entry_amount is None:
        return "금액을 입력해 주세요."
    if ss.entry_amount < 1:
        return "1원 이상 입력해 주세요."
    return None


def reset_entry(keep_date: bool) -> None:
    ss.entry_cat = ss.entry_sub = ss.entry_acc = ss.entry_amount = None
    ss.entry_memo = ""
    ss.editing_id = None
    if not keep_date:
        ss.entry_date = to_date(core.today())


def on_type_change() -> None:
    ss.entry_cat = ss.entry_sub = ss.entry_acc = None


def on_cat_change() -> None:
    ss.entry_sub = None


def on_entry_submit() -> None:
    if entry_problem():
        return
    entry_type = ss.entry_type
    tx_date = ss.entry_date.isoformat()
    data = {
        "type": entry_type,
        "date": tx_date,
        "amount": int(ss.entry_amount),
        "categoryId": None if entry_type == "transfer" else ss.entry_cat,
        "subcategoryId": ss.entry_sub if entry_type == "expense" else None,
        "accountId": ss.entry_acc if entry_type == "transfer" else None,
        "memo": (ss.entry_memo or "").strip(),
    }
    editing = ss.editing_id
    if editing:
        core.update_transaction(state(), editing, data)
    else:
        core.add_transaction(state(), data)
    if not commit():
        return
    current = core.get_cycle(state(), core.today())
    verb = "수정했어요" if editing else "저장했어요"
    if current["start"] <= tx_date <= current["end"]:
        flash(f"{verb}.")
    else:
        flash(f"{core.get_cycle(state(), tx_date)['title']}에 {verb}. 이번 주기 목록에는 보이지 않아요.", "📅")
    reset_entry(keep_date=not editing)  # 새로 입력할 때는 날짜를 유지한다 (지난 내역 몰아서 입력하기 편하게)


def start_edit(tx_id: str) -> None:
    tx = core.find_by_id(state()["transactions"], tx_id)
    if not tx:
        return
    ss.entry_type = tx["type"]
    ss.entry_cat = tx.get("categoryId")
    ss.entry_sub = tx.get("subcategoryId")
    ss.entry_acc = tx.get("accountId")
    ss.entry_date = to_date(tx["date"])
    ss.entry_amount = tx["amount"]
    ss.entry_memo = tx.get("memo") or ""
    ss.editing_id = tx_id


def render_entry_form() -> None:
    s = state()
    init_entry_keys()
    sanitize_entry()
    editing = bool(ss.editing_id)
    st.subheader("✏️ 내역 수정" if editing else "✏️ 입력")

    st.radio("유형", list(TYPE_LABELS), format_func=TYPE_LABELS.get, key="entry_type",
             horizontal=True, on_change=on_type_change, label_visibility="collapsed")

    if ss.entry_type == "expense":
        cats = core.categories_of(s, "expense")
        names = {c["id"]: f"{c['emoji']} {c['name']}" for c in cats}
        st.pills("대분류", list(names), format_func=names.get, key="entry_cat", on_change=on_cat_change)
        subs = core.subcategories_of(s, ss.entry_cat) if ss.entry_cat else []
        if subs:
            sub_names = {sub["id"]: f"{sub['emoji']} {sub['name']}" for sub in subs}
            st.pills("소분류", list(sub_names), format_func=sub_names.get, key="entry_sub")
    elif ss.entry_type == "income":
        cats = core.categories_of(s, "income")
        names = {c["id"]: f"{c['emoji']} {c['name']}" for c in cats}
        st.pills("수입 종류", list(names), format_func=names.get, key="entry_cat")
    elif s["accounts"]:
        names = {a["id"]: f"🏦 {a['name']}" for a in s["accounts"]}
        st.pills("넣을 계좌", list(names), format_func=names.get, key="entry_acc")
    else:
        st.info("자산 탭에서 계좌를 먼저 추가하세요.")

    col_date, col_amount = st.columns(2)
    col_date.date_input("날짜", key="entry_date", min_value=DATE_MIN, max_value=DATE_MAX, format="YYYY-MM-DD")
    col_amount.number_input("금액 (원)", key="entry_amount", min_value=0, max_value=core.MAX_AMOUNT,
                            step=1000, format="%d", placeholder="0")
    if ss.entry_amount:
        col_amount.caption(core.format_won(ss.entry_amount))
    st.text_input("메모 (선택)", key="entry_memo", max_chars=100)

    problem = entry_problem()
    col_save, col_cancel = st.columns(2)
    col_save.button("수정 저장" if editing else "저장", type="primary", disabled=bool(problem),
                    on_click=on_entry_submit, width="stretch")
    if editing:
        col_cancel.button("수정 취소", on_click=reset_entry, kwargs={"keep_date": False}, width="stretch")
    if problem:
        st.caption(problem)


# ============================================================
# 5. 내역 목록
# ============================================================

def amount_md(tx: dict) -> str:
    text = core.format_won(tx["amount"])
    if tx["type"] == "income":
        return f":green[+{md(text)}]"
    return f"−{md(text)}"


@st.dialog("내역 삭제")
def delete_tx_dialog(tx_id: str) -> None:
    tx = core.find_by_id(state()["transactions"], tx_id)
    if not tx:
        st.rerun()
    _, label = core.describe_transaction(state(), tx)
    st.markdown("이 내역을 삭제할까요?")
    st.markdown(f"**{md(tx['date'])}  {md(label)}  {md(core.format_won(tx['amount']))}**")
    col_ok, col_cancel = st.columns(2)
    if col_ok.button("삭제", type="primary", width="stretch"):
        core.delete_transaction(state(), tx_id)
        if ss.get("editing_id") == tx_id:
            reset_entry(keep_date=False)
        if commit():
            flash("삭제했어요.", "🗑️")
        st.rerun()
    if col_cancel.button("취소", width="stretch"):
        st.rerun()


def render_transactions(cycle: dict) -> None:
    s = state()
    st.subheader("📒 이번 주기 내역")
    items = sorted(core.transactions_in(s, cycle), key=lambda tx: (tx["date"], tx.get("createdAt", "")), reverse=True)
    if not items:
        st.caption("이번 주기 내역이 아직 없어요.")
        return
    today_str = core.today()
    groups: list = []
    for tx in items:
        if groups and groups[-1][0] == tx["date"]:
            groups[-1][1].append(tx)
        else:
            groups.append((tx["date"], [tx]))

    for day, txs in groups:
        d = to_date(day)
        heading = f"**{d.month}월 {d.day}일 ({core.weekday_of(day)})**"
        if len(txs) > 1:  # 하루 합계는 내역이 2건 이상일 때만 (1건이면 같은 금액이 두 번 보인다)
            income = sum(tx["amount"] for tx in txs if tx["type"] == "income")
            expense = sum(tx["amount"] for tx in txs if tx["type"] == "expense")
            if income:
                heading += f" · :green[+{md(core.format_won(income))}]"
            if expense:
                heading += f" · −{md(core.format_won(expense))}"
        st.markdown(heading)
        for tx in txs:
            emoji, label = core.describe_transaction(s, tx)
            editing = tx["id"] == ss.get("editing_id")
            with st.container(border=editing):
                col_text, col_menu = st.columns([6, 1], vertical_alignment="center")
                line = f"{emoji} {md(label)}"
                if tx["date"] > today_str:
                    line += " :orange-badge[예정]"
                if editing:
                    line += " :blue-badge[수정 중]"
                line += f" — **{amount_md(tx)}**"
                col_text.markdown(line)
                if tx.get("memo"):
                    col_text.caption(md(tx["memo"]))
                with col_menu.popover("⋯", help="수정·삭제"):
                    st.button("수정", key=f"edit_{tx['id']}", on_click=start_edit, args=(tx["id"],),
                              width="stretch")
                    if st.button("삭제", key=f"del_{tx['id']}", width="stretch"):
                        delete_tx_dialog(tx["id"])


# ============================================================
# 6. 지출 그래프 (F-601~F-603)
# ============================================================

def render_charts(cycle: dict) -> None:
    s = state()
    by_cat = core.spending_by(s, cycle, "categoryId")
    by_sub = core.spending_by(s, cycle, "subcategoryId")
    cats = core.categories_of(s, "expense")
    rows = [(c, by_cat.get(c["id"], 0)) for c in cats if by_cat.get(c["id"], 0) > 0]
    total = sum(amount for _, amount in rows)
    if not total:
        st.caption("이번 주기 지출이 아직 없어요.")
        return

    df = pd.DataFrame([{
        "대분류": f"{c['emoji']} {c['name']}",
        "지출": amount,
        "예산": c.get("budget") or 0,
        "비율": amount / total,
        "순서": c["order"],
        "색": c.get("color") or core.CATEGORY_COLORS[0],
        "지출 표시": core.format_won(amount),
        "예산 표시": core.format_won(c["budget"]) if c.get("budget") else "없음",
        "비율 표시": core.percent(amount / total),
    } for c, amount in rows])
    names = df["대분류"].tolist()
    color = alt.Color("대분류:N", scale=alt.Scale(domain=names, range=df["색"].tolist()), sort=names)
    tooltip = [alt.Tooltip("대분류:N"), alt.Tooltip("지출 표시:N", title="지출"),
               alt.Tooltip("비율 표시:N", title="비율"), alt.Tooltip("예산 표시:N", title="예산")]

    col_donut, col_bars = st.columns([2, 3])
    with col_donut:
        base = alt.Chart(df).encode(theta=alt.Theta("지출:Q", stack=True), order=alt.Order("순서:Q"))
        donut = base.mark_arc(innerRadius=70, outerRadius=110, padAngle=0.015, cornerRadius=2).encode(
            color=color.legend(orient="bottom", columns=2, title=None), tooltip=tooltip)
        st.markdown(f"**총 지출 {md(core.format_won(total))}**")
        st.altair_chart(donut.properties(height=330), width="stretch")

    with col_bars:
        st.caption("막대 = 지출, 회색 세로선 = 예산. 예산을 넘은 대분류는 표에 표시돼요.")
        y = alt.Y("대분류:N", sort=names, title=None)
        bars = alt.Chart(df).mark_bar(cornerRadiusEnd=4, height=18).encode(
            y=y, x=alt.X("지출:Q", title="원", axis=alt.Axis(format=",d")), color=color.legend(None), tooltip=tooltip)
        layers = bars
        if (df["예산"] > 0).any():
            layers += alt.Chart(df[df["예산"] > 0]).mark_tick(color="gray", thickness=3, size=26).encode(
                y=y, x="예산:Q", tooltip=tooltip)
        st.altair_chart(layers.properties(height=max(120, 40 * len(df))), width="stretch")

    # 표 보기 (색만으로 구분하지 않도록)
    table = pd.DataFrame([{
        "대분류": f"{c['emoji']} {c['name']}",
        "지출": core.format_won(amount),
        "비율": core.percent(amount / total),
        "예산": core.format_won(c["budget"]) if c.get("budget") else "없음",
        "비고": "⚠️ 예산 초과" if c.get("budget") and amount > c["budget"] else "",
    } for c, amount in rows])
    st.dataframe(table, hide_index=True, width="stretch")

    zero = [f"{c['emoji']} {c['name']}" for c in cats if not by_cat.get(c["id"])]
    if zero:
        st.caption(md("지출 없음: " + ", ".join(zero)))

    # 소분류 펼쳐 보기
    options = {c["id"]: f"{c['emoji']} {c['name']}" for c, _ in rows}
    picked = st.selectbox("소분류별 지출 보기", list(options), format_func=options.get, index=None,
                          placeholder="대분류를 고르세요")
    if picked:
        category = core.find_by_id(s["categories"], picked)
        amount = by_cat[picked]
        sub_rows = [{"소분류": f"{sub['emoji']} {sub['name']}", "지출": by_sub.get(sub["id"], 0)}
                    for sub in core.subcategories_of(s, picked) if by_sub.get(sub["id"], 0) > 0]
        counted = sum(row["지출"] for row in sub_rows)
        if amount > counted:
            sub_rows.append({"소분류": "소분류 없음", "지출": amount - counted})
        sub_df = pd.DataFrame(sub_rows).sort_values("지출", ascending=False)
        sub_df["표시"] = [f"{core.format_won(v)} · {core.percent(v / amount)}" for v in sub_df["지출"]]
        chart = alt.Chart(sub_df).mark_bar(cornerRadiusEnd=4, height=16, color=category.get("color")).encode(
            y=alt.Y("소분류:N", sort=sub_df["소분류"].tolist(), title=None),
            x=alt.X("지출:Q", title="원", axis=alt.Axis(format=",d")),
            tooltip=[alt.Tooltip("소분류:N"), alt.Tooltip("표시:N", title="지출")])
        st.altair_chart(chart.properties(height=max(80, 36 * len(sub_df))), width="stretch")


# ============================================================
# 7. 자산 현황
# ============================================================

ACCOUNT_FIELDS = ("acc_name", "acc_kind", "acc_balance", "acc_rate", "acc_interest",
                  "acc_open", "acc_maturity", "acc_monthly", "acc_paid", "acc_autopay")


def prepare_account_form(account: dict | None) -> None:
    a = account or {}
    ss.acc_editing = a.get("id")
    ss.acc_paid_touched = bool(account)  # 직접 고친 회차는 자동 제안으로 덮어쓰지 않는다
    ss.acc_name = a.get("name", "")
    ss.acc_kind = a.get("kind", "fixed_savings")
    ss.acc_balance = a.get("balance")
    ss.acc_rate = float(a["annualRate"]) if a.get("annualRate") is not None else None
    ss.acc_interest = a.get("interest") or "simple"
    ss.acc_open = to_date(a.get("openDate"))
    ss.acc_maturity = to_date(a.get("maturityDate"))
    ss.acc_monthly = a.get("monthlyPayment")
    ss.acc_paid = a.get("paidCount")
    ss.acc_autopay = bool(a.get("autoPay"))
    ss.acc_error = ""


def suggest_paid_count() -> None:
    if ss.get("acc_paid_touched") or not ss.acc_open:
        return
    ss.acc_paid = core.suggested_paid_count(
        ss.acc_open.isoformat(), ss.acc_maturity.isoformat() if ss.acc_maturity else None)


def read_account_form() -> tuple[dict | None, str | None]:
    kind_key = ss.acc_kind
    kind = core.ACCOUNT_KINDS[kind_key]
    name = (ss.acc_name or "").strip()
    if not name:
        return None, "계좌 이름을 입력해 주세요."
    if ss.acc_balance is None:
        return None, "현재 잔고를 입력해 주세요. 없으면 0을 입력하세요."
    rate = ss.acc_rate
    if rate is None or not 0 <= rate <= 100:
        return None, "연 이율은 0~100 사이 숫자로 입력해 주세요. (예: 4.5)"
    data = {
        "name": name, "kind": kind_key, "balance": int(ss.acc_balance),
        "annualRate": core.js_round(rate * 1000) / 1000,
        "interest": ss.acc_interest if kind["interest"] else None,
        "openDate": None, "maturityDate": None, "monthlyPayment": None, "paidCount": None, "autoPay": False,
    }
    if kind["needsDates"]:
        if not ss.acc_open:
            return None, "가입일을 입력해 주세요."
        if not ss.acc_maturity:
            return None, "만기일을 입력해 주세요."
        if ss.acc_maturity <= ss.acc_open:
            return None, "만기일이 가입일보다 늦어야 해요."
        data["openDate"] = ss.acc_open.isoformat()
        data["maturityDate"] = ss.acc_maturity.isoformat()
    if kind["monthly"]:
        data["monthlyPayment"] = int(ss.acc_monthly) if ss.acc_monthly else None
        data["paidCount"] = int(ss.acc_paid or 0)
        data["autoPay"] = bool(ss.acc_autopay)
    return data, None


@st.dialog("계좌")
def account_dialog() -> None:
    editing = ss.get("acc_editing")
    st.subheader("계좌 수정" if editing else "계좌 추가")
    st.text_input("계좌 이름", key="acc_name", max_chars=30)
    st.selectbox("종류", list(core.ACCOUNT_KINDS), format_func=lambda k: core.ACCOUNT_KINDS[k]["name"], key="acc_kind")
    kind = core.ACCOUNT_KINDS[ss.acc_kind]
    st.number_input("현재 잔고 (원)", key="acc_balance", min_value=0, max_value=core.MAX_AMOUNT, step=10000, format="%d")
    st.number_input("연 이율 (%)", key="acc_rate", min_value=0.0, max_value=100.0, step=0.1, format="%.3f")
    if kind["interest"]:
        st.radio("이자 방식", list(core.INTEREST_NAMES), format_func=core.INTEREST_NAMES.get,
                 key="acc_interest", horizontal=True)
    if kind["needsDates"]:
        col_open, col_maturity = st.columns(2)
        col_open.date_input("가입일", key="acc_open", min_value=DATE_MIN, max_value=DATE_MAX,
                            format="YYYY-MM-DD", on_change=suggest_paid_count)
        col_maturity.date_input("만기일", key="acc_maturity", min_value=DATE_MIN, max_value=DATE_MAX,
                                format="YYYY-MM-DD", on_change=suggest_paid_count)
    if kind["monthly"]:
        col_monthly, col_paid = st.columns(2)
        col_monthly.number_input("월 납입액 (원)", key="acc_monthly", min_value=0, max_value=core.MAX_AMOUNT,
                                 step=10000, format="%d")
        col_paid.number_input("납입 완료 회차", key="acc_paid", min_value=0, max_value=1200, step=1,
                              on_change=lambda: ss.update(acc_paid_touched=True))
        st.checkbox("주기가 바뀔 때 자동 납입 반영 (결산 화면에서 확인)", key="acc_autopay")

    if ss.get("acc_error"):
        st.error(ss.acc_error)
    col_save, col_cancel = st.columns(2)
    if col_save.button("저장", type="primary", width="stretch"):
        data, problem = read_account_form()
        if problem:
            ss.acc_error = problem
            st.rerun(scope="fragment")
        if editing:
            core.update_account(state(), editing, data)
        else:
            core.add_account(state(), data)
        if commit():
            flash("계좌를 저장했어요.")
        st.rerun()
    if col_cancel.button("취소", width="stretch"):
        st.rerun()


@st.dialog("계좌 삭제")
def delete_account_dialog(account_id: str) -> None:
    account = core.find_by_id(state()["accounts"], account_id)
    if not account:
        st.rerun()
    transfers = sum(1 for tx in state()["transactions"] if tx.get("accountId") == account_id)
    st.markdown(md(f'"{account["name"]}" 계좌를 삭제할까요?'))
    st.markdown(md(f"잔고 {core.format_won(account['balance'])}이 총 자산에서 빠져요."))
    if transfers:
        st.markdown(md(f'이 계좌로 저축 이체한 내역 {transfers}건은 "삭제된 계좌"로 남아요.'))
    col_ok, col_cancel = st.columns(2)
    if col_ok.button("삭제", type="primary", width="stretch"):
        core.delete_account(state(), account_id)
        if commit():
            flash("계좌를 삭제했어요.", "🗑️")
        st.rerun()
    if col_cancel.button("취소", width="stretch"):
        st.rerun()


def maturity_badge(account: dict) -> str:
    maturity = to_date(account.get("maturityDate"))
    if not maturity:
        return ""
    left = core.diff_days(to_date(core.today()), maturity)
    if left < 0:
        return " :red-badge[만기 도래]"
    text = "D-day" if left == 0 else f"D-{left}"
    return f" :orange-badge[곧 만기 {text}]" if left <= core.MATURITY_SOON_DAYS else f" :gray-badge[{text}]"


def render_account_card(account: dict) -> None:
    kind = core.ACCOUNT_KINDS.get(account.get("kind"), core.ACCOUNT_KINDS["etc"])
    rate_text = f"연 {account.get('annualRate', 0)}%"
    if kind["interest"]:
        rate_text += f" {core.INTEREST_NAMES.get(account.get('interest'), '')}"
    details = [f"잔고 {core.format_won(account['balance'])}", rate_text]
    info = core.maturity_amount(account)
    if kind["monthly"] and account.get("monthlyPayment"):
        total = f"/{info['months']}" if info and info.get("months") else ""
        details.append(f"월 {core.format_won(account['monthlyPayment'])} · {account.get('paidCount') or 0}{total}회 납입")

    with st.container(border=True):
        col_head, col_edit, col_delete = st.columns([6, 1, 1], vertical_alignment="center")
        col_head.markdown(f"**{md(account['name'])}** · {md(kind['name'])}{maturity_badge(account)}")
        if col_edit.button("수정", key=f"accedit_{account['id']}", width="stretch"):
            prepare_account_form(account)
            account_dialog()
        if col_delete.button("삭제", key=f"accdel_{account['id']}", width="stretch"):
            delete_account_dialog(account["id"])
        st.caption(md(" · ".join(details)))

        opened, maturity = to_date(account.get("openDate")), to_date(account.get("maturityDate"))
        if kind["needsDates"] and opened and maturity:
            span = max(1, core.diff_days(opened, maturity))
            ratio = min(1.0, max(0.0, core.diff_days(opened, to_date(core.today())) / span))
            st.progress(ratio, text=f"가입 {account['openDate']} → 만기 {account['maturityDate']} ({core.percent(ratio)})")
        if info:
            if maturity and account["maturityDate"] < core.today():
                st.warning("만기 도래 — 수령 후 잔고를 정리하세요.")
            elif info.get("problem"):
                st.warning(info["problem"])
            else:
                st.markdown(md(f"만기 예상 수령액 ") + f"**{md(core.format_won(info['total']))}** "
                            + md(f"(원금 {core.format_won(info['principal'])} + 이자 {core.format_won(info['interest'])}, 세전)"))


def render_accounts() -> None:
    s = state()
    col_title, col_add = st.columns([4, 1], vertical_alignment="center")
    col_title.subheader("🏦 자산 현황")
    if col_add.button("＋ 계좌 추가", width="stretch"):
        prepare_account_form(None)
        account_dialog()
    if not s["accounts"]:
        st.caption("등록된 계좌가 없어요. 적금·예금을 추가하면 총 자산과 만기 예상액을 볼 수 있어요.")
        return
    st.caption(f"계좌 합계 {core.format_won(core.total_assets(s)['accounts'])}")
    for account in s["accounts"]:
        render_account_card(account)


# ============================================================
# 8. 설정: 카테고리 · 시작 현금 · 백업
# ============================================================

def on_starting_cash_change() -> None:
    state()["settings"]["startingCash"] = int(ss.starting_cash or 0)
    if commit():
        flash("시작 현금을 저장했어요.")


def on_cat_field_change(field: str, cat_id: str) -> None:
    s = state()
    category = core.find_by_id(s["categories"], cat_id)
    key = f"cat_{field}_{cat_id}"
    if not category:
        return
    if field == "name":
        name = (ss[key] or "").strip()
        problem = core.category_name_problem(s, name, cat_id)
        if problem:
            flash(problem, "⚠️")
            ss[key] = category["name"]
            return
        category["name"] = name
    elif field == "emoji":
        emoji = core.first_grapheme(ss[key] or "")
        if not emoji:
            ss[key] = category["emoji"]
            return
        category["emoji"] = ss[key] = emoji
    elif field == "budget":
        category["budget"] = int(ss[key] or 0)
    if commit():
        flash("저장했어요.")


def on_sub_field_change(field: str, sub_id: str) -> None:
    s = state()
    sub = core.find_by_id(s["subcategories"], sub_id)
    key = f"sub_{field}_{sub_id}"
    if not sub:
        return
    if field == "name":
        name = (ss[key] or "").strip()
        problem = core.subcategory_name_problem(s, sub["categoryId"], name, sub_id)
        if problem:
            flash(problem, "⚠️")
            ss[key] = sub["name"]
            return
        sub["name"] = name
    else:
        emoji = core.first_grapheme(ss[key] or "")
        if not emoji:
            ss[key] = sub["emoji"]
            return
        sub["emoji"] = ss[key] = emoji
    if commit():
        flash("저장했어요.")


def on_add_subcategory(cat_id: str) -> None:
    s = state()
    category = core.find_by_id(s["categories"], cat_id)
    name = (ss.get(f"newsub_name_{cat_id}") or "").strip()
    problem = core.subcategory_name_problem(s, cat_id, name)
    if problem:
        flash(problem, "⚠️")
        return
    emoji = core.first_grapheme(ss.get(f"newsub_emoji_{cat_id}") or "") or core.DEFAULT_NEW_EMOJI
    core.add_subcategory(s, cat_id, name, emoji)
    ss[f"newsub_name_{cat_id}"] = ""
    ss[f"newsub_emoji_{cat_id}"] = core.DEFAULT_NEW_EMOJI
    if commit():
        flash(f'"{category["name"]} > {name}" 소분류를 추가했어요.')


def on_add_category() -> None:
    s = state()
    name = (ss.get("newcat_name") or "").strip()
    problem = core.category_name_problem(s, name)
    if problem:
        flash(problem, "⚠️")
        return
    emoji = core.first_grapheme(ss.get("newcat_emoji") or "") or core.DEFAULT_NEW_EMOJI
    core.add_category(s, name, emoji, int(ss.get("newcat_budget") or 0))
    ss.newcat_name = ""
    ss.newcat_budget = None
    ss.newcat_emoji = core.DEFAULT_NEW_EMOJI
    if commit():
        flash(f'"{name}" 대분류를 추가했어요. 소분류를 펼쳐서 추가하세요.')


@st.dialog("대분류 삭제")
def delete_category_dialog(cat_id: str) -> None:
    s = state()
    category = core.find_by_id(s["categories"], cat_id)
    if not category:
        st.rerun()
    sub_count = len(core.subcategories_of(s, cat_id))
    tx_count = sum(1 for tx in s["transactions"] if tx.get("categoryId") == cat_id)
    st.markdown(md(f'"{category["emoji"]} {category["name"]}" 대분류를 삭제할까요?'))
    if sub_count:
        st.markdown(md(f"소분류 {sub_count}개도 함께 삭제돼요."))
    if tx_count:
        st.markdown(md(f"내역 {tx_count}건은 📦 기타로 옮겨져요."))
    col_ok, col_cancel = st.columns(2)
    if col_ok.button("삭제", type="primary", width="stretch"):
        core.delete_category(s, cat_id)
        if commit():
            flash(f'"{category["name"]}" 대분류를 삭제했어요.', "🗑️")
        st.rerun()
    if col_cancel.button("취소", width="stretch"):
        st.rerun()


@st.dialog("소분류 삭제")
def delete_sub_dialog(sub_id: str) -> None:
    s = state()
    sub = core.find_by_id(s["subcategories"], sub_id)
    if not sub:
        st.rerun()
    category = core.find_by_id(s["categories"], sub["categoryId"])
    label = f"{category['name']} > {sub['name']}"
    count = sum(1 for tx in s["transactions"] if tx.get("subcategoryId") == sub_id)
    others = [o for o in core.subcategories_of(s, category["id"]) if o["id"] != sub_id]
    target = None
    if count:
        if not others:
            st.warning(md(f'"{sub["name"]}"에 내역이 {count}건 있어요. 옮길 소분류를 먼저 추가하거나, '
                          "대분류를 삭제해서 기타로 옮기세요."))
            if st.button("닫기", width="stretch"):
                st.rerun()
            return
        names = {o["id"]: f"{o['emoji']} {o['name']}" for o in others}
        target = st.selectbox(f"내역 {count}건을 옮길 소분류", list(names), format_func=names.get)
    else:
        st.markdown(md(f'"{label}" 소분류를 삭제할까요?'))
    col_ok, col_cancel = st.columns(2)
    if col_ok.button("옮기고 삭제" if count else "삭제", type="primary", width="stretch"):
        core.delete_subcategory(s, sub_id, target)
        if commit():
            flash(f'"{label}" 소분류를 삭제했어요.', "🗑️")
        st.rerun()
    if col_cancel.button("취소", width="stretch"):
        st.rerun()


def render_category_manager() -> None:
    s = state()
    st.caption("이름·이모지·예산은 칸을 벗어나거나 Enter를 누르면 저장돼요. 이모지는 첫 글자 하나만 써요. "
               "예: " + " ".join(core.EMOJI_CHOICES))
    for category in core.categories_of(s, "expense"):
        cat_id = category["id"]
        is_etc = cat_id == core.ETC_CATEGORY_ID
        for field, value in (("emoji", category["emoji"]), ("name", category["name"]), ("budget", category["budget"] or None)):
            ss.setdefault(f"cat_{field}_{cat_id}", value)
        subs = core.subcategories_of(s, cat_id)
        budget_text = f" · 예산 {core.format_won(category['budget'])}" if category.get("budget") else ""
        with st.expander(f"{category['emoji']} {category['name']}{budget_text}"):
            col_emoji, col_name, col_budget = st.columns([1, 3, 3])
            col_emoji.text_input("이모지", key=f"cat_emoji_{cat_id}", on_change=on_cat_field_change, args=("emoji", cat_id))
            col_name.text_input("대분류 이름", key=f"cat_name_{cat_id}", max_chars=core.MAX_NAME_LENGTH,
                                on_change=on_cat_field_change, args=("name", cat_id))
            col_budget.number_input("월 예산 (원)", key=f"cat_budget_{cat_id}", min_value=0, max_value=core.MAX_AMOUNT,
                                    step=10000, format="%d", placeholder="없음",
                                    on_change=on_cat_field_change, args=("budget", cat_id))
            if is_etc:
                st.caption("기타는 소분류가 없고 삭제할 수 없어요.")
                continue

            st.markdown(f"**소분류 {len(subs)}개**")
            for sub in subs:
                ss.setdefault(f"sub_emoji_{sub['id']}", sub["emoji"])
                ss.setdefault(f"sub_name_{sub['id']}", sub["name"])
                col_e, col_n, col_d = st.columns([1, 5, 1], vertical_alignment="bottom")
                col_e.text_input("이모지", key=f"sub_emoji_{sub['id']}", label_visibility="collapsed",
                                 on_change=on_sub_field_change, args=("emoji", sub["id"]))
                col_n.text_input(f"{category['name']} > {sub['name']} 이름", key=f"sub_name_{sub['id']}",
                                 label_visibility="collapsed", max_chars=core.MAX_NAME_LENGTH,
                                 on_change=on_sub_field_change, args=("name", sub["id"]))
                if col_d.button("삭제", key=f"subdel_{sub['id']}", width="stretch"):
                    delete_sub_dialog(sub["id"])

            ss.setdefault(f"newsub_emoji_{cat_id}", core.DEFAULT_NEW_EMOJI)
            col_e, col_n, col_a = st.columns([1, 5, 2], vertical_alignment="bottom")
            col_e.text_input("이모지", key=f"newsub_emoji_{cat_id}", label_visibility="collapsed")
            col_n.text_input("새 소분류 이름", key=f"newsub_name_{cat_id}", placeholder="새 소분류 이름",
                             label_visibility="collapsed", max_chars=core.MAX_NAME_LENGTH)
            col_a.button("소분류 추가", key=f"subadd_{cat_id}", on_click=on_add_subcategory, args=(cat_id,),
                         width="stretch")
            st.divider()
            if st.button("이 대분류 삭제", key=f"catdel_{cat_id}", type="secondary"):
                delete_category_dialog(cat_id)

    st.markdown("**새 대분류**")
    ss.setdefault("newcat_emoji", core.DEFAULT_NEW_EMOJI)
    col_e, col_n, col_b, col_a = st.columns([1, 3, 3, 2], vertical_alignment="bottom")
    col_e.text_input("이모지", key="newcat_emoji")
    col_n.text_input("이름", key="newcat_name", max_chars=core.MAX_NAME_LENGTH)
    col_b.number_input("월 예산 (원)", key="newcat_budget", min_value=0, max_value=core.MAX_AMOUNT,
                       step=10000, format="%d", value=None, placeholder="없음")
    col_a.button("대분류 추가", on_click=on_add_category, width="stretch")


def on_backup_download() -> None:
    state()["settings"]["lastBackupAt"] = core.now_iso()
    commit()


def render_backup() -> None:
    s = state()
    last = s["settings"].get("lastBackupAt")
    st.caption(f"마지막 내보내기: {last[:10]}" if last else "아직 내보낸 적이 없어요.")
    st.download_button("⬇ 백업 내보내기 (JSON)", data=json.dumps(s, ensure_ascii=False, indent=2),
                       file_name=f"ledger-backup-{core.today()}.json", mime="application/json",
                       on_click=on_backup_download)
    st.caption("기존 HTML 버전에서 내보낸 백업 파일도 그대로 가져올 수 있어요.")

    uploaded = st.file_uploader("백업 가져오기", type=["json"], key=f"uploader_{ss.get('uploader_nonce', 0)}")
    if not uploaded:
        return
    try:
        data = json.loads(uploaded.getvalue().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        st.error("읽을 수 없는 파일이에요. JSON 백업 파일을 골라 주세요.")
        return
    problem = core.backup_problem(data)
    if problem:
        st.error(problem)
        return
    st.warning(f"현재 데이터를 덮어씁니다. 백업의 내역 {len(data['transactions'])}건, 계좌 {len(data['accounts'])}개로 바뀌어요.")
    if st.button("덮어쓰고 가져오기", type="primary"):
        ss.state = core.state_from_backup(data)
        core.renew_cycles(ss.state, ss.notices)
        reset_widget_keys()
        ss.uploader_nonce = ss.get("uploader_nonce", 0) + 1
        if commit():
            flash(f"가져왔어요. 내역 {len(state()['transactions'])}건, 계좌 {len(state()['accounts'])}개.")
        st.rerun()


def render_settings() -> None:
    st.subheader("⚙ 설정")
    with st.container(border=True):
        st.markdown("**시작 현금** — 가계부를 시작할 때 갖고 있던 현금성 자산")
        ss.setdefault("starting_cash", state()["settings"].get("startingCash") or None)
        st.number_input("시작 현금 (원)", key="starting_cash", min_value=0, max_value=core.MAX_AMOUNT,
                        step=10000, format="%d", on_change=on_starting_cash_change, label_visibility="collapsed")
    st.markdown("#### 카테고리와 예산")
    render_category_manager()
    st.markdown("#### 백업")
    render_backup()


# ============================================================
# 9. 결산 팝업 (F-503, F-504)
# ============================================================

def dismiss_settlement() -> None:
    ss.settlement = None


@st.dialog("지난 주기 결산", width="large", on_dismiss=dismiss_settlement)
def settlement_dialog() -> None:
    closed = ss.settlement
    latest = closed[-1]
    info = core.get_cycle(state(), latest["start"])
    st.subheader(f"{info['title']} 결산")
    note = f" · 밀린 주기 {len(closed)}개를 마감했어요. 가장 최근 주기만 보여드려요." if len(closed) > 1 else ""
    st.caption(f"{latest['start']} ~ {latest['end']}{note}")
    cols = st.columns(4)
    cols[0].metric("수입", f"+{core.format_won(latest['income'])}")
    cols[1].metric("지출", f"−{core.format_won(latest['expense'])}")
    cols[2].metric("저축 이체", core.format_won(latest["transfer"]))
    cols[3].metric("잔액", core.format_won(latest["income"] - latest["expense"] - latest["transfer"]))
    render_evaluation(latest, latest.get("budgets") or {})

    # 자동 납입 반영 (F-504). 납입일 = 마감된 각 주기 다음 날(새 주기 시작일)
    candidates = core.auto_pay_candidates(state(), core.pay_dates_for(closed))
    if candidates:
        st.markdown("**자동 납입 반영**")
        for index, candidate in enumerate(candidates):
            account, dates = candidate["account"], candidate["dates"]
            st.checkbox(f"{account['name']}: 월 {core.format_won(account['monthlyPayment'])} × {len(dates)}회 = "
                        f"{core.format_won(account['monthlyPayment'] * len(dates))}",
                        value=True, key=f"autopay_{index}")
    if st.button("확인", type="primary", width="stretch"):
        applied = 0
        for index, candidate in enumerate(candidates):
            if ss.get(f"autopay_{index}", True):
                core.apply_auto_pay(state(), candidate["account"], candidate["dates"])
                applied += 1
        ss.settlement = None
        if applied and commit():
            flash(f"자동 납입 {applied}건을 반영했어요.")
        st.rerun()


# ============================================================
# 10. 화면 조립
# ============================================================

def render_header(cycle: dict) -> None:
    st.title(f"🥕 {cycle['title']}")
    d_day = "오늘 마감" if cycle["daysLeft"] == 0 else f"다음 갱신까지 D-{cycle['daysLeft']}"
    st.caption(f"{cycle['start'][5:].replace('-', '/')} ~ {cycle['end'][5:].replace('-', '/')} · {d_day}")
    for notice in ss.notices:
        (st.error if notice["level"] == "error" else st.warning)(notice["text"])


def render_summary(cycle: dict) -> None:
    sums = core.totals(state(), cycle)
    assets = core.total_assets(state())
    cols = st.columns(4)
    cols[0].metric("총 자산", core.format_won(assets["total"]),
                   help=f"현금성 {core.format_won(assets['cash'])} · 계좌 {core.format_won(assets['accounts'])}")
    cols[0].caption(f"현금성 {core.format_won(assets['cash'])} · 계좌 {core.format_won(assets['accounts'])}")
    cols[1].metric("이번 주기 수입", f"{'+' if sums['income'] else ''}{core.format_won(sums['income'])}")
    cols[2].metric("이번 주기 지출", f"{'−' if sums['expense'] else ''}{core.format_won(sums['expense'])}")
    cols[3].metric("이번 주기 잔액", core.format_won(sums["balance"]), help="수입 − 지출 − 저축")


def render_sidebar(store) -> None:
    with st.sidebar:
        st.markdown(f"**저장소:** {store.name}")
        if isinstance(store, storage.LocalStore):
            st.caption("로컬 파일 모드예요. Streamlit Cloud에서는 앱이 재시작되면 데이터가 사라지니 Google Sheets를 연결하세요.")
        if st.button("🔄 다시 불러오기", width="stretch", help="다른 기기에서 입력한 내용을 가져와요"):
            load_session()
            st.rerun()
        if ss.get("authed") and st.button("로그아웃", width="stretch"):
            ss.clear()
            st.rerun()


def main() -> None:
    try:
        store = get_store()
    except Exception as error:
        st.error(f"Google Sheets에 연결하지 못했어요: {error}")
        st.stop()
    remote = isinstance(store, storage.SheetStore)
    password_gate(remote)

    # 시간 여행. today()가 모듈 전역이라 실행마다 다시 정한다
    core.set_today_override(st.query_params.get("today"))

    if "state" not in ss:
        try:
            load_session()
        except Exception as error:
            st.error(f"데이터를 불러오지 못했어요: {error}")
            st.stop()
    if core.is_today_overridden():
        core.add_notice(ss.notices, "warn", f"테스트 모드: 오늘을 {core.today()}로 보고 있어요.")
    renew()

    for text, icon in ss.pop("flash", []):
        st.toast(text, icon=icon)

    cycle = core.get_cycle(state(), core.today())
    render_sidebar(store)
    render_header(cycle)
    render_summary(cycle)

    tab_main, tab_chart, tab_assets, tab_settings = st.tabs(["📒 가계부", "📊 지출 그래프", "🏦 자산", "⚙ 설정"])
    with tab_main:
        col_left, col_right = st.columns([5, 6], gap="large")
        with col_left:
            with st.container(border=True):
                render_entry_form()
            with st.container(border=True):
                st.subheader("🥕 당근과 채찍")
                render_evaluation(cycle, core.current_budgets(state()))
        with col_right:
            render_transactions(cycle)
    with tab_chart:
        render_charts(cycle)
    with tab_assets:
        render_accounts()
    with tab_settings:
        render_settings()

    if ss.get("settlement"):
        settlement_dialog()


main()
