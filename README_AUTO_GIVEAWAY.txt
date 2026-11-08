SF ARMY AUTO GIVEAWAY - CORE FILE BUNDLE

Included: main.py, database.py, scheduler.py, config.py, backup.py, requirements.txt.

These are the core files for the auto-finalization flow. main.py also imports the
existing project modules (admin.py, member.py, referrals.py, profile.py,
leaderboard.py, rewards.py, redeem.py, keyboards.py). Keep those existing files
in the same project folder; they are intentionally not replaced by this bundle.

Before replacing files on your host:
1. Stop the bot.
2. Make a copy of the existing data/giveaway.db and backups/ folder.
3. Replace the six files from this bundle.
4. Install requirements.txt if needed, then start the bot.

Do not delete data/giveaway.db. The giveaway deadline configured here is
8 November 2026 at 12:00 PM Asia/Kolkata. Daily backup is configured for 00:00.

BOT_TOKEN is read from the BOT_TOKEN environment variable. Do not share it.
