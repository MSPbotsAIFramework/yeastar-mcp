"""Non-credential runtime configuration.

Credentials (PBX base URL, client id, client secret) are never read here: they
arrive per-request as headers (see server.py) so one running process can safely
serve many tenants concurrently. This module only holds the HTTP listen
settings, which are the same for every request regardless of tenant.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # The runtime environment may inject variables this project does not
    # declare; `extra="ignore"` keeps those from crashing startup.
    model_config = SettingsConfigDict(extra="ignore")

    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8080


settings = Settings()
