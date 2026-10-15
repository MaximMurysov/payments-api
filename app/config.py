from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Пустое значение (`WEBHOOK_SECRET=` в .env) считаем незаданным, а не пустой строкой:
    # иначе проверка подписи вебхука включилась бы с пустым ключом.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite:///./payments.db"
    webhook_secret: str | None = None
