"""
Application settings via environment variables / .env file.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "Trading AI API"
    debug: bool = False
    cors_origins: list[str] = ["*"]

    # JWT
    secret_key: str = "change-me-in-production-use-a-real-secret"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24h

    # Database
    database_url: str = "sqlite:///./trading_ai.db"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    use_mock_llm: bool = True

    # Backtest
    default_bars: int = 5000
    chart_output_dir: str = "backtest_charts"

    # MetaApi Cloud
    metaapi_api_key: str = ""
    metaapi_account_id: int = 0  # 0 = no default account

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
