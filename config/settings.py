"""Central configuration via pydantic-settings (reads .env automatically)."""
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # ── Anthropic ──────────────────────────────────────────────────────────
    # Empty by default — supplied at runtime via the Streamlit UI, not .env
    anthropic_api_key: str = Field("", env="ANTHROPIC_API_KEY")
    agent_model: str = Field("claude-sonnet-4-6", env="AGENT_MODEL")
    agent_max_iterations: int = Field(10, env="AGENT_MAX_ITERATIONS")
    agent_verbose: bool = Field(True, env="AGENT_VERBOSE")

    # ── SWIFT MyStandards (optional) ───────────────────────────────────────
    swift_mystd_username: str = Field("", env="SWIFT_MYSTD_USERNAME")
    swift_mystd_password: str = Field("", env="SWIFT_MYSTD_PASSWORD")
    swift_mystd_api_key: str = Field("", env="SWIFT_MYSTD_API_KEY")

    # ── Paths ──────────────────────────────────────────────────────────────
    standards_library_path: Path = Field(Path("./data/library"), env="STANDARDS_LIBRARY_PATH")
    schemas_path: Path = Field(Path("./data/schemas"), env="SCHEMAS_PATH")
    samples_path: Path = Field(Path("./data/samples"), env="SAMPLES_PATH")

    # ── Logging ────────────────────────────────────────────────────────────
    log_level: str = Field("INFO", env="LOG_LEVEL")

    # ── ISO 20022 source URLs ──────────────────────────────────────────────
    iso20022_catalogue_url: str = "https://www.iso20022.org/iso-20022-message-definitions"
    iso20022_repo_url: str = "https://github.com/ISO20022/iso20022-messages"

    # ── Comparator defaults ────────────────────────────────────────────────
    # XPath patterns treated as benign (ignored unless overridden)
    benign_patterns: list[str] = [
        "MsgId",
        "CreDtTm",
        "InstrId",
        "EndToEndId",
        "TxId",
        "UETR",
        "ClrSysRef",
        "CreationDateTime",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
