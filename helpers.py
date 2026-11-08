from datetime import datetime
from zoneinfo import ZoneInfo

from config import (
    TIMEZONE,
    QUALIFICATION_REFERRALS,
    GIVEAWAY_END_AT,
)


def get_current_time():
    return datetime.now(TIMEZONE)


def get_current_date():
    return get_current_time().strftime("%Y-%m-%d")


def get_formatted_time():
    return get_current_time().strftime("%d %b %Y, %I:%M %p IST")


def get_display_name(user):
    first_name = (user.get("first_name") or "").strip()
    last_name = (user.get("last_name") or "").strip()
    full_name = f"{first_name} {last_name}".strip()

    return full_name or "Unknown User"


def get_username(username):
    if not username:
        return "Not Set"

    username = username.strip().lstrip("@")
    return f"@{username}" if username else "Not Set"


def get_qualification_status(verified_referrals):
    verified_referrals = int(verified_referrals or 0)

    if verified_referrals >= QUALIFICATION_REFERRALS:
        return True

    return False


def get_qualification_text(verified_referrals):
    verified_referrals = int(verified_referrals or 0)

    if verified_referrals >= QUALIFICATION_REFERRALS:
        return "✅ Qualified"

    remaining = QUALIFICATION_REFERRALS - verified_referrals

    return f"⏳ Not Qualified ({remaining} more verified referrals needed)"


def get_referral_link(bot_username, user_id):
    bot_username = str(bot_username).strip().lstrip("@")
    user_id = int(user_id)

    return f"https://t.me/{bot_username}?start=ref_{user_id}"


def parse_referral_parameter(parameter):
    if not parameter:
        return None

    parameter = str(parameter).strip()

    if not parameter.startswith("ref_"):
        return None

    try:
        inviter_id = int(parameter[4:])

        if inviter_id <= 0:
            return None

        return inviter_id

    except (TypeError, ValueError):
        return None


def get_coins_text(coins):
    coins = int(coins or 0)

    return f"🪙 {coins:,} Coins"


def get_rank_text(rank):
    if rank is None:
        return "Not Ranked"

    rank = int(rank)

    if rank <= 0:
        return "Not Ranked"

    return f"#{rank:,}"


def get_progress_text(current, target):
    current = max(0, int(current or 0))
    target = max(1, int(target or 1))

    completed = min(current, target)
    remaining = max(0, target - completed)

    percentage = int((completed / target) * 100)

    return {
        "current": completed,
        "target": target,
        "remaining": remaining,
        "percentage": percentage,
        "text": f"{completed}/{target} ({percentage}%)",
    }


def get_giveaway_end_datetime():
    if not GIVEAWAY_END_AT:
        return None

    if isinstance(GIVEAWAY_END_AT, datetime):
        if GIVEAWAY_END_AT.tzinfo is None:
            return GIVEAWAY_END_AT.replace(tzinfo=TIMEZONE)

        return GIVEAWAY_END_AT.astimezone(TIMEZONE)

    try:
        parsed = datetime.fromisoformat(str(GIVEAWAY_END_AT))

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TIMEZONE)

        return parsed.astimezone(TIMEZONE)

    except (TypeError, ValueError):
        return None


def is_giveaway_ended():
    end_time = get_giveaway_end_datetime()

    if end_time is None:
        return False

    return get_current_time() >= end_time


def format_user_details(user):
    name = get_display_name(user)
    username = get_username(user.get("username"))
    user_id = user.get("user_id", "Unknown")
    coins = get_coins_text(user.get("total_coins", 0))

    return (
        f"👤 **Name:** {name}\n"
        f"🔗 **Username:** {username}\n"
        f"🆔 **User ID:** `{user_id}`\n"
        f"💰 **Balance:** {coins}"
    )


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
