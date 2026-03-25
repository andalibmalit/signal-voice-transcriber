from signal_transcriber.utils import is_voice_message, split_message


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


# ── split_message tests ──────────────────────────────────────


def test_split_short_message():
    assert split_message("Hello world") == ["Hello world"]


def test_split_empty_string():
    assert split_message("") == [""]


def test_split_at_paragraph_boundary():
    para1 = "A" * 100
    para2 = "B" * 100
    text = f"{para1}\n\n{para2}"
    chunks = split_message(text, max_length=150)
    assert chunks == [para1, para2]


def test_split_at_word_boundary():
    words = " ".join(["word"] * 100)  # 499 chars
    chunks = split_message(words, max_length=50)
    assert all(len(c) <= 50 for c in chunks)
    assert " ".join(chunks) == words


def test_split_hard_break_on_long_word():
    long_word = "x" * 200
    chunks = split_message(long_word, max_length=80)
    assert all(len(c) <= 80 for c in chunks)
    assert "".join(chunks) == long_word


def test_split_respects_max_length():
    text = "\n\n".join(["A" * 50] * 100)  # many paragraphs
    chunks = split_message(text, max_length=200)
    assert all(len(c) <= 200 for c in chunks)
