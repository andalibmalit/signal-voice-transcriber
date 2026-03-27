import asyncio
import logging

from .backends import TranscriptionResult
from .config import Config

logger = logging.getLogger(__name__)

_openai_client = None


def get_openai_client(api_key: str, timeout: float = 120):
    """Return a cached OpenAI client, creating one if needed."""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=api_key, timeout=timeout)
    return _openai_client

PAUSE_THRESHOLD = 1.5  # seconds — gap between segments that triggers a paragraph break

_SYSTEM_PROMPT = (
    "Clean up this voice transcription. Fix punctuation, "
    "add paragraph breaks where appropriate. Do not change the meaning or words. "
    "If the transcription is in a non-English language, keep it in that language."
)


def format_with_pauses(result: TranscriptionResult) -> str:
    """Insert paragraph breaks at natural speech pauses using segment timestamps."""
    if not result.segments or len(result.segments) <= 1:
        return result.text

    paragraphs: list[str] = []
    current_paragraph: list[str] = [result.segments[0].text]

    for prev_seg, seg in zip(result.segments, result.segments[1:]):
        gap = seg.start - prev_seg.end
        if gap >= PAUSE_THRESHOLD:
            paragraphs.append(" ".join(current_paragraph))
            current_paragraph = [seg.text]
        else:
            current_paragraph.append(seg.text)

    if current_paragraph:
        paragraphs.append(" ".join(current_paragraph))

    return "\n\n".join(paragraphs)


async def _gpt_format(raw_text: str, config: Config) -> str:
    """Format a transcript using GPT."""
    loop = asyncio.get_running_loop()
    client = get_openai_client(config.openai_api_key, timeout=config.openai_timeout)

    def _call_gpt() -> str:
        result = client.chat.completions.create(
            model=config.gpt_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": raw_text},
            ],
        )
        return result.choices[0].message.content

    formatted = await loop.run_in_executor(None, _call_gpt)
    logger.info("Formatting complete (%d -> %d chars)", len(raw_text), len(formatted))
    return formatted


async def format_transcript(
    result: TranscriptionResult, config: Config
) -> str:
    """Format a transcript. Uses GPT if available, else pause-based breaks."""
    if config.enable_formatting and config.openai_api_key:
        try:
            return await _gpt_format(result.text, config)
        except Exception:
            logger.warning("GPT formatting failed, falling back to pause-based", exc_info=True)

    if result.segments:
        return format_with_pauses(result)

    return result.text
