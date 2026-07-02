import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_CURRICULUM_PATH = Path(__file__).parent.parent.parent / "data" / "curriculum.json"

_curriculum_cache: dict | None = None
_curriculum_mtime: float | None = None


def _load_curriculum() -> dict:
    global _curriculum_cache, _curriculum_mtime

    try:
        current_mtime = os.path.getmtime(_CURRICULUM_PATH)
    except OSError:
        logger.warning("Curriculum file not found at %s, returning empty", _CURRICULUM_PATH)
        _curriculum_cache = {"version": "unknown", "programmes": {}}
        return _curriculum_cache

    if _curriculum_cache is not None and current_mtime == _curriculum_mtime:
        return _curriculum_cache

    try:
        with open(_CURRICULUM_PATH) as f:
            _curriculum_cache = json.load(f)
            _curriculum_mtime = current_mtime
        logger.info("Curriculum data loaded from %s", _CURRICULUM_PATH)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in curriculum file: %s", e)
        _curriculum_cache = {"version": "unknown", "programmes": {}}
    return _curriculum_cache


def get_version() -> str:
    data = _load_curriculum()
    return data.get("version", "unknown")


def get_curriculum() -> dict:
    return _load_curriculum()
