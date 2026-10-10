import os
from pathlib import Path

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
DEFAULT_MANIFEST_PATH = STATE_DIR / "vman-py/manifest.json"
