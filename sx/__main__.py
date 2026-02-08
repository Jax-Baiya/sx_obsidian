import argparse
import sys

from sx.cli import interactive_menu
from sx.config import ProfileManager
from sx.render import DatabaseLayer, IngredientRegistry, ValidationEngine, setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SX Obsidian DB Generator")
    parser.add_argument("--profile", help="Active profile name")
    parser.add_argument("--vault", help="Vault path override")
    parser.add_argument("--csv", help="Consolidated CSV override", action="append")
    parser.add_argument("--add-csv", help="Add extra CSV sources", action="append")
    parser.add_argument("--set", help="Override config KEY=VALUE", action="append")
    parser.add_argument("--authors", help="Authors CSV override")
    parser.add_argument("--bookmarks", help="Bookmarks CSV override")
    parser.add_argument("--data-dir", help="Data dir name")
    parser.add_argument("--db-dir", help="DB dir name")
    parser.add_argument("--log-dir", help="Log dir name")
    parser.add_argument("--schema", help="Schema file path")
    parser.add_argument("--mode", choices=["create", "update", "sync"], default=None)
    parser.add_argument("--cleanup", choices=["soft", "hard"], help="Reset generated files")
    parser.add_argument("--force", action="store_true", help="Force hard cleanup")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--add-profile", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--interactive", action="store_true")

    # Performance / scalability controls
    parser.add_argument(
        "--only-bookmarked",
        action="store_true",
        help="Only sync items that appear in the bookmarks CSV (reduces note count)",
    )
    parser.add_argument(
        "--only-ids-file",
        help="Path to a text file containing one asset id per line to sync",
    )
    parser.add_argument(
        "--archive-stale",
        action="store_true",
        help=(
            "Move DB notes not included in the current sync selection to ARCHIVE_DIR "
            "(skips dirty notes unless --force)"
        ),
    )
    parser.add_argument(
        "--archive-dir",
        help="Archive directory (defaults to ARCHIVE_DIR env or '_archive/sx_obsidian_db')",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    manager = ProfileManager()

    if args.add_profile:
        name = input("Profile Name: ").strip().lower()
        vault = input("Vault Path: ").strip()
        csv1 = input("Main CSV Path: ").strip()
        manager.add_profile(name, vault, csv1)
        return 0

    if args.interactive:
        interactive_menu(manager, args)

    config = manager.resolve_config(args)
    if not config.get("vault"):
        print("Error: Vault path must be defined in .env or via --vault")
        return 1

    logger, _log_file = setup_logging(config["log_dir"], config["vault"])
    logger.info(
        f"Starting Profile: {config['profile']} (Style: {config['path_style']}, Dry Run: {args.dry_run})"
    )

    db = DatabaseLayer(config, logger)
    if args.cleanup:
        db.cleanup(args.cleanup, args.force, args.dry_run)

    registry = IngredientRegistry(logger)
    registry.load_all(config)

    if args.validate:
        engine = ValidationEngine(logger)
        engine.validate(config, registry)

    if args.mode:
        db.sync(registry, args)
        logger.info(f"Run Summary: {db.stats}")
    else:
        logger.info(f"Summary: {db.stats}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
