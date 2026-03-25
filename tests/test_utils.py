from signal_transcriber.utils import is_voice_message


def test_voice_note_flag():
    assert is_voice_message({"voiceNote": True}) is True


def test_voice_note_false():
    assert is_voice_message({"voiceNote": False}) is False


def test_audio_no_filename():
    assert is_voice_message({"contentType": "audio/aac", "filename": None}) is True


def test_audio_with_filename():
    assert is_voice_message({"contentType": "audio/aac", "filename": "song.mp3"}) is False


def test_non_audio_type():
    assert is_voice_message({"contentType": "image/jpeg"}) is False


def test_empty_attachment():
    assert is_voice_message({}) is False


def test_audio_wildcard():
    """Signal sometimes sends audio/* as content type."""
    assert is_voice_message({"contentType": "audio/*"}) is True


def test_audio_mpeg_no_filename():
    assert is_voice_message({"contentType": "audio/mpeg"}) is True
