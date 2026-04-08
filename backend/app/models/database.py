"""
═══════════════════════════════════════════════════════════════
SQLite 데이터베이스 모델 및 초기화 로직
═══════════════════════════════════════════════════════════════
은행 원장(Ledger) 구조를 모방한 테이블 설계.

테이블 구조:
  1. customers    - 고객 기본 정보 (CIF: Customer Information File)
  2. accounts     - 계좌 정보 (원장의 계좌 마스터)
  3. transactions - 거래 이력 (거래 원장)
  4. fds_logs     - FDS 심사 이력 (감사 추적용)

※ 실제 은행에서는 이 테이블들이 별도 DB 인스턴스에 분리되어 있으며,
   거래 원장은 절대 삭제(DELETE)하지 않고 INSERT만 수행합니다.
   (감사 추적성 확보를 위한 금융권 필수 원칙)
═══════════════════════════════════════════════════════════════
"""

import sqlite3
import os
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timedelta
import random
import hashlib


# DB 파일 경로 (프로젝트 data/ 폴더에 생성)
DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DB_DIR / "fds_bank.db"


def get_db_path() -> str:
    """DB 파일 경로 반환. data 디렉토리가 없으면 자동 생성."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    return str(DB_PATH)


@contextmanager
def get_db_connection():
    """
    SQLite DB 연결 컨텍스트 매니저.

    ※ WAL(Write-Ahead Logging) 모드를 사용하여
      읽기/쓰기 동시 접근 시 성능을 확보합니다.
      실제 운영 환경에서는 PostgreSQL의 MVCC를 사용합니다.
    """
    conn = sqlite3.connect(get_db_path())
    conn.execute("PRAGMA journal_mode=WAL")   # 동시성 향상
    conn.execute("PRAGMA foreign_keys=ON")    # 외래키 제약 활성화
    conn.row_factory = sqlite3.Row            # dict-like 결과 반환
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ════════════════════════════════════════════
# 테이블 생성 DDL
# ════════════════════════════════════════════

CREATE_TABLES_SQL = """
-- ────────────────────────────────────
-- 1. 고객 정보 테이블 (CIF: Customer Information File)
-- 은행의 고객 마스터 테이블을 모방.
-- 실제 은행에서는 KYC(Know Your Customer) 정보까지 포함.
-- ────────────────────────────────────
CREATE TABLE IF NOT EXISTS customers (
    customer_id     TEXT PRIMARY KEY,           -- 고객 고유 ID (예: CUST_001)
    name            TEXT NOT NULL,              -- 고객명 (마스킹 처리된 형태)
    phone_masked    TEXT,                       -- 연락처 (뒤 4자리만 노출)
    email_masked    TEXT,                       -- 이메일 (@ 앞 3자리만 노출)
    risk_grade      TEXT DEFAULT 'NORMAL',      -- 고객 위험 등급 (NORMAL/CAUTION/HIGH)
    created_at      TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT DEFAULT (datetime('now', 'localtime'))
);

