import os
from datetime import datetime
from zoneinfo import ZoneInfo

# BOT CONFIGURATION
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [8872609272, 7331380618]

# REQUIRED CHANNELS
CHANNELS = [
    {"name": "🦅 SF ARMY 💓🤍", "chat_id": -1002334256951, "url": "https://t.me/+qboCxP7VbFQ5YzM1"},
    {"name": "Secret World 🙈", "chat_id": -1004346974389, "url": "https://t.me/+LSDB_ZOckwswMDUx"},
    {"name": "🤍💓ANUSHAR 🌷", "chat_id": -1003746793908, "url": "https://t.me/+kkjsBE3OfypmNTc1"},
    {"name": "ANUSHAR ARMY 🪖", "chat_id": -1003689156772, "url": "https://t.me/+6qmbICUUy0dmMTY1"},
    {"name": "EXPOSE MAFIA 😎", "chat_id": -1003040006163, "url": "https://t.me/+aOrE_A-_KadkZjhl"},
    {"name": "SF TOOL GC 🧑🏻‍🔧", "chat_id": -1002708620916, "url": "https://t.me/+PwAfcam-4ycxZGU1"},
]

# COIN SETTINGS
WELCOME_BONUS = 5
REFERRAL_REWARD = 10
DAILY_BONUS = 5

# GIVEAWAY SETTINGS
TIMEZONE = ZoneInfo("Asia/Kolkata")
QUALIFICATION_REFERRALS = 6
LEADERBOARD_LIMIT = 50
LEADERBOARD_PAGE_SIZE = 25
GIVEAWAY_END_AT = datetime(2026, 11, 8, 12, 0, 0, tzinfo=TIMEZONE)
REWARD_SYSTEM_ENABLED = True

# GIVEAWAY SUPPORT
SUPPORT_USERNAME = "@AnusharCommunity"
GIVEAWAY_GREETING = "Happy Diwali! 🪔✨"

# GIVEAWAY REWARDS
GIVEAWAY_REWARDS = {
    1: {"type": "fixed", "name": "Telegram NFT Star Notepad", "url": "https://t.me/nft/StarNotepad-42379"},
    2: {"type": "fixed", "name": "Telegram NFT Chill Flame", "url": "https://t.me/nft/ChillFlame-107767"},
    3: {"type": "fixed", "name": "Telegram NFT Ice Cream", "url": "https://t.me/nft/IceCream-327731"},
}
TEDDY_AND_ACCOUNT_RANKS = range(4, 11)
TEDDY_ONLY_RANKS = range(11, 34)
ACCOUNT_CHOICE_RANKS = range(34, 51)

# DATABASE AND BACKUP SETTINGS
DATA_DIR = "data"
BACKUP_DIR = "backups"
DATABASE_FILE = os.path.join(DATA_DIR, "giveaway.db")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
BACKUP_HOUR = 0
BACKUP_MINUTE = 0

# REWARD MENU
REWARD_COMING_SOON_TEXT = "🎁 Giveaway rewards and eligibility details are available below."

# Official channel used for final giveaway results and post-end user notice.
GIVEAWAY_CHANNEL_ID = "@SFgiveaways"
GIVEAWAY_CHANNEL_URL = "https://t.me/SFgiveaways"
