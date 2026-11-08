"""SF ARMY 10K Giveaway Rewards System."""

from html import escape

from database import (
    get_giveaway_result,
    get_giveaway_state,
    save_giveaway_reward_choice,
    confirm_giveaway_reward_choice,
)


NFT_REWARDS = {
    1: ("Star Notepad NFT", "https://t.me/nft/StarNotepad-42379"),
    2: ("Chill Flame NFT", "https://t.me/nft/ChillFlame-107767"),
    3: ("Ice Cream NFT", "https://t.me/nft/IceCream-327731"),
}

GIVEAWAY_END_TEXT = "8 November 2026"
GIVEAWAY_END_TIME = "12:00 PM IST (Noon)"


def _finalized():
    try:
        value = get_giveaway_state("finalized", "0")
        return str(value).strip().lower() in {
            "1", "true", "yes", "finalized"
        }
    except Exception:
        return False


def _value(result, key, default=None):
    if not result:
        return default

    try:
        value = result.get(key, default)
    except AttributeError:
        try:
            value = result[key]
        except (KeyError, IndexError, TypeError):
            return default

    return default if value is None else value


def _rank_reward(rank):
    rank = int(rank or 0)

    if rank in NFT_REWARDS:
        name, link = NFT_REWARDS[rank]
        return f'<a href="{link}">{escape(name)}</a>'

    if 4 <= rank <= 10:
        return "Teddy + Telegram/WhatsApp Account Choice"

    if 11 <= rank <= 33:
        return "Teddy Reward"

    if 34 <= rank <= 50:
        return "Telegram/WhatsApp Account Choice"

    return "No Rank Reward Assigned"


def _account_choice_required(rank):
    rank = int(rank or 0)
    return 4 <= rank <= 10 or 34 <= rank <= 50


def get_reward_info_message():
    """Return complete premium giveaway reward information."""

    return (
        "ℹ️ <b>SF ARMY 10K — REWARD INFORMATION</b>\n\n"
        "🦅 <b>THE ULTIMATE REWARD LINEUP</b> 💓🤍\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🥇 <b>RANK #1 — STAR NOTEPAD NFT</b>\n"
        '<a href="https://t.me/nft/StarNotepad-42379">'
        "🔗 Open NFT</a>\n\n"

        "🥈 <b>RANK #2 — CHILL FLAME NFT</b>\n"
        '<a href="https://t.me/nft/ChillFlame-107767">'
        "🔗 Open NFT</a>\n\n"

        "🥉 <b>RANK #3 — ICE CREAM NFT</b>\n"
        '<a href="https://t.me/nft/IceCream-327731">'
        "🔗 Open NFT</a>\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🎁 <b>RANKS #4–#10</b>\n"
        "🧸 Teddy + Telegram / WhatsApp Account Choice\n\n"

        "🧸 <b>RANKS #11–#33</b>\n"
        "🎁 Teddy Reward\n\n"

        "📱 <b>RANKS #34–#50</b>\n"
        "🎁 Telegram / WhatsApp Account Choice\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "⏳ <b>GIVEAWAY ENDS</b>\n\n"
        f"📅 <b>{GIVEAWAY_END_TEXT}</b>\n"
        f"🕛 <b>{GIVEAWAY_END_TIME}</b>\n\n"

        "⚠️ <i>Complete your referrals and eligibility "
        "requirements before the giveaway ends.</i>\n\n"

        "🔒 <b>ACCOUNT SELECTION POLICY</b>\n"
        "Account selection unlocks only after the final results "
        "are announced. Once confirmed, your choice cannot be changed.\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🦅 <b>SF ARMY 10K SPECIAL</b> 💓🤍\n"
        "✨ <i>Your Rank. Your Reward. Your Moment.</i>"
    )


