"""Create the app database and the demo accounts: head office plus three store managers.

Passwords come from the environment (or FULL_CODE/.env), never from this file:
    VOS_ADMIN_PASSWORD   head office
    VOS_STORE_PASSWORD   the three store managers

python FULL_CODE/db/seed.py
Running it again resets the demo accounts' passwords and keeps every case and message.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voice_of_store.accounts import AccountError, save_user  # noqa: E402
from voice_of_store.cli import configure_logging  # noqa: E402
from voice_of_store.config import load_env_file, load_settings  # noqa: E402
from voice_of_store.database import apply_schema, session  # noqa: E402

logger = logging.getLogger("seed")

# Three stores, one per region, each with an early warning in the data, so each login has a story to show.
STORE_ACCOUNTS = [
    ("rs-puram", "RS Puram store manager", "ST-KXEU6"),
    ("dharampeth", "Dharampeth store manager", "ST-01XF3"),
    ("kankarbagh", "Kankarbagh store manager", "ST-D69EG"),
]


def main() -> int:
    configure_logging()
    load_env_file()
    settings = load_settings()
    admin_password = os.environ.get("VOS_ADMIN_PASSWORD", "")
    store_password = os.environ.get("VOS_STORE_PASSWORD", "")
    if not admin_password or not store_password:
        logger.error("Set VOS_ADMIN_PASSWORD and VOS_STORE_PASSWORD (copy FULL_CODE/.env.example to FULL_CODE/.env).")
        return 2
    apply_schema(settings.database.path)
    try:
        with session(settings.database.path) as connection:
            save_user(connection, "head-office", "Head office", admin_password, "admin")
            for username, name, store_id in STORE_ACCOUNTS:
                save_user(connection, username, name, store_password, "store", store_id)
    except AccountError as error:
        logger.error("%s", error)
        return 2
    logger.info(
        "Accounts ready in %s: head-office, %s", settings.database.path, ", ".join(a[0] for a in STORE_ACCOUNTS)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