-- ────────────────────────────────────
-- 2. 계좌 정보 테이블
-- 하나의 고객이 여러 계좌를 가질 수 있음 (1:N 관계).
-- 잔액(balance)은 실시간 업데이트되는 핵심 필드.
-- ────────────────────────────────────
CREATE TABLE IF NOT EXISTS accounts (
    account_id      TEXT PRIMARY KEY,           -- 계좌 식별자 (PaySim의 name에 대응)
    customer_id     TEXT NOT NULL,              -- 소유 고객 ID
    account_type    TEXT NOT NULL DEFAULT 'C',  -- C: 개인, M: 가맹점
    balance         REAL NOT NULL DEFAULT 0.0,  -- 현재 잔액
    daily_limit     REAL DEFAULT 5000000.0,     -- 1일 이체한도 (기본 500만원)
    status          TEXT DEFAULT 'ACTIVE',      -- ACTIVE/FROZEN/CLOSED
    created_at      TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

-- ────────────────────────────────────
-- 3. 거래 이력 테이블 (거래 원장)
-- 금융권 원칙: INSERT ONLY (수정/삭제 불가).
-- 모든 거래는 영구 보관되며 감사 추적의 근거가 됨.
-- PaySim 데이터 구조를 기반으로 설계.
-- ────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    tx_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_no     TEXT UNIQUE NOT NULL,        -- 전문번호 (고유)
    step            INTEGER NOT NULL,            -- 시뮬레이션 시간 단위 (PaySim)
    tx_type         TEXT NOT NULL,               -- 거래 유형 (TRANSFER, CASH_OUT 등)
    amount          REAL NOT NULL,               -- 거래 금액
    sender_id       TEXT NOT NULL,               -- 송금 계좌
    sender_bal_before   REAL NOT NULL,           -- 송금인 거래 전 잔액
    sender_bal_after    REAL NOT NULL,           -- 송금인 거래 후 잔액
    receiver_id     TEXT NOT NULL,               -- 수취 계좌
    receiver_bal_before REAL NOT NULL,           -- 수취인 거래 전 잔액
    receiver_bal_after  REAL NOT NULL,           -- 수취인 거래 후 잔액
    is_fraud        INTEGER DEFAULT 0,           -- 실제 사기 여부 (라벨)
    channel_code    TEXT DEFAULT 'MB',           -- 거래 채널
    created_at      TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (sender_id) REFERENCES accounts(account_id),
    FOREIGN KEY (receiver_id) REFERENCES accounts(account_id)
);

-- ────────────────────────────────────
-- 4. FDS 심사 이력 테이블 (감사 로그)
-- 모든 FDS 판단 결과를 기록하여 추후 모델 성능 분석,
-- 오탐/미탐 분석, 금융감독원 감사에 활용.
-- ────────────────────────────────────
CREATE TABLE IF NOT EXISTS fds_logs (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_no     TEXT NOT NULL,               -- 심사 대상 전문번호
    risk_score      REAL NOT NULL,               -- 사기 확률 (0.0 ~ 1.0)
    risk_level      TEXT NOT NULL,               -- 위험 등급
    action_taken    TEXT NOT NULL,               -- 대응 조치 (APPROVE/BLOCK 등)
    reason          TEXT,                        -- 판단 근거
    model_version   TEXT DEFAULT 'v1',           -- 사용 모델 버전
    processing_ms   REAL,                        -- 처리 시간 (ms)
    created_at      TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (telegram_no) REFERENCES transactions(telegram_no)
);

