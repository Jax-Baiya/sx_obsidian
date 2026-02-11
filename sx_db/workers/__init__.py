"""Maintenance workers for sx_db.

This package is intentionally lightweight and side-effect free.

Design goals:
- Tasks can be run from cron/systemd timers.
- No dependency on the Obsidian vault (the plugin owns vault writes).
- Safe defaults (dry-run friendly; bounded deletes).
"""
