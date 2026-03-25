def is_voice_message(attachment: dict) -> bool:
    """Detect if an attachment is a voice message."""
    if attachment.get("voiceNote", False):
        return True
    content_type = attachment.get("contentType", "")
    filename = attachment.get("filename")
    if content_type.startswith("audio/") and filename is None:
        return True
    return False
