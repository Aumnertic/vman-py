from dataclasses import dataclass
from pathlib import Path
from .scan import ScanStatus
from .model import EnvironmentStatus

@dataclass
class Environment:
    id: int | None
    path: Path

    python_executable: Path | None
    python_version: str | None
    python_home: Path | None
    manager: str | None

    status: EnvironmentStatus

    discovered_at: int
    last_seen_at: int
    last_verified_at: int | None

    first_seen_scan_id: int | None
    last_seen_scan_id: int | None

    size_bytes: int | None
    size_updated_at: int | None

@dataclass
class Scan:
    id: int | None
    root: Path

    started_at: int
    finished_at: int | None
    status: ScanStatus

    environments_found: int
