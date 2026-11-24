"""Entry point: `python3 -m ai_cleaner`."""
import argparse
import sys

from . import config
from .ui.wizard import main


def _parse_args(argv=None):
    p = argparse.ArgumentParser(prog="ai_cleaner")
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually move files to Trash. Without this flag, runs in dry-run mode.",
    )
    p.add_argument("--admin", action="store_true", help="Run in admin/root mode.")
    p.add_argument("--folder", default=None, help="Folder to scan.")
    p.add_argument("--deep", action="store_true", help="Deep scan.")
    p.add_argument("--signal-file", default=None, help=argparse.SUPPRESS)
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    if args.apply:
        config.DRY_RUN = False
    main(admin_mode=args.admin, start_folder=args.folder, start_deep=args.deep)