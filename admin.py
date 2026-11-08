"""Admin helpers for the SF ARMY giveaway bot.

All messages returned by format_* functions use Telegram HTML parse mode.
This module does not modify the database schema or reset user data.
"""

from html import escape

from config import ADMIN_IDS
from database import (
    get_user,
    get_dashboard_stats,
    add_coins,
    deduct_coins,
    get_coin_transactions,
    get_all_users,
    get_redeem_codes,
    get_redeem_history,
    get_backup_history,
)


def is_admin(user_id):
    """Return True only when user_id is in configured ADMIN_IDS."""
    try:
        return int(user_id) in {int(admin_id) for admin_id in ADMIN_IDS}
    except (TypeError, ValueError):
        return False


def get_admin_dashboard():
    try:
        return {"success": True, "stats": get_dashboard_stats() or {}}
    except Exception:
        return {
            "success": False,
            "error": "Could not retrieve dashboard statistics.",
            "stats": {},
        }


def format_admin_dashboard():
    result = get_admin_dashboard()
    if not result["success"]:
        return "⚠️ <b>Dashboard Unavailable</b>\n\nPlease try again later."

    stats = result["stats"]
    keys = (
        ("total_users", "👥 Total Users"),
        ("verified_users", "✅ Verified Users"),
        ("total_coins", "🪙 Coins in Circulation"),
        ("verified_referrals", "👤 Verified Referrals"),
        ("pending_referrals", "⏳ Pending Referrals"),
        ("total_codes", "🎟️ Total Redeem Codes"),
        ("active_codes", "🟢 Active Redeem Codes"),
        ("total_redemptions", "🎁 Total Redemptions"),
    )
    lines = ["📊 <b>SF ARMY ADMIN DASHBOARD</b>", ""]
    for key, label in keys:
        try:
            value = int(stats.get(key, 0) or 0)
        except (TypeError, ValueError):
            value = 0
        lines.append(f"{label}: <b>{value:,}</b>")
        if key in ("total_coins", "pending_referrals", "active_codes"):
            lines.append("")
    return "\n".join(lines).strip()


def get_user_details(user_id):
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return {"success": False, "message": "❌ Please enter a valid numeric Telegram user ID.", "user": None}
    try:
        user = get_user(uid)
        if not user:
            return {"success": False, "message": "❌ User not found in the database.", "user": None}
        return {"success": True, "message": "✅ User found.", "user": user}
    except Exception:
        return {"success": False, "message": "⚠️ Could not retrieve user details.", "user": None}


def format_user_details(user):
    if not user:
        return "❌ User not found."

    first_name = escape(str(user.get("first_name") or "Not set"))
    last_name = escape(str(user.get("last_name") or ""))
    username = str(user.get("username") or "").strip().lstrip("@")
    username_text = f"@{escape(username)}" if username else "Not set"
    user_id = escape(str(user.get("user_id", "Unknown")))
    try:
        total_coins = int(user.get("total_coins") or 0)
    except (TypeError, ValueError):
        total_coins = 0
    verified = bool(user.get("verified", 0))
    joined_at = escape(str(user.get("joined_at") or "Unknown"))
    referred_by = user.get("referred_by")
    referred_text = f"<code>{escape(str(referred_by))}</code>" if referred_by else "Direct / None"
    full_name = f"{first_name} {last_name}".strip()

    return (
        "👤 <b>USER DETAILS</b>\n\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"📛 Name: {full_name}\n"
        f"🔗 Username: {username_text}\n"
        f"💰 Balance: <b>{total_coins:,} coins</b>\n"
        f"🔐 Membership: {'✅ Verified' if verified else '❌ Not verified'}\n"
        f"👥 Referred By: {referred_text}\n"
        f"📅 Joined: {joined_at}"
    )


def _adjust_coins(user_id, amount, admin_id, reason, add):
    if not is_admin(admin_id):
        return {"success": False, "message": "⛔ You are not authorized to perform this action."}

    try:
        uid, coins, aid = int(user_id), int(amount), int(admin_id)
    except (TypeError, ValueError):
        return {"success": False, "message": "❌ User ID and coin amount must be numbers."}

    if coins <= 0:
        return {"success": False, "message": "❌ Coin amount must be greater than zero."}

    try:
        if not get_user(uid):
            return {"success": False, "message": "❌ User not found."}

        # These keyword arguments match the database.py functions.
        if add:
            success = add_coins(
                user_id=uid,
                amount=coins,
                description=f"{reason} (Admin ID: {aid})",
                admin_id=aid,
                transaction_type="admin_add",
            )
        else:
            success = deduct_coins(
                user_id=uid,
                amount=coins,
                description=f"{reason} (Admin ID: {aid})",
                admin_id=aid,
                transaction_type="admin_deduct",
            )

        if not success:
            if add:
                message = "❌ Coins could not be added."
            else:
                user = get_user(uid) or {}
                balance = int(user.get("total_coins") or 0)
                return {
                    "success": False,
                    "balance": balance,
                    "message": "❌ Coins could not be deducted. The user may not have enough coins.",
                }
            return {"success": False, "message": message}

        updated_user = get_user(uid) or {}
        balance = int(updated_user.get("total_coins") or 0)
        action = "Added" if add else "Deducted"
        symbol = "+" if add else "−"
        return {
            "success": True,
            "balance": balance,
            "message": (
                f"✅ <b>Coins {action} Successfully!</b>\n\n"
                f"👤 User ID: <code>{uid}</code>\n"
                f"{symbol} {action}: <b>{coins:,} Coins</b>\n"
                f"💰 New Balance: <b>{balance:,} Coins</b>"
            ),
        }
    except Exception:
        return {"success": False, "message": "⚠️ An error occurred while updating the user's coins."}


