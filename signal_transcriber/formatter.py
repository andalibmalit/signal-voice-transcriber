import asyncio
import logging

from .config import Config
from .transcriber import get_openai_client

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Clean up this voice transcription. Fix punctuation, "
    "add paragraph breaks where appropriate. Do not change the meaning or words. "
    "If the transcription is in a non-English language, keep it in that language."
)


async def format_transcript(raw_text: str, config: Config) -> str:
    """Format a raw transcript with GPT. Falls back to raw text on failure."""
    loop = asyncio.get_running_loop()

    try:
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
    except Exception:
        logger.warning("GPT formatting failed, returning raw transcript", exc_info=True)
        return raw_text