def get_rewards_message(user_id):
    """Return the reward list and the user's personal result."""

    result = get_giveaway_result(int(user_id))
    finalized = _finalized()

    lines = [
        "🦅 <b>SF ARMY 10K SPECIAL</b> 💓🤍",
        "",
        "🏆 <b>THE ULTIMATE REWARD LINEUP</b>",
        "━━━━━━━━━━━━━━━━━━",
        "",
        '🥇 <b>#1:</b> '
        '<a href="https://t.me/nft/StarNotepad-42379">'
        "Star Notepad NFT</a>",
        '🥈 <b>#2:</b> '
        '<a href="https://t.me/nft/ChillFlame-107767">'
        "Chill Flame NFT</a>",
        '🥉 <b>#3:</b> '
        '<a href="https://t.me/nft/IceCream-327731">'
        "Ice Cream NFT</a>",
        "",
        "🎁 <b>#4–#10:</b> Teddy + Telegram/WhatsApp Account Choice",
        "🧸 <b>#11–#33:</b> Teddy Reward",
        "📱 <b>#34–#50:</b> Telegram/WhatsApp Account Choice",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "👤 <b>YOUR GIVEAWAY RESULT</b>",
        "",
    ]

    if not finalized:
        lines.extend([
            "⏳ Final results have not been announced yet.",
            "🔒 Reward selection unlocks after the final results.",
        ])

    elif not result:
        lines.extend([
            "❌ <b>No Reward Assigned</b>",
            "You are not listed in the final qualified Top 50 winners.",
            "Only qualified users ranked in the final Top 50 "
            "receive rewards.",
        ])

    else:
        rank = int(_value(result, "final_rank", 0) or 0)
        refs = int(_value(result, "verified_referrals", 0) or 0)
        coins = int(_value(result, "referral_coins", 0) or 0)

        choice = str(
            _value(result, "reward_choice", "") or ""
        ).strip().lower()

        confirmed_value = _value(
            result,
            "selection_confirmed",
            _value(result, "choice_confirmed", 0),
        )

        confirmed = str(confirmed_value).strip().lower() in {
            "1", "true", "yes"
        }

        lines.extend([
            "🎉 <b>Congratulations, Winner!</b>",
            f"🏅 Final Rank: <b>#{rank}</b>",
            f"👥 Verified Referrals: <b>{refs}</b>",
            f"🪙 Referral Coins: <b>{coins}</b>",
            f"🎁 Your Reward: {_rank_reward(rank)}",
        ])

        if _account_choice_required(rank):
            if confirmed:
                account = (
                    choice.title()
                    if choice in {"telegram", "whatsapp"}
                    else "Confirmed"
                )

                lines.extend([
                    "",
                    "🔒 <b>ACCOUNT CHOICE CONFIRMED</b>",
                    f"📱 Selection: <b>{escape(account)}</b>",
                    "Your choice is locked and cannot be changed.",
                ])

            elif choice in {"telegram", "whatsapp"}:
                lines.extend([
                    "",
                    f"📌 Selected Account: <b>{escape(choice.title())}</b>",
                    "Confirm your choice to lock it permanently.",
                ])

            else:
                lines.extend([
                    "",
                    "📌 <b>ACCOUNT SELECTION</b>",
                    "Choose Telegram or WhatsApp after the "
                    "final results are announced.",
                ])

        elif rank in NFT_REWARDS:
            lines.extend([
                "",
                "ℹ️ NFT prizes will be delivered manually "
                "by the administration.",
            ])

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━",
        "📅 <b>GIVEAWAY ENDS</b>",
        f"{GIVEAWAY_END_TEXT} — {GIVEAWAY_END_TIME}",
        "",
        "🦅 <b>SF ARMY 10K SPECIAL</b> 💓🤍",
    ])

    return "\n".join(lines)


def choose_reward(user_id, choice):
    """Save a winner's Telegram or WhatsApp selection."""

    choice = str(choice).strip().lower()

    if choice not in {"telegram", "whatsapp"}:
        return {
            "success": False,
            "reason": "invalid_choice",
            "message": "Please choose Telegram or WhatsApp.",
        }

    result = save_giveaway_reward_choice(int(user_id), choice)

    if result.get("success"):
        return {
            "success": True,
            "choice": result.get("choice", choice),
            "message": "Reward choice saved.",
        }

    reasons = {
        "not_a_winner":
            "Your user ID is not listed in the final giveaway results.",
        "choice_not_required":
            "Your rank does not have an account-choice reward.",
        "already_confirmed":
            "Your reward choice is already confirmed and locked.",
        "invalid_choice":
            "Please choose Telegram or WhatsApp.",
    }

    reason = result.get("reason", "")

    return {
        "success": False,
        "reason": reason,
        "message": reasons.get(
            reason,
            "Could not save your reward choice. Please try again.",
        ),
    }


def confirm_reward_choice(user_id):
    """Confirm and permanently lock the selected reward choice."""

    result = confirm_giveaway_reward_choice(int(user_id))

    if result.get("success"):
        return {
            "success": True,
            "choice": result.get("choice"),
            "rank": result.get("rank"),
            "message": "Reward choice confirmed and locked.",
        }

    reasons = {
        "not_a_winner":
            "Your user ID is not listed in the final giveaway results.",
        "confirmation_not_required":
            "Your rank does not have an account-choice reward.",
        "choice_not_selected":
            "Select Telegram or WhatsApp before confirming.",
        "confirmation_failed":
            "Confirmation could not be saved. Please try again.",
        "already_confirmed":
            "Your reward choice is already confirmed and locked.",
    }

    reason = result.get("reason", "")

    return {
        "success": False,
        "reason": reason,
        "message": reasons.get(
            reason,
            "Could not confirm your reward choice. Please try again.",
        ),
    }


def get_user_giveaway_summary(user_id):
    """Return a compact summary of the user's final result."""

    result = get_giveaway_result(int(user_id))

    if not result:
        return {
            "is_winner": False,
            "message": "No final rank is assigned to this user.",
        }

    rank = int(_value(result, "final_rank", 0) or 0)

    confirmed_value = _value(
        result,
        "selection_confirmed",
        _value(result, "choice_confirmed", 0),
    )

    confirmed = str(confirmed_value).strip().lower() in {
        "1", "true", "yes"
    }

    return {
        "is_winner": 1 <= rank <= 50,
        "rank": rank,
        "reward_type": _value(result, "reward_type", ""),
        "reward": _rank_reward(rank),
        "reward_choice": _value(result, "reward_choice"),
        "choice_confirmed": confirmed,
    }
