import os
import tempfile
from pathlib import Path


def make_temp_path(suffix: str = ".m4a") -> Path:
    """Create a temp file atomically and return its path."""
    fd, name = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return Path(name)


def is_voice_message(attachment: dict) -> bool:
    """Detect if an attachment is a voice message."""
    if attachment.get("voiceNote", False):
        return True
    content_type = attachment.get("contentType", "")
    filename = attachment.get("filename")
    if content_type.startswith("audio/") and filename is None:
        return True
    return False
