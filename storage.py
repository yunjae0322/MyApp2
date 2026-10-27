"""가계부 데이터 저장소.

app.js와 같이 상태 전체를 JSON 객체 하나로 저장한다.
- Google Sheets (배포용): st.secrets에 sheet_url과 gcp_service_account가 있으면 쓴다.
  워크시트 "ledger_v1"의 A열에 JSON을 40,000자씩 나눠 적고 B1에 저장 번호(revision)를 적는다.
  (셀 하나에 50,000자까지만 들어간다)
- 로컬 JSON 파일 (개발용): secrets가 없으면 ledger_data.json에 저장한다.

다른 기기·탭에서 먼저 저장했으면 revision이 달라진다. 이때는 덮어쓰지 않고 ConflictError를 낸다.
읽을 수 없는 데이터는 버리지 않고 ledger_backup_<timestamp>로 옮긴다.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import ledger_core as core

CHUNK_SIZE = 40_000
LOCAL_FILE = Path(__file__).with_name("ledger_data.json")


class ConflictError(Exception):
    """다른 곳에서 먼저 저장해서 이번 저장을 하지 않았다."""


def _dumps(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


class LocalStore:
    name = "로컬 파일"

    def __init__(self, path: Path = LOCAL_FILE):
        self.path = path
        self.rev_path = path.with_suffix(".rev")

    def read(self) -> tuple[str | None, str]:
        """(JSON 글자 또는 None, revision)."""
        if not self.path.exists():
            return None, "0"
        rev = self.rev_path.read_text(encoding="utf-8").strip() if self.rev_path.exists() else "0"
        return self.path.read_text(encoding="utf-8"), rev

    def write(self, raw: str, expected_rev: str) -> str:
        _, rev = self.read()
        if rev != expected_rev:
            raise ConflictError
        new_rev = str(int(rev) + 1)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(raw, encoding="utf-8")
        os.replace(tmp, self.path)
        self.rev_path.write_text(new_rev, encoding="utf-8")
        return new_rev

    def backup(self, raw: str) -> str:
        key = f"{core.BACKUP_KEY_PREFIX}{int(time.time() * 1000)}"
        self.path.with_name(f"{key}.json").write_text(raw, encoding="utf-8")
        return key


class SheetStore:
    name = "Google Sheets"

    def __init__(self, service_account_info: dict, sheet_url: str):
        import gspread  # 로컬 모드에서는 설치하지 않아도 되게 여기서 불러온다

        client = gspread.service_account_from_dict(dict(service_account_info))
        self.book = client.open_by_url(sheet_url)
        try:
            self.ws = self.book.worksheet(core.STORAGE_KEY)
        except gspread.WorksheetNotFound:
            self.ws = self.book.add_worksheet(title=core.STORAGE_KEY, rows=100, cols=2)

    def _rev(self) -> str:
        return str(self.ws.acell("B1").value or "0")

    def read(self) -> tuple[str | None, str]:
        chunks = self.ws.col_values(1)
        rev = self._rev()
        if not chunks:
            return None, rev
        return "".join(chunks), rev

    def write(self, raw: str, expected_rev: str) -> str:
        if self._rev() != expected_rev:
            raise ConflictError
        chunks = [raw[i:i + CHUNK_SIZE] for i in range(0, len(raw), CHUNK_SIZE)] or [""]
        old_count = len(self.ws.col_values(1))
        rows = chunks + [""] * max(0, old_count - len(chunks))  # 예전 데이터가 더 길었으면 남은 칸을 비운다
        if self.ws.row_count < len(rows):
            self.ws.add_rows(len(rows) - self.ws.row_count)
        new_rev = str(int(expected_rev) + 1)
        # 내용과 revision을 요청 한 번에 쓴다. RAW라서 "="로 시작하는 조각도 수식이 되지 않는다
        self.ws.batch_update([
            {"range": f"A1:A{len(rows)}", "values": [[chunk] for chunk in rows]},
            {"range": "B1", "values": [[new_rev]]},
        ], value_input_option="RAW")
        return new_rev

    def backup(self, raw: str) -> str:
        key = f"{core.BACKUP_KEY_PREFIX}{int(time.time() * 1000)}"
        chunks = [raw[i:i + CHUNK_SIZE] for i in range(0, len(raw), CHUNK_SIZE)] or [""]
        ws = self.book.add_worksheet(title=key, rows=max(len(chunks), 1), cols=1)
        ws.update(range_name=f"A1:A{len(chunks)}", values=[[c] for c in chunks], value_input_option="RAW")
        return key


def load_state(store, notices: list) -> tuple[dict, str]:
    """저장된 상태를 읽는다. 없으면 기본 상태, 읽을 수 없으면 백업해 두고 새로 시작한다."""
    raw, rev = store.read()
    if raw is None:
        return core.create_initial_state(), rev
    try:
        data = json.loads(raw)
        if not core.is_valid_state(data) or data["schemaVersion"] > core.SCHEMA_VERSION:
            raise ValueError("invalid shape")
        return core.migrate(data), rev
    except Exception:
        try:
            key = store.backup(raw)
            core.add_notice(notices, "error",
                            f'저장된 데이터를 읽을 수 없어 새로 시작했어요. 이전 데이터는 "{key}"에 보관했어요.')
        except Exception:
            core.add_notice(notices, "error", "저장된 데이터를 읽을 수 없어 새로 시작했어요. 이전 데이터를 보관하지 못했어요.")
        return core.create_initial_state(), rev


def save_state(store, state: dict, expected_rev: str) -> str:
    """주기 기록 요약을 다시 계산한 뒤 저장하고 새 revision을 돌려준다."""
    core.refresh_cycle_history(state)
    return store.write(_dumps(state), expected_rev)
