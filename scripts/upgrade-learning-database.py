#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.learning_production import (
    ProductionLearningDatabaseError,
    inspect_learning_database,
    restore_learning_backup,
    upgrade_learning_database,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely initialize or upgrade the independent Nautilus learning database."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "data" / "learning.sqlite3",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "backups" / "learning",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only inspect an existing learning database; never migrate or restore.",
    )
    parser.add_argument(
        "--restore",
        type=Path,
        help="Restore a learning database backup to --database.",
    )
    parser.add_argument(
        "--allow-missing-current",
        action="store_true",
        help=(
            "Allow restore when the current database is missing. This accepts that purge "
            "verification against current tombstones is unavailable."
        ),
    )
    parser.add_argument(
        "--authorize-production",
        action="store_true",
        help="Required for any production migration or restore operation.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.verify_only:
            if not args.authorize_production:
                raise ProductionLearningDatabaseError("verification requires explicit production authorization")
            result = inspect_learning_database(args.database)
        elif args.restore is not None:
            if not args.authorize_production:
                raise ProductionLearningDatabaseError("restore requires explicit production authorization")
            result = restore_learning_backup(
                args.restore,
                args.database,
                allow_missing_current=args.allow_missing_current,
            )
        else:
            result = upgrade_learning_database(
                args.database,
                args.backup_dir,
                authorized=args.authorize_production,
            )
    except ProductionLearningDatabaseError as error:
        print(f"error: {error}", flush=True)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
