import os
import tempfile
from pathlib import Path

MAX_MESSAGE_LENGTH = 1800


def make_temp_path(suffix: str = ".m4a") -> Path:
    """Create a temp file atomically and return its path."""
    fd, name = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return Path(name)


def split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split text into chunks that fit within max_length.

    Splits hierarchically: paragraph breaks first, then word boundaries,
    then hard character split as a last resort.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    paragraphs = text.split("\n\n")

    current = ""
    for para in paragraphs:
        needed = len(current) + 2 + len(para) if current else len(para)
        if needed <= max_length:
            current = f"{current}\n\n{para}" if current else para
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(para) <= max_length:
            current = para
            continue

        words = para.split(" ")
        for word in words:
            needed = len(current) + 1 + len(word) if current else len(word)
            if needed <= max_length:
                current = f"{current} {word}" if current else word
                continue

            if current:
                chunks.append(current)
                current = ""

            while len(word) > max_length:
                chunks.append(word[:max_length])
                word = word[max_length:]
            current = word

    if current:
        chunks.append(current)

    return chunks or [text]


def is_voice_message(attachment: dict) -> bool:
    """Detect if an attachment is a voice message."""
    if attachment.get("voiceNote", False):
        return True
    content_type = attachment.get("contentType", "")
    filename = attachment.get("filename")
    if content_type.startswith("audio/") and filename is None:
        return True
    return False
