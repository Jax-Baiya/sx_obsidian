import re
from pathlib import Path


class PathResolver:
    def __init__(self, config):
        self.config = config
        self.style = config.get("path_style", "linux").lower()
        # The vault path on the machine running the generator/API.
        # This may differ from the style-specific vault root used to *format* paths
        # for protocols (e.g., Windows drive letters when generating from Linux).
        self.vault_os_root = config.get("vault")
        self.vault_root = self._get_vault_root()
        self.data_dir = config.get("data_dir", "data")

    def _get_vault_root(self):
        # Specific override for OS style if exists and is not empty
        style_key = f"vault_{self.style}"
        override = self.config.get(style_key)
        if override:
            return override
        return self.config.get("vault")

    def resolve_absolute(self, relative_path):
        """Resolves a media file to an absolute path based on style."""
        if not relative_path:
            return ""

        # Base path: vault + data_dir + relative_path
        parts = [self.vault_root, self.data_dir, relative_path]

        if self.style == "windows":
            # Use backslashes
            path = "\\".join(p.replace("/", "\\").strip("\\") for p in parts if p)
            # Ensure drive colon isn't double backslashed if it's there
            path = re.sub(r"([A-Z]):\\+", r"\1:\\", path, flags=re.I)
            return path

        # Use forward slashes
        path = "/".join(p.replace("\\", "/").strip("/") for p in parts if p)
        if self.vault_root and self.vault_root.startswith("/"):
            path = "/" + path
        return path

    def resolve_os_absolute(self, relative_path: str | None) -> str:
        """Resolve using the *runtime OS* vault root (config['vault']).

        This is useful for checking existence even when path_style=windows and
        `vault_windows` points to an unmapped drive on the current OS.
        """

        if not relative_path:
            return ""

        base = self.vault_os_root or self.vault_root
        if not base:
            return ""

        rel = str(relative_path).replace("\\", "/").lstrip("/")
        data_dir = str(self.data_dir or "data").replace("\\", "/").strip("/")
        return str(Path(base) / data_dir / Path(rel))

    def exists(self, relative_path: str | None) -> bool:
        p = self.resolve_os_absolute(relative_path)
        if not p:
            return False
        try:
            return Path(p).exists()
        except Exception:
            return False

    def format_protocol(self, protocol, path):
        """Returns a formatted protocol link."""
        return f"{protocol}:{path}"
