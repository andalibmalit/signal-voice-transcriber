from dataclasses import dataclass, field
import os


@dataclass
class Config:
    signal_api_url: str = field(
        default_factory=lambda: os.getenv("SIGNAL_API_URL", "http://signal-api:8080")
    )
    signal_number: str = field(
        default_factory=lambda: os.getenv("SIGNAL_NUMBER", "")
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
