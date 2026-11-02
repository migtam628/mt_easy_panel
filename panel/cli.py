"""Offline administrator bootstrap. Run on the control-plane host."""
import argparse
import getpass
import os
import sys
from panel.auth import AuthStore


def main():
    parser = argparse.ArgumentParser(description="MT Panel administrative CLI")
    parser.add_argument("command", choices=["create-admin"])
    parser.add_argument("--username", default="admin")
    parser.add_argument("--db", default=os.environ.get("PANEL_DB_PATH", "./state/panel.db"))
    args = parser.parse_args()
    store = AuthStore(args.db)
    if store.is_setup():
        sys.exit("An administrator already exists; this bootstrap command will not modify credentials.")
    password = getpass.getpass("Choose a unique admin password (minimum 14 characters): ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        sys.exit("Passwords do not match")
    try:
        store.create_admin(args.username, password)
    except (ValueError, Exception) as exc:
        # Do not echo secret values.
        sys.exit(f"Could not create admin: {type(exc).__name__}: {exc}")
    print(f"Created administrator '{args.username}' in {args.db}")


if __name__ == "__main__":
    main()