-- 조회 성능을 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender_id);
CREATE INDEX IF NOT EXISTS idx_tx_receiver ON transactions(receiver_id);
CREATE INDEX IF NOT EXISTS idx_tx_created ON transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_fds_telegram ON fds_logs(telegram_no);
CREATE INDEX IF NOT EXISTS idx_fds_risk ON fds_logs(risk_level);
"""


def init_db():
    """
    데이터베이스 초기화: 테이블 생성.
    서버 시작 시 자동 호출되며, IF NOT EXISTS로 멱등성 보장.
    """
    with get_db_connection() as conn:
        conn.executescript(CREATE_TABLES_SQL)
    print(f"[DB] 테이블 초기화 완료 → {DB_PATH}")


# ════════════════════════════════════════════
# 더미 데이터 삽입 (PaySim 구조 기반)
# ════════════════════════════════════════════

def seed_dummy_data():
    """
    테스트용 더미 데이터 삽입.

    PaySim 데이터 구조를 기반으로 10명의 고객과
    다양한 거래 패턴을 가진 과거 거래 이력을 생성합니다.

    ※ 더미 고객 프로필:
      - 정상 고객 7명: 일상적인 패턴 (소액 이체, 급여 입금 등)
      - 주의 고객 2명: 간헐적 고액 거래 패턴
      - 고위험 고객 1명: 다수 계좌 분산 이체 패턴 (사기 시뮬레이션)
    """
    with get_db_connection() as conn:
        # 이미 데이터가 있으면 스킵 (멱등성)
        existing = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        if existing > 0:
            print(f"[DB] 기존 데이터 {existing}명 존재 → 더미 삽입 스킵")
            return

        # ── 고객 데이터 ──
        customers = [
            ("CUST_001", "김*현", "010-****-1234", "kim***@naver.com",   "NORMAL"),
            ("CUST_002", "이*수", "010-****-5678", "lee***@gmail.com",   "NORMAL"),
            ("CUST_003", "박*진", "010-****-9012", "par***@daum.net",    "NORMAL"),
            ("CUST_004", "최*미", "010-****-3456", "cho***@naver.com",   "NORMAL"),
            ("CUST_005", "정*호", "010-****-7890", "jun***@kakao.com",   "NORMAL"),
            ("CUST_006", "강*서", "010-****-2345", "kan***@naver.com",   "NORMAL"),
            ("CUST_007", "윤*리", "010-****-6789", "yoo***@gmail.com",   "NORMAL"),
            ("CUST_008", "한*석", "010-****-0123", "han***@naver.com",   "CAUTION"),
            ("CUST_009", "서*영", "010-****-4567", "seo***@daum.net",    "CAUTION"),
            ("CUST_010", "임*우", "010-****-8901", "lim***@gmail.com",   "HIGH"),
        ]
        conn.executemany(
            "INSERT INTO customers (customer_id, name, phone_masked, email_masked, risk_grade) VALUES (?,?,?,?,?)",
            customers
        )

        # ── 계좌 데이터 ──
        # 각 고객에게 1~2개 계좌 부여 + 가맹점 2개
        accounts = [
            # 개인 고객 계좌
            ("C1000000001", "CUST_001", "C", 1_500_000.0,  5_000_000.0, "ACTIVE"),
            ("C1000000002", "CUST_002", "C", 3_200_000.0,  5_000_000.0, "ACTIVE"),
            ("C1000000003", "CUST_003", "C", 850_000.0,    5_000_000.0, "ACTIVE"),
            ("C1000000004", "CUST_004", "C", 12_000_000.0, 10_000_000.0,"ACTIVE"),
            ("C1000000005", "CUST_005", "C", 600_000.0,    5_000_000.0, "ACTIVE"),
            ("C1000000006", "CUST_006", "C", 2_100_000.0,  5_000_000.0, "ACTIVE"),
            ("C1000000007", "CUST_007", "C", 4_800_000.0,  5_000_000.0, "ACTIVE"),
            ("C1000000008", "CUST_008", "C", 25_000_000.0, 10_000_000.0,"ACTIVE"),
            ("C1000000009", "CUST_009", "C", 8_500_000.0,  10_000_000.0,"ACTIVE"),
            ("C1000000010", "CUST_010", "C", 500_000.0,    5_000_000.0, "ACTIVE"),
            # 고위험 고객의 두 번째 계좌
            ("C1000000011", "CUST_010", "C", 200_000.0,    5_000_000.0, "ACTIVE"),
            # 가맹점 계좌
            ("M2000000001", "CUST_001", "M", 50_000_000.0, 100_000_000.0, "ACTIVE"),
            ("M2000000002", "CUST_004", "M", 30_000_000.0, 100_000_000.0, "ACTIVE"),
        ]
        conn.executemany(
            "INSERT INTO accounts (account_id, customer_id, account_type, balance, daily_limit, status) VALUES (?,?,?,?,?,?)",
            accounts
        )

        # ── 거래 이력 데이터 (PaySim 구조 모방) ──
        # 다양한 패턴의 과거 거래를 생성하여 FDS가 비교 분석 가능하도록 함
        random.seed(42)  # 재현성 보장

        tx_types = ["TRANSFER", "CASH_OUT", "PAYMENT", "CASH_IN", "DEBIT"]
        channels = ["MB", "IB", "AT", "TL"]

        transactions = []
        tx_counter = 0

        for step in range(1, 51):  # 50 시간 단위의 과거 데이터
            # 각 step에서 2~5건의 거래 발생
            num_tx = random.randint(2, 5)
            for _ in range(num_tx):
                tx_counter += 1
                tx_type = random.choice(tx_types)
                channel = random.choice(channels)

                # 송금/수취 계좌 선택 (자기 자신에게 보내는 것 방지)
                sender_accts = [a[0] for a in accounts if a[2] == "C"]
                sender = random.choice(sender_accts)
                receiver_pool = [a[0] for a in accounts if a[0] != sender]
                receiver = random.choice(receiver_pool)

                # 거래 금액 결정 (일반적인 패턴)
                if tx_type in ["TRANSFER", "CASH_OUT"]:
                    amount = round(random.uniform(10_000, 2_000_000), 0)
                elif tx_type == "PAYMENT":
                    amount = round(random.uniform(5_000, 500_000), 0)
                else:
                    amount = round(random.uniform(50_000, 3_000_000), 0)

                # 잔액 계산 (단순화)
                sender_bal = dict((a[0], a[3]) for a in accounts).get(sender, 1_000_000)
                receiver_bal = dict((a[0], a[3]) for a in accounts).get(receiver, 500_000)

                telegram_no = f"2026040{random.randint(1,8)}{channel}{tx_counter:010d}"

                # 대부분 정상, 일부 사기 라벨링 (고위험 고객 거래의 일부)
                is_fraud = 1 if (sender in ["C1000000010", "C1000000011"] and amount > 1_000_000 and random.random() < 0.4) else 0

                transactions.append((
                    telegram_no, step, tx_type, amount,
                    sender, sender_bal, sender_bal - amount,
                    receiver, receiver_bal, receiver_bal + amount,
                    is_fraud, channel
                ))

        conn.executemany(
            """INSERT INTO transactions
               (telegram_no, step, tx_type, amount,
                sender_id, sender_bal_before, sender_bal_after,
                receiver_id, receiver_bal_before, receiver_bal_after,
                is_fraud, channel_code)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            transactions
        )

        fraud_count = sum(1 for t in transactions if t[10] == 1)
        print(f"[DB] 더미 데이터 삽입 완료:")
        print(f"     - 고객: {len(customers)}명")
        print(f"     - 계좌: {len(accounts)}개")
        print(f"     - 거래: {len(transactions)}건 (사기: {fraud_count}건)")


