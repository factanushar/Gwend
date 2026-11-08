from database import get_leaderboard, get_user_rank, get_leaderboard_stats
from config import LEADERBOARD_LIMIT, LEADERBOARD_PAGE_SIZE, QUALIFICATION_REFERRALS


def get_leaderboard_page(page=0):
    """Return one paginated page, keeping database work limited to that page."""
    page = max(0, int(page))
    page_size = max(1, int(LEADERBOARD_PAGE_SIZE))
    total_limit = max(1, int(LEADERBOARD_LIMIT))
    total_pages = max(1, (total_limit + page_size - 1) // page_size)
    page = min(page, total_pages - 1)
    offset = page * page_size
    limit = min(page_size, total_limit - offset)

    users = get_leaderboard(limit=limit, offset=offset)
    entries = []
    for rank, user in enumerate(users, start=offset + 1):
        first_name = (user.get("first_name") or "Unknown User").strip()
        last_name = (user.get("last_name") or "").strip()
        username = user.get("username")
        verified_referrals = int(user.get("verified_referrals", 0) or 0)
        qualified = bool(user.get("qualified", verified_referrals >= QUALIFICATION_REFERRALS))
        entries.append({
            "rank": rank,
            "user_id": int(user["user_id"]),
            "name": f"{first_name} {last_name}".strip(),
            "username": f"@{username.lstrip('@')}" if username else "Not Set",
            "coins": int(user.get("total_coins", 0) or 0),
            "verified_referrals": verified_referrals,
            "pending_referrals": int(user.get("pending_referrals", 0) or 0),
            "qualified": qualified,
            "qualification_status": "✅ Qualified" if qualified else "⏳ Not Qualified",
        })

    stats = get_leaderboard_stats()
    return {
        "page": page, "page_size": page_size, "total_pages": total_pages,
        "entries": entries, "total_limit": total_limit, "stats": stats,
    }


def escape_html(text):
    text = str(text)
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def format_leaderboard(page=0):
    data = get_leaderboard_page(page)
    entries = data["entries"]
    stats = data["stats"]
    lines = [
        "🏆 <b>SF ARMY GIVEAWAY LEADERBOARD</b>",
        "",
        f"👥 <b>Total Users:</b> {stats['total_users']:,}",
        f"🪙 <b>Total Coins:</b> {stats['total_coins']:,}",
        f"✅ <b>Qualified:</b> {stats['qualified_users']:,}",
        f"⏳ <b>Non-Qualified:</b> {stats['unqualified_users']:,}",
        "",
        f"📊 <b>Top {data['total_limit']} Users</b>",
        f"📄 <b>Page:</b> {data['page'] + 1}/{data['total_pages']}",
        "",
    ]
    if not entries:
        lines.append("No verified users are on the leaderboard yet.")
        return "\n".join(lines)

    # Add clear section markers when a page crosses from qualified to unqualified.
    previous_status = None
    for user in entries:
        status = user["qualified"]
        if status != previous_status:
            lines.append("")
            lines.append("✅ <b>QUALIFIED USERS</b>" if status else "⏳ <b>NON-QUALIFIED USERS</b>")
            previous_status = status
        rank = user["rank"]
        icon = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"<b>#{rank}</b>"
        lines.append(
            f"{icon} <b>{escape_html(user['name'])}</b>\n"
            f"   👤 {escape_html(user['username'])}\n"
            f"   🆔 <code>{user['user_id']}</code>\n"
            f"   🪙 <b>{user['coins']:,} Total Coins</b>\n"
            f"   👥 Verified Referrals: {user['verified_referrals']}\n"
            f"   🎯 {user['qualification_status']}"
        )
        lines.append("")

    lines.extend([
        f"📌 Qualification requires {QUALIFICATION_REFERRALS} eligible verified referrals.",
        "🏆 Qualified users always appear before non-qualified users.",
        "🪙 Ranking within each group is based on total earned coins.",
    ])
    return "\n".join(lines)


def get_user_leaderboard_details(user_id):
    user_id = int(user_id)
    rank = get_user_rank(user_id)
    page_users = get_leaderboard(limit=1000, offset=0)
    for user in page_users:
        if int(user["user_id"]) == user_id:
            verified_referrals = int(user.get("verified_referrals", 0) or 0)
            return {
                "rank": rank,
                "coins": int(user.get("total_coins", 0) or 0),
                "verified_referrals": verified_referrals,
                "qualified": bool(user.get("qualified", verified_referrals >= QUALIFICATION_REFERRALS)),
            }
    return {"rank": rank, "coins": 0, "verified_referrals": 0, "qualified": False}
