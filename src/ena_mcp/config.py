"""Runtime settings loaded from environment variables (see .env.example)."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENA_MCP_", env_file=".env", extra="ignore")

    ena_portal_url: str = "https://www.ebi.ac.uk/ena/portal/api"
    ena_taxonomy_url: str = "https://www.ebi.ac.uk/ena/taxonomy/rest"
    biosamples_url: str = "https://www.ebi.ac.uk/biosamples"
    http_timeout_seconds: float = 30.0
    transport: Literal["stdio", "streamable-http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000


settings = Settings()