# ════════════════════════════════════════════
# DB 조회 유틸리티 함수
# ════════════════════════════════════════════

def get_account_info(account_id: str) -> dict | None:
    """계좌 정보 조회."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        return dict(row) if row else None


def get_recent_transactions(account_id: str, hours: int = 24) -> list[dict]:
    """
    특정 계좌의 최근 N시간 내 거래 이력 조회.
    FDS Metadata의 파생 피처 계산에 활용.
    """
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM transactions
               WHERE (sender_id = ? OR receiver_id = ?)
                 AND created_at >= datetime('now', 'localtime', ?)
               ORDER BY created_at DESC""",
            (account_id, account_id, f"-{hours} hours")
        ).fetchall()
        return [dict(r) for r in rows]


def get_tx_stats(account_id: str, hours: int) -> dict:
    """
    특정 계좌의 최근 N시간 거래 통계.
    FDS Metadata 자동 계산에 사용.
    """
    with get_db_connection() as conn:
        row = conn.execute(
            """SELECT
                 COUNT(*) as tx_count,
                 COALESCE(SUM(amount), 0) as tx_amount_sum,
                 COALESCE(AVG(amount), 0) as avg_amount
               FROM transactions
               WHERE sender_id = ?
                 AND created_at >= datetime('now', 'localtime', ?)""",
            (account_id, f"-{hours} hours")
        ).fetchone()
        return dict(row)


def insert_transaction(tx_data: dict):
    """거래 이력 INSERT (원장 기록)."""
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO transactions
               (telegram_no, step, tx_type, amount,
                sender_id, sender_bal_before, sender_bal_after,
                receiver_id, receiver_bal_before, receiver_bal_after,
                is_fraud, channel_code)
               VALUES (:telegram_no, :step, :tx_type, :amount,
                       :sender_id, :sender_bal_before, :sender_bal_after,
                       :receiver_id, :receiver_bal_before, :receiver_bal_after,
                       :is_fraud, :channel_code)""",
            tx_data
        )


def insert_fds_log(log_data: dict):
    """FDS 심사 결과 기록 (감사 로그)."""
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO fds_logs
               (telegram_no, risk_score, risk_level, action_taken,
                reason, model_version, processing_ms)
               VALUES (:telegram_no, :risk_score, :risk_level, :action_taken,
                       :reason, :model_version, :processing_ms)""",
            log_data
        )


def update_account_balance(account_id: str, new_balance: float):
    """계좌 잔액 업데이트."""
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE accounts SET balance = ? WHERE account_id = ?",
            (new_balance, account_id)
        )
