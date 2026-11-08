import sqlite3
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from config import DATABASE_FILE, TIMEZONE, GIVEAWAY_END_AT, QUALIFICATION_REFERRALS, LEADERBOARD_LIMIT

IST = TIMEZONE if isinstance(TIMEZONE, ZoneInfo) else ZoneInfo("Asia/Kolkata")
# The deployed config previously had GIVEAWAY_END_AT=None. Keep the known
# scheduled deadline as a safe fallback so date checks do not crash.
if GIVEAWAY_END_AT is None:
    GIVEAWAY_END_AT = datetime(2026, 11, 8, 12, 0, 0, tzinfo=IST)


def current_datetime():
    return datetime.now(IST)


def current_time():
    return current_datetime().strftime("%Y-%m-%d %H:%M:%S")


def current_date():
    return current_datetime().strftime("%Y-%m-%d")


def giveaway_cutoff_string():
    return GIVEAWAY_END_AT.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")


def giveaway_has_ended():
    return current_datetime() >= GIVEAWAY_END_AT.astimezone(IST)


@contextmanager
def get_db():
    connection = sqlite3.connect(DATABASE_FILE, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with get_db() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT,
                first_name TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '',
                total_coins INTEGER NOT NULL DEFAULT 0 CHECK(total_coins >= 0),
                verified INTEGER NOT NULL DEFAULT 0, joined_at TEXT NOT NULL,
                last_seen TEXT NOT NULL, welcome_bonus_claimed INTEGER NOT NULL DEFAULT 0,
                daily_bonus_date TEXT, referred_by INTEGER,
                FOREIGN KEY (referred_by) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inviter_id INTEGER NOT NULL, referred_id INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','verified','rejected')),
                started_at TEXT NOT NULL, verified_at TEXT,
                reward_coins INTEGER NOT NULL DEFAULT 0, reward_paid INTEGER NOT NULL DEFAULT 0,
                giveaway_eligible INTEGER NOT NULL DEFAULT 1,
                post_deadline INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (inviter_id) REFERENCES users(user_id),
                FOREIGN KEY (referred_id) REFERENCES users(user_id),
                CHECK(inviter_id != referred_id)
            );
            CREATE INDEX IF NOT EXISTS idx_referrals_inviter ON referrals(inviter_id);
            CREATE INDEX IF NOT EXISTS idx_referrals_status ON referrals(status);
            CREATE INDEX IF NOT EXISTS idx_referrals_giveaway
                ON referrals(inviter_id,status,giveaway_eligible,verified_at);
            CREATE TABLE IF NOT EXISTS required_chat_checks (
                user_id INTEGER NOT NULL, chat_id TEXT NOT NULL,
                is_member INTEGER NOT NULL DEFAULT 0, checked_at TEXT NOT NULL,
                PRIMARY KEY(user_id,chat_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS coin_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL, transaction_type TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '', admin_id INTEGER, created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_transactions_user ON coin_transactions(user_id,id DESC);
            CREATE INDEX IF NOT EXISTS idx_transactions_type_date
                ON coin_transactions(transaction_type,created_at,user_id);
            CREATE TABLE IF NOT EXISTS redeem_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE COLLATE NOCASE,
                reward_coins INTEGER NOT NULL DEFAULT 0 CHECK(reward_coins >= 0),
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
                added_by INTEGER, added_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS redeem_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, code_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL, redeemed_at TEXT NOT NULL,
                UNIQUE(code_id,user_id), FOREIGN KEY(code_id) REFERENCES redeem_codes(id),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_redeem_history_user ON redeem_history(user_id);
            CREATE TABLE IF NOT EXISTS bot_settings (
                setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS backup_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, backup_path TEXT NOT NULL,
                backup_type TEXT NOT NULL, created_at TEXT NOT NULL, created_by INTEGER,
                status TEXT NOT NULL DEFAULT 'success', notes TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS giveaway_results (
                user_id INTEGER PRIMARY KEY, final_rank INTEGER NOT NULL UNIQUE,
                username TEXT, first_name TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '',
                verified_referrals INTEGER NOT NULL DEFAULT 0,
                referral_coins INTEGER NOT NULL DEFAULT 0, reward_type TEXT NOT NULL DEFAULT '',
                reward_choice TEXT, selection_confirmed INTEGER NOT NULL DEFAULT 0,
                selection_confirmed_at TEXT,
                notification_status TEXT NOT NULL DEFAULT 'pending', finalized_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_giveaway_results_rank ON giveaway_results(final_rank);
            CREATE TABLE IF NOT EXISTS giveaway_state (
                state_key TEXT PRIMARY KEY, state_value TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS giveaway_post_deadline_referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, inviter_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE, verified_at TEXT NOT NULL,
                reward_paid INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(inviter_id) REFERENCES users(user_id),
                FOREIGN KEY(referred_id) REFERENCES users(user_id)
            );
        """)
        # Safe migrations; existing rows are preserved.
        redeem_cols = {r["name"] for r in db.execute("PRAGMA table_info(redeem_codes)").fetchall()}
        if "max_users" not in redeem_cols:
            db.execute("ALTER TABLE redeem_codes ADD COLUMN max_users INTEGER")
        referral_cols = {r["name"] for r in db.execute("PRAGMA table_info(referrals)").fetchall()}
        if "giveaway_eligible" not in referral_cols:
            db.execute("ALTER TABLE referrals ADD COLUMN giveaway_eligible INTEGER NOT NULL DEFAULT 1")
        if "post_deadline" not in referral_cols:
            db.execute("ALTER TABLE referrals ADD COLUMN post_deadline INTEGER NOT NULL DEFAULT 0")


def register_user(user_id, username=None, first_name="", last_name="", referred_by=None):
    user_id = int(user_id)
    if referred_by is not None:
        referred_by = int(referred_by)
        if referred_by == user_id:
            referred_by = None
    now = current_time()
    with get_db() as db:
        existing = db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        if existing:
            db.execute("UPDATE users SET username=?,first_name=?,last_name=?,last_seen=? WHERE user_id=?",
                       (username, first_name or "", last_name or "", now, user_id))
            return False
        if referred_by is not None and not db.execute("SELECT user_id FROM users WHERE user_id=?", (referred_by,)).fetchone():
            referred_by = None
        db.execute("""INSERT INTO users(user_id,username,first_name,last_name,total_coins,verified,
                    joined_at,last_seen,welcome_bonus_claimed,daily_bonus_date,referred_by)
                    VALUES(?,?,?,?,0,0,?,?,0,NULL,?)""",
                   (user_id, username, first_name or "", last_name or "", now, now, referred_by))
        return True


def get_user(user_id):
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE user_id=?", (int(user_id),)).fetchone()
        return dict(row) if row else None


def get_all_users():
    with get_db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM users ORDER BY joined_at ASC").fetchall()]


def update_user_profile(user_id, username=None, first_name="", last_name=""):
    with get_db() as db:
        db.execute("UPDATE users SET username=?,first_name=?,last_name=?,last_seen=? WHERE user_id=?",
                   (username, first_name or "", last_name or "", current_time(), int(user_id)))
        return db.total_changes > 0


def mark_user_verified(user_id):
    with get_db() as db:
        db.execute("UPDATE users SET verified=1,last_seen=? WHERE user_id=?", (current_time(), int(user_id)))
        return db.total_changes > 0


def has_claimed_welcome_bonus(user_id):
    with get_db() as db:
        row = db.execute("SELECT welcome_bonus_claimed FROM users WHERE user_id=?", (int(user_id),)).fetchone()
        return bool(row and row["welcome_bonus_claimed"])


def claim_welcome_bonus(user_id, amount):
    user_id, amount = int(user_id), int(amount)
    if amount < 0:
        raise ValueError("Bonus amount cannot be negative.")
    now = current_time()
    with get_db() as db:
        user = db.execute("SELECT verified,welcome_bonus_claimed FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user or not user["verified"] or user["welcome_bonus_claimed"]:
            return False
        db.execute("UPDATE users SET total_coins=total_coins+?,welcome_bonus_claimed=1 WHERE user_id=? AND verified=1 AND welcome_bonus_claimed=0", (amount, user_id))
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            return False
        db.execute("INSERT INTO coin_transactions(user_id,amount,transaction_type,description,created_at) VALUES(?,?,'welcome_bonus',?,?)",
                   (user_id, amount, "Welcome bonus", now))
        return True


def claim_daily_bonus(user_id, amount):
    user_id, amount = int(user_id), int(amount)
    today = current_date()
    if amount < 0:
        raise ValueError("Bonus amount cannot be negative.")
    with get_db() as db:
        user = db.execute("SELECT verified,daily_bonus_date FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user or not user["verified"] or user["daily_bonus_date"] == today:
            return False
        db.execute("""UPDATE users SET total_coins=total_coins+?,daily_bonus_date=?
                    WHERE user_id=? AND verified=1 AND (daily_bonus_date IS NULL OR daily_bonus_date != ?)""",
                   (amount, today, user_id, today))
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            return False
        db.execute("INSERT INTO coin_transactions(user_id,amount,transaction_type,description,created_at) VALUES(?,?,'daily_bonus',?,?)",
                   (user_id, amount, "Daily bonus", current_time()))
        return True


def add_pending_referral(inviter_id, referred_id):
    inviter_id, referred_id = int(inviter_id), int(referred_id)
    if inviter_id == referred_id:
        return False
    now = current_time()
    after_cutoff = giveaway_has_ended()
    with get_db() as db:
        if not db.execute("SELECT user_id FROM users WHERE user_id=?", (inviter_id,)).fetchone():
            return False
        referred = db.execute("SELECT user_id,referred_by FROM users WHERE user_id=?", (referred_id,)).fetchone()
        if not referred or referred["referred_by"] not in (None, inviter_id):
            return False
        if db.execute("SELECT id FROM referrals WHERE referred_id=?", (referred_id,)).fetchone():
            return False
        db.execute("""INSERT INTO referrals(inviter_id,referred_id,status,started_at,reward_coins,
                    reward_paid,giveaway_eligible,post_deadline)
                    VALUES(?,?,'pending',?,0,0,?,?)""",
                   (inviter_id, referred_id, now, 0 if after_cutoff else 1, 1 if after_cutoff else 0))
        db.execute("UPDATE users SET referred_by=? WHERE user_id=? AND referred_by IS NULL", (inviter_id, referred_id))
        return True


def verify_referral(referred_id, reward_amount):
    """Verify once. Post-cutoff referrals are recorded but receive no coins."""
    referred_id, reward_amount = int(referred_id), int(reward_amount)
    if reward_amount < 0:
        raise ValueError("Reward amount cannot be negative.")
    now_dt = current_datetime()
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    post_deadline = now_dt >= GIVEAWAY_END_AT.astimezone(IST)
    with get_db() as db:
        referral = db.execute("SELECT * FROM referrals WHERE referred_id=?", (referred_id,)).fetchone()
        if not referral or referral["status"] != "pending":
            return None
        inviter_id = int(referral["inviter_id"])
        if not db.execute("SELECT user_id FROM users WHERE user_id=?", (referred_id,)).fetchone():
            return None
        if not db.execute("SELECT user_id FROM users WHERE user_id=?", (inviter_id,)).fetchone():
            return None
        paid_reward = 0 if post_deadline else reward_amount
        eligible = 0 if post_deadline else int(referral["giveaway_eligible"])
        db.execute("UPDATE users SET verified=1,last_seen=? WHERE user_id=?", (now, referred_id))
        db.execute("""UPDATE referrals SET status='verified',verified_at=?,reward_coins=?,reward_paid=?,
                    giveaway_eligible=?,post_deadline=? WHERE id=? AND status='pending'""",
                   (now, paid_reward, 0 if post_deadline else 1, eligible, 1 if post_deadline else 0, referral["id"]))
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            return None
        if post_deadline:
            db.execute("""INSERT OR IGNORE INTO giveaway_post_deadline_referrals
                        (inviter_id,referred_id,verified_at,reward_paid,notes) VALUES(?,?,?,0,?)""",
                       (inviter_id, referred_id, now, "Verified after giveaway deadline; no referral coins paid."))
        else:
            db.execute("UPDATE users SET total_coins=total_coins+? WHERE user_id=?", (reward_amount, inviter_id))
            db.execute("""INSERT INTO coin_transactions(user_id,amount,transaction_type,description,created_at)
                        VALUES(?,?,'referral_reward',?,?)""", (inviter_id, reward_amount, f"Verified referral: {referred_id}", now))
        return {"inviter_id": inviter_id, "referred_id": referred_id, "reward_coins": paid_reward,
                "verified_at": now, "post_deadline": post_deadline}


def get_referral_counts(user_id):
    with get_db() as db:
        row = db.execute("""SELECT COUNT(CASE WHEN status='verified' THEN 1 END) AS verified_referrals,
                    COUNT(CASE WHEN status='pending' THEN 1 END) AS pending_referrals
                    FROM referrals WHERE inviter_id=?""", (int(user_id),)).fetchone()
        return {"verified_referrals": row["verified_referrals"], "pending_referrals": row["pending_referrals"]}


def get_referrals(user_id):
    with get_db() as db:
        rows = db.execute("""SELECT r.*,u.username,u.first_name,u.last_name FROM referrals r
                    JOIN users u ON u.user_id=r.referred_id WHERE r.inviter_id=? ORDER BY r.started_at DESC""",
                          (int(user_id),)).fetchall()
        return [dict(r) for r in rows]


def get_leaderboard(limit=50, offset=0):
    limit, offset = max(1, min(int(limit), 1000)), max(0, int(offset))
    with get_db() as db:
        rows = db.execute("""SELECT u.user_id,u.username,u.first_name,u.last_name,u.total_coins,
                    COUNT(CASE WHEN r.status='verified' THEN 1 END) AS verified_referrals,
                    COUNT(CASE WHEN r.status='pending' THEN 1 END) AS pending_referrals
                    FROM users u LEFT JOIN referrals r ON r.inviter_id=u.user_id
                    WHERE u.verified=1 GROUP BY u.user_id
                    ORDER BY u.total_coins DESC,verified_referrals DESC,u.user_id ASC LIMIT ? OFFSET ?""",
                          (limit, offset)).fetchall()
        return [dict(r) for r in rows]


def get_user_rank(user_id):
    with get_db() as db:
        user = db.execute("SELECT total_coins FROM users WHERE user_id=? AND verified=1", (int(user_id),)).fetchone()
        if not user:
            return None
        row = db.execute("SELECT COUNT(*)+1 AS rank FROM users WHERE verified=1 AND total_coins>?", (user["total_coins"],)).fetchone()
        return row["rank"]


def add_coins(user_id, amount, description="Admin coin addition", admin_id=None, transaction_type="admin_add"):
    user_id, amount = int(user_id), int(amount)
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    with get_db() as db:
        if not db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone():
            return False
        db.execute("UPDATE users SET total_coins=total_coins+? WHERE user_id=?", (amount, user_id))
        db.execute("""INSERT INTO coin_transactions(user_id,amount,transaction_type,description,admin_id,created_at)
                    VALUES(?,?,?,?,?,?)""", (user_id, amount, transaction_type, description, admin_id, current_time()))
        return True


def deduct_coins(user_id, amount, description="Admin coin deduction", admin_id=None, transaction_type="admin_deduct"):
    user_id, amount = int(user_id), int(amount)
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    with get_db() as db:
        db.execute("UPDATE users SET total_coins=total_coins-? WHERE user_id=? AND total_coins>=?", (amount, user_id, amount))
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            return False
        db.execute("""INSERT INTO coin_transactions(user_id,amount,transaction_type,description,admin_id,created_at)
                    VALUES(?,?,?,?,?,?)""", (user_id, -amount, transaction_type, description, admin_id, current_time()))
        return True


def get_coin_transactions(user_id, limit=50):
    limit = max(1, min(int(limit), 1000))
    with get_db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM coin_transactions WHERE user_id=? ORDER BY id DESC LIMIT ?", (int(user_id), limit)).fetchall()]


def get_giveaway_qualification_count(user_id):
    with get_db() as db:
        row = db.execute("""SELECT COUNT(*) AS count FROM referrals WHERE inviter_id=? AND status='verified'
                    AND giveaway_eligible=1 AND post_deadline=0 AND verified_at<=?""",
                          (int(user_id), giveaway_cutoff_string())).fetchone()
        return int(row["count"] or 0)


def get_giveaway_referral_coins(user_id):
    with get_db() as db:
        row = db.execute("""SELECT COALESCE(SUM(amount),0) AS coins FROM coin_transactions
                    WHERE user_id=? AND transaction_type='referral_reward' AND amount>0 AND created_at<=?""",
                          (int(user_id), giveaway_cutoff_string())).fetchone()
        return int(row["coins"] or 0)


def get_giveaway_results():
    with get_db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM giveaway_results ORDER BY final_rank").fetchall()]


def get_giveaway_result(user_id):
    with get_db() as db:
        row = db.execute("SELECT * FROM giveaway_results WHERE user_id=?", (int(user_id),)).fetchone()
        return dict(row) if row else None


def get_giveaway_state(key, default=None):
    with get_db() as db:
        row = db.execute("SELECT state_value FROM giveaway_state WHERE state_key=?", (str(key),)).fetchone()
        return row["state_value"] if row else default


def set_giveaway_state(key, value):
    with get_db() as db:
        db.execute("""INSERT INTO giveaway_state(state_key,state_value,updated_at) VALUES(?,?,?)
                    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=excluded.updated_at""",
                   (str(key), str(value), current_time()))


def finalize_giveaway_results(force=False):
    """Freeze qualified Top 50 once; force=True is for controlled testing only."""
    if not force and not giveaway_has_ended():
        return {"success": False, "reason": "giveaway_not_ended", "deadline": giveaway_cutoff_string()}
    cutoff, finalized_at = giveaway_cutoff_string(), current_time()
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        state = db.execute("SELECT state_value FROM giveaway_state WHERE state_key='finalized'").fetchone()
        if state and state["state_value"] == "1":
            count = db.execute("SELECT COUNT(*) AS count FROM giveaway_results").fetchone()["count"]
            return {"success": True, "already_finalized": True, "winner_count": int(count)}
        candidates = db.execute("""
            WITH eligible AS (
                SELECT inviter_id,verified_at,id,
                       ROW_NUMBER() OVER(PARTITION BY inviter_id ORDER BY verified_at,id) AS rn
                FROM referrals WHERE status='verified' AND giveaway_eligible=1 AND post_deadline=0
                  AND verified_at IS NOT NULL AND verified_at<=?
            ), counts AS (
                SELECT inviter_id,COUNT(*) AS verified_referrals,
                       MAX(CASE WHEN rn=? THEN verified_at END) AS reached_qualification_at
                FROM eligible GROUP BY inviter_id
            ), coins AS (
                SELECT user_id,COALESCE(SUM(amount),0) AS referral_coins FROM coin_transactions
                WHERE transaction_type='referral_reward' AND amount>0 AND created_at<=? GROUP BY user_id
            )
            SELECT u.user_id,u.username,u.first_name,u.last_name,c.verified_referrals,
                   COALESCE(co.referral_coins,0) AS referral_coins,c.reached_qualification_at
            FROM counts c JOIN users u ON u.user_id=c.inviter_id
            LEFT JOIN coins co ON co.user_id=u.user_id
            WHERE c.verified_referrals>=? AND u.verified=1
            ORDER BY referral_coins DESC,c.verified_referrals DESC,c.reached_qualification_at ASC,u.user_id ASC
        """, (cutoff, int(QUALIFICATION_REFERRALS), cutoff, int(QUALIFICATION_REFERRALS))).fetchall()
        max_winners = max(1, int(LEADERBOARD_LIMIT))
        winners = candidates[:max_winners]
        for rank, user in enumerate(winners, 1):
            if rank <= 3:
                reward_type = "fixed"
            elif rank <= 10:
                reward_type = "teddy_and_account"
            elif rank <= 33:
                reward_type = "teddy"
            else:
                reward_type = "account"
            db.execute("""INSERT INTO giveaway_results(user_id,final_rank,username,first_name,last_name,
                        verified_referrals,referral_coins,reward_type,selection_confirmed,notification_status,finalized_at)
                        VALUES(?,?,?,?,?,?,?,?,0,'pending',?)""",
                       (user["user_id"], rank, user["username"], user["first_name"] or "", user["last_name"] or "",
                        int(user["verified_referrals"] or 0), int(user["referral_coins"] or 0), reward_type, finalized_at))
        db.execute("""INSERT INTO giveaway_state(state_key,state_value,updated_at) VALUES('finalized','1',?)
                    ON CONFLICT(state_key) DO UPDATE SET state_value='1',updated_at=excluded.updated_at""", (finalized_at,))
        db.execute("""INSERT INTO giveaway_state(state_key,state_value,updated_at) VALUES('finalized_at',?,?)
                    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=excluded.updated_at""",
                   (finalized_at, finalized_at))
        return {"success": True, "already_finalized": False, "qualified_count": len(candidates),
                "winner_count": len(winners), "qualified_but_not_top_50": max(0, len(candidates)-len(winners)),
                "finalized_at": finalized_at}


def save_giveaway_reward_choice(user_id, choice):
    user_id, choice = int(user_id), str(choice).strip().lower()
    if choice not in ("telegram", "whatsapp"):
        return {"success": False, "reason": "invalid_choice"}
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM giveaway_results WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return {"success": False, "reason": "not_a_winner"}
        if row["reward_type"] not in ("teddy_and_account", "account"):
            return {"success": False, "reason": "choice_not_required"}
        if row["selection_confirmed"]:
            return {"success": False, "reason": "already_confirmed", "choice": row["reward_choice"]}
        db.execute("UPDATE giveaway_results SET reward_choice=? WHERE user_id=? AND selection_confirmed=0", (choice, user_id))
        return {"success": True, "choice": choice}


def confirm_giveaway_reward_choice(user_id):
    user_id, now = int(user_id), current_time()
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM giveaway_results WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return {"success": False, "reason": "not_a_winner"}
        if row["reward_type"] not in ("teddy_and_account", "account"):
            return {"success": False, "reason": "confirmation_not_required"}
        if row["selection_confirmed"]:
            return {"success": True, "already_confirmed": True, "choice": row["reward_choice"], "rank": row["final_rank"]}
        if not row["reward_choice"]:
            return {"success": False, "reason": "choice_not_selected"}
        db.execute("UPDATE giveaway_results SET selection_confirmed=1,selection_confirmed_at=? WHERE user_id=? AND selection_confirmed=0 AND reward_choice IS NOT NULL", (now, user_id))
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            return {"success": False, "reason": "confirmation_failed"}
        return {"success": True, "already_confirmed": False, "choice": row["reward_choice"], "rank": row["final_rank"], "user_id": user_id}


def mark_giveaway_notification_status(user_id, status):
    if status not in {"pending", "sent", "failed"}:
        raise ValueError("Invalid notification status.")
    with get_db() as db:
        db.execute("UPDATE giveaway_results SET notification_status=? WHERE user_id=?", (status, int(user_id)))
        return db.total_changes > 0


def get_post_deadline_referral_report(limit=1000):
    limit = max(1, min(int(limit), 5000))
    with get_db() as db:
        rows = db.execute("""SELECT p.*,iu.username AS inviter_username,iu.first_name AS inviter_first_name,
                    ru.username AS referred_username,ru.first_name AS referred_first_name
                    FROM giveaway_post_deadline_referrals p
                    LEFT JOIN users iu ON iu.user_id=p.inviter_id
                    LEFT JOIN users ru ON ru.user_id=p.referred_id ORDER BY p.id DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_post_deadline_referral_count():
    with get_db() as db:
        return int(db.execute("SELECT COUNT(*) AS count FROM giveaway_post_deadline_referrals").fetchone()["count"] or 0)


def add_redeem_code(code, reward_coins=0, added_by=None, max_users=None):
    code, reward_coins = str(code).strip(), int(reward_coins)
    max_users = None if max_users in (None, "", 0, "0") else int(max_users)
    if not code:
        return False
    if reward_coins < 0:
        raise ValueError("Reward amount cannot be negative.")
    if max_users is not None and max_users < 1:
        raise ValueError("Maximum users must be at least 1.")
    try:
        with get_db() as db:
            db.execute("""INSERT INTO redeem_codes(code,reward_coins,status,added_by,added_at,max_users)
                        VALUES(?,?,'active',?,?,?)""", (code, reward_coins, added_by, current_time(), max_users))
        return True
    except sqlite3.IntegrityError:
        return False


def delete_redeem_code(code):
    with get_db() as db:
        cursor = db.execute("DELETE FROM redeem_codes WHERE code=?", (str(code).strip(),))
        return cursor.rowcount > 0


def get_redeem_codes(status=None):
    with get_db() as db:
        query = """SELECT c.*,(SELECT COUNT(*) FROM redeem_history h WHERE h.code_id=c.id) AS redeemed_count,
                   CASE WHEN c.max_users IS NULL THEN NULL ELSE MAX(c.max_users-(SELECT COUNT(*) FROM redeem_history h WHERE h.code_id=c.id),0) END AS remaining_users
                   FROM redeem_codes c"""
        params = ()
        if status:
            query += " WHERE c.status=?"
            params = (status,)
        query += " ORDER BY c.id DESC"
        return [dict(r) for r in db.execute(query, params).fetchall()]


def redeem_code(user_id, code):
    user_id, code, now = int(user_id), str(code).strip(), current_time()
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        user = db.execute("SELECT verified FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user or not user["verified"]:
            return {"success": False, "reason": "user_not_verified"}
        redeem = db.execute("SELECT * FROM redeem_codes WHERE code=? COLLATE NOCASE AND status='active'", (code,)).fetchone()
        if not redeem:
            return {"success": False, "reason": "invalid_or_inactive_code"}
        if db.execute("SELECT id FROM redeem_history WHERE code_id=? AND user_id=?", (redeem["id"], user_id)).fetchone():
            return {"success": False, "reason": "already_redeemed"}
        count = db.execute("SELECT COUNT(*) FROM redeem_history WHERE code_id=?", (redeem["id"],)).fetchone()[0]
        max_users = redeem["max_users"] if "max_users" in redeem.keys() else None
        if max_users is not None and count >= max_users:
            db.execute("UPDATE redeem_codes SET status='disabled' WHERE id=?", (redeem["id"],))
            return {"success": False, "reason": "code_limit_reached"}
        try:
            db.execute("INSERT INTO redeem_history(code_id,user_id,redeemed_at) VALUES(?,?,?)", (redeem["id"], user_id, now))
        except sqlite3.IntegrityError:
            return {"success": False, "reason": "already_redeemed"}
        reward = int(redeem["reward_coins"])
        if reward > 0:
            db.execute("UPDATE users SET total_coins=total_coins+? WHERE user_id=?", (reward, user_id))
            db.execute("INSERT INTO coin_transactions(user_id,amount,transaction_type,description,created_at) VALUES(?,?,'redeem_code',?,?)", (user_id, reward, f"Redeemed code: {redeem['code']}", now))
        count += 1
        if max_users is not None and count >= max_users:
            db.execute("UPDATE redeem_codes SET status='disabled' WHERE id=?", (redeem["id"],))
        return {"success": True, "code": redeem["code"], "reward_coins": reward, "redeemed_at": now,
                "max_users": max_users, "redeemed_count": count,
                "remaining_users": None if max_users is None else max(0, max_users-count)}


def get_redeem_history(user_id=None):
    with get_db() as db:
        query = """SELECT h.*,c.code,c.reward_coins,u.username,u.first_name,u.last_name
                   FROM redeem_history h JOIN redeem_codes c ON c.id=h.code_id
                   JOIN users u ON u.user_id=h.user_id"""
        params = ()
        if user_id is not None:
            query += " WHERE h.user_id=?"
            params = (int(user_id),)
        query += " ORDER BY h.id DESC"
        return [dict(r) for r in db.execute(query, params).fetchall()]


def set_setting(key, value):
    with get_db() as db:
        db.execute("""INSERT INTO bot_settings(setting_key,setting_value) VALUES(?,?)
                    ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value""", (str(key), str(value)))


def get_setting(key, default=None):
    with get_db() as db:
        row = db.execute("SELECT setting_value FROM bot_settings WHERE setting_key=?", (str(key),)).fetchone()
        return row["setting_value"] if row else default


def record_chat_check(user_id, chat_id, is_member):
    with get_db() as db:
        db.execute("""INSERT INTO required_chat_checks(user_id,chat_id,is_member,checked_at) VALUES(?,?,?,?)
                    ON CONFLICT(user_id,chat_id) DO UPDATE SET is_member=excluded.is_member,checked_at=excluded.checked_at""",
                   (int(user_id), str(chat_id), 1 if is_member else 0, current_time()))


def get_chat_checks(user_id):
    with get_db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM required_chat_checks WHERE user_id=? ORDER BY chat_id", (int(user_id),)).fetchall()]


def record_backup(backup_path, backup_type="automatic", created_by=None, status="success", notes=""):
    with get_db() as db:
        cursor = db.execute("""INSERT INTO backup_history(backup_path,backup_type,created_at,created_by,status,notes)
                    VALUES(?,?,?,?,?,?)""", (str(backup_path), str(backup_type), current_time(), created_by, str(status), str(notes)))
        return cursor.lastrowid


def get_backup_history(limit=20):
    limit = max(1, min(int(limit), 1000))
    with get_db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM backup_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def get_dashboard_stats():
    with get_db() as db:
        users = db.execute("""SELECT COUNT(*) AS total_users,SUM(CASE WHEN verified=1 THEN 1 ELSE 0 END) AS verified_users,
                    COALESCE(SUM(total_coins),0) AS total_coins FROM users""").fetchone()
        refs = db.execute("""SELECT COUNT(CASE WHEN status='verified' THEN 1 END) AS verified_referrals,
                    COUNT(CASE WHEN status='pending' THEN 1 END) AS pending_referrals FROM referrals""").fetchone()
        codes = db.execute("SELECT COUNT(*) AS total_codes,SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active_codes FROM redeem_codes").fetchone()
        redemptions = db.execute("SELECT COUNT(*) AS total_redemptions FROM redeem_history").fetchone()
        return {"total_users": users["total_users"] or 0, "verified_users": users["verified_users"] or 0,
                "total_coins": users["total_coins"] or 0, "verified_referrals": refs["verified_referrals"] or 0,
                "pending_referrals": refs["pending_referrals"] or 0, "total_codes": codes["total_codes"] or 0,
                "active_codes": codes["active_codes"] or 0, "total_redemptions": redemptions["total_redemptions"] or 0}


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
