from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class StudioError(ValueError):
    def __init__(self, message: str, code: str = "invalid_request", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class Config:
    media_root: Path
    workspace: Path
    state_dir: Path
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    threads: int = 4
    port: int = 8741

    @classmethod
    def load(cls) -> "Config":
        preferred = Path.home() / ".config/framedrop/config.json"
        legacy = Path.home() / ".config/montage-studio/config.json"
        default = preferred if preferred.is_file() or not legacy.is_file() else legacy
        location = Path(os.environ.get("FRAMEDROP_CONFIG", os.environ.get("MONTAGE_CONFIG", default))).expanduser()
        values = json.loads(location.read_text()) if location.is_file() else {}
        root = Path(os.environ.get("MONTAGE_MEDIA_ROOT", values.get("media_root", str(Path.home() / "Editing")))).expanduser().resolve()
        workspace = Path(os.environ.get("MONTAGE_WORKSPACE", values.get("workspace", str(root / "Framedrop")))).expanduser().resolve()
        state = Path(os.environ.get("MONTAGE_STATE_DIR", values.get("state_dir", str(Path.home() / ".local/share/framedrop")))).expanduser().resolve()
        return cls(root, workspace, state, values.get("ffmpeg", "ffmpeg"), values.get("ffprobe", "ffprobe"), max(1, min(8, int(values.get("threads", 4)))), int(values.get("port", 8741)))

    def ensure(self) -> None:
        if not self.media_root.is_dir():
            raise StudioError(f"Media folder does not exist: {self.media_root}", "media_root_missing")
        for path in (self.state_dir, self.projects_dir, self.history_dir, self.jobs_dir, self.cache_dir, self.renders_dir):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def projects_dir(self) -> Path:
        return self.workspace / "projects"

    @property
    def history_dir(self) -> Path:
        return self.workspace / "history"

    @property
    def jobs_dir(self) -> Path:
        return self.state_dir / "jobs"

    @property
    def cache_dir(self) -> Path:
        return self.state_dir / "cache"

    @property
    def renders_dir(self) -> Path:
        return self.workspace / "renders"

    def as_dict(self) -> dict:
        return {"media_root": str(self.media_root), "workspace": str(self.workspace), "state_dir": str(self.state_dir), "ffmpeg": self.ffmpeg, "ffprobe": self.ffprobe, "threads": self.threads, "port": self.port}

    @classmethod
    def from_dict(cls, values: dict) -> "Config":
        return cls(Path(values["media_root"]), Path(values["workspace"]), Path(values["state_dir"]), values.get("ffmpeg", "ffmpeg"), values.get("ffprobe", "ffprobe"), int(values.get("threads", 4)), int(values.get("port", 8741)))

    def dependency_status(self) -> dict:
        return {"ffmpeg": shutil.which(self.ffmpeg), "ffprobe": shutil.which(self.ffprobe)}