def add_user_coins(user_id, amount, admin_id, reason="Admin adjustment"):
    return _adjust_coins(user_id, amount, admin_id, reason, add=True)


def deduct_user_coins(user_id, amount, admin_id, reason="Admin adjustment"):
    return _adjust_coins(user_id, amount, admin_id, reason, add=False)


def get_user_transactions(user_id, limit=20):
    try:
        uid = int(user_id)
        limit = max(1, min(int(limit), 100))
        if not get_user(uid):
            return []
        return get_coin_transactions(user_id=uid, limit=limit) or []
    except (TypeError, ValueError, Exception):
        return []


def format_user_transactions(user_id, limit=20):
    user_result = get_user_details(user_id)
    if not user_result["success"]:
        return user_result["message"]

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return "❌ Please enter a valid numeric Telegram user ID."

    transactions = get_user_transactions(uid, limit)
    if not transactions:
        return f"📜 <b>TRANSACTION HISTORY</b>\n\n👤 User ID: <code>{uid}</code>\n\nNo transactions found."

    lines = ["📜 <b>TRANSACTION HISTORY</b>", "", f"👤 User ID: <code>{uid}</code>", ""]
    for tx in transactions:
        try:
            amount = int(tx.get("amount") or 0)
            amount_text = f"+{amount:,}" if amount > 0 else f"{amount:,}"
        except (TypeError, ValueError):
            amount_text = escape(str(tx.get("amount", "Unknown")))
        tx_type = escape(str(tx.get("transaction_type") or "unknown"))
        description = escape(str(tx.get("description") or "Coin transaction"))
        created_at = escape(str(tx.get("created_at") or "Unknown"))
        lines.extend([
            f"🪙 Amount: <b>{amount_text}</b>",
            f"📌 Type: <code>{tx_type}</code>",
            f"📝 Details: {description}",
            f"🕒 Date: {created_at}",
            "──────────────",
        ])
    return "\n".join(lines)


def get_user_list():
    try:
        return get_all_users() or []
    except Exception:
        return []


def get_user_list_page(page=0, page_size=10):
    try:
        page = max(0, int(page))
        page_size = max(1, min(int(page_size), 50))
        users = get_user_list()
        total = len(users)
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages - 1)
        start = page * page_size
        return {"users": users[start:start + page_size], "page": page,
                "page_size": page_size, "total_users": total, "total_pages": pages}
    except (TypeError, ValueError):
        return {"users": [], "page": 0, "page_size": 10, "total_users": 0, "total_pages": 1}


def get_admin_redeem_codes(status=None):
    try:
        return get_redeem_codes(status=status) or []
    except Exception:
        return []


def format_admin_redeem_codes(status="active"):
    codes = get_admin_redeem_codes(status=status)
    if not codes:
        return "🎟️ <b>REDEEM CODES</b>\n\nNo codes found."

    lines = ["🎟️ <b>REDEEM CODES</b>", ""]
    for item in codes[:50]:
        code = escape(str(item.get("code") or "Unknown"))
        reward = item.get("reward_coins", 0)
        code_status = escape(str(item.get("status") or "Unknown"))
        max_users = item.get("max_users")
        redeemed = item.get("redeemed_count", 0) or 0
        remaining = item.get("remaining_users")
        limit_text = "Unlimited" if max_users is None else str(max_users)
        remaining_text = "Unlimited" if remaining is None else str(remaining)
        lines.append(
            f"🔑 Code: <code>{code}</code>\n"
            f"🪙 Reward: <b>{escape(str(reward))}</b> coins\n"
            f"👥 Redeemed: <b>{escape(str(redeemed))}/{escape(limit_text)}</b>\n"
            f"📦 Slots left: <b>{escape(remaining_text)}</b>\n"
            f"📌 Status: <b>{code_status}</b>"
        )
    if len(codes) > 50:
        lines.append(f"\nShowing 50 of {len(codes)} codes.")
    return "\n\n".join(lines)


def get_admin_redeem_history(limit=20):
    try:
        limit = max(1, min(int(limit), 100))
        return (get_redeem_history() or [])[:limit]
    except Exception:
        return []


def get_admin_backup_history(limit=20):
    try:
        limit = max(1, min(int(limit), 100))
        return get_backup_history(limit=limit) or []
    except Exception:
        return []
