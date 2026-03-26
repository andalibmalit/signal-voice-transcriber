from dataclasses import dataclass, field
import os


@dataclass
class Config:
    def __post_init__(self) -> None:
        self.transcribe_mode = self.transcribe_mode.lower()
        valid_modes = {"own_only", "allowlist", "all"}
        if self.transcribe_mode not in valid_modes:
            raise ValueError(
                f"Invalid TRANSCRIBE_MODE '{self.transcribe_mode}'. "
                f"Must be one of: {', '.join(sorted(valid_modes))}"
            )

    signal_api_url: str = field(
        default_factory=lambda: os.getenv("SIGNAL_API_URL", "http://signal-api:8080")
    )
    signal_number: str = field(
        default_factory=lambda: os.getenv("SIGNAL_NUMBER", "")
    )
    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )
    whisper_model: str = field(
        default_factory=lambda: os.getenv("WHISPER_MODEL", "whisper-1")
    )
    gpt_model: str = field(
        default_factory=lambda: os.getenv("GPT_MODEL", "gpt-4o-mini")
    )
    enable_formatting: bool = field(
        default_factory=lambda: os.getenv("ENABLE_GPT_FORMATTING", "true").lower() == "true"
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    attachment_dir: str = field(
        default_factory=lambda: os.getenv(
            "ATTACHMENT_DIR", "/home/.local/share/signal-cli/attachments"
        )
    )
    max_audio_size_mb: int = field(
        default_factory=lambda: int(os.getenv("MAX_AUDIO_SIZE_MB", "25"))
    )
    openai_timeout: int = field(
        default_factory=lambda: int(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
    )
    transcribe_mode: str = field(
        default_factory=lambda: os.getenv("TRANSCRIBE_MODE", "own_only")
    )
    allowed_numbers: list[str] = field(
        default_factory=lambda: [
            n.strip()
            for n in os.getenv("ALLOWED_NUMBERS", "").split(",")
            if n.strip()
        ]
    )
