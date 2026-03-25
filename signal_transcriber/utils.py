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
        # Check if adding this paragraph (with separator) fits
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_length:
            current = candidate
            continue

        # Flush current chunk if non-empty
        if current:
            chunks.append(current)
            current = ""

        # If the paragraph itself fits, start a new chunk with it
        if len(para) <= max_length:
            current = para
            continue

        # Paragraph too long — split by words
        words = para.split(" ")
        for word in words:
            candidate = f"{current} {word}" if current else word
            if len(candidate) <= max_length:
                current = candidate
                continue

            if current:
                chunks.append(current)
                current = ""

            # Single word exceeds max_length — hard split
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
