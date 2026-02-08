import os
import shutil
from datetime import datetime

from dotenv import load_dotenv


class ProfileManager:
    def __init__(self):
        load_dotenv()
        self.active_profile = None

    def list_profiles(self):
        """Discovers profiles from .env by looking for VAULT_ keys."""
        profiles = ["default"]

        # Ignore OS-specific vault roots; these are not profiles.
        ignore_prefixes = (
            "VAULT_WINDOWS_",
            "VAULT_LINUX_",
            "VAULT_MAC_",
            # Legacy / shorthand variants that users may have set.
            "VAULT_WIN_",
            "VAULT_OSX_",
        )

        for key in os.environ:
            if not key.startswith("VAULT_"):
                continue
            if key == "VAULT_default":
                continue
            if key.startswith(ignore_prefixes):
                continue

            profile = key[6:]
            if profile:
                profiles.append(profile)
        return sorted(list(set(profiles)))

    def resolve_config(self, args):
        """Merges CLI args with .env namespaced values and overrides."""
        self.active_profile = getattr(args, "profile", None) or os.getenv("SX_PROFILE", "default")

        # Profile-specific suffixes
        suffix = f"_{self.active_profile}" if self.active_profile != "default" else ""

        # Resolve Overrides
        overrides = {}
        if hasattr(args, "set") and args.set:
            for item in args.set:
                if "=" in item:
                    k, v = item.split("=", 1)
                    overrides[k.upper()] = v

        config = {
            "profile": self.active_profile,
            "vault": overrides.get("VAULT")
            or getattr(args, "vault", None)
            or os.getenv(f"VAULT{suffix}")
            or os.getenv("VAULT_default"),
            "path_style": overrides.get("PATH_STYLE")
            or os.getenv(f"PATH_STYLE{suffix}")
            or os.getenv("PATH_STYLE", "linux"),
            "data_dir": overrides.get("DATA_DIR")
            or getattr(args, "data_dir", None)
            or os.getenv("DATA_DIR", "data"),
            "db_dir": overrides.get("DB_DIR")
            or getattr(args, "db_dir", None)
            or os.getenv("DB_DIR", "_db/media"),
            "log_dir": overrides.get("LOG_DIR")
            or getattr(args, "log_dir", None)
            or os.getenv("LOG_DIR", "_logs"),
            "reports_dir": overrides.get("REPORTS_DIR") or os.getenv("REPORTS_DIR", "reports"),
            "archive_dir": overrides.get("ARCHIVE_DIR")
            or getattr(args, "archive_dir", None)
            or os.getenv("ARCHIVE_DIR", "_archive/sx_obsidian_db"),
            "schema": overrides.get("SCHEMA")
            or getattr(args, "schema", None)
            or os.getenv("SX_SCHEMA", "schema.yaml"),
        }

        # OS-specific vault roots
        for os_prefix in ["WINDOWS", "LINUX", "MAC"]:
            key = f"vault_{os_prefix.lower()}"
            env_key = f"VAULT_{os_prefix}{suffix}"
            config[key] = os.getenv(env_key) or os.getenv(f"VAULT_{os_prefix}_default")

        # CSV Resolution
        csv_consolidated = (
            getattr(args, "csv", None)
            or self._get_enumerated_env(f"CSV_consolidated{suffix}")
            or self._get_enumerated_env("CSV_consolidated_1")
        )
        if hasattr(args, "add_csv") and args.add_csv:
            csv_consolidated.extend(args.add_csv)

        config["csv_consolidated"] = csv_consolidated
        config["csv_authors"] = (
            getattr(args, "authors", None)
            or os.getenv(f"CSV_authors{suffix}")
            or os.getenv("CSV_authors_1")
        )
        config["csv_bookmarks"] = (
            getattr(args, "bookmarks", None)
            or os.getenv(f"CSV_bookmarks{suffix}")
            or os.getenv("CSV_bookmarks_1")
        )

        return config

    def _get_enumerated_env(self, prefix):
        """Loads CSV_consolidated_1, CSV_consolidated_2, etc."""
        results = []
        val = os.getenv(prefix)
        if val:
            return [val]

        base_prefix = prefix.rsplit("_", 1)[0] if "_" in prefix else prefix
        for i in range(1, 10):
            val = os.getenv(f"{base_prefix}_{i}")
            if val:
                results.append(val)
        return results

    def add_profile(
        self,
        name,
        vault,
        csv_consolidated,
        path_style="linux",
        vault_windows=None,
        authors=None,
        bookmarks=None,
    ):
        """Persists a new profile to .env safely."""
        if os.path.exists(".env"):
            timestamp = datetime.now().strftime("%Y%m%d")
            shutil.copy(".env", f".env.bak.{timestamp}")

        lines = [
            f"\n# --- Profile: {name} (Added {datetime.now().strftime('%Y-%m-%d')}) ---",
            f"VAULT_{name}={vault}",
            f"PATH_STYLE_{name}={path_style}",
            f"CSV_consolidated_{name}_1={csv_consolidated}",
        ]
        if vault_windows:
            lines.append(f"VAULT_WINDOWS_{name}={vault_windows}")
        if authors:
            lines.append(f"CSV_authors_{name}={authors}")
        if bookmarks:
            lines.append(f"CSV_bookmarks_{name}={bookmarks}")

        with open(".env", "a") as f:
            f.write("\n".join(lines) + "\n")

        load_dotenv(override=True)
