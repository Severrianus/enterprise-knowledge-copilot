from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file = PROJECT_ROOT / ".env",
        env_file_encoding = "utf-8",
        extra = "ignore",
    )


    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5433
    postgres_db: str
    postgres_user: str
    postgres_password: SecretStr
    auth_jwt_secret: SecretStr
    minio_endpoint: str
    minio_root_user: str
    minio_root_password: SecretStr
    minio_bucket: str = "ekc-raw"
    dashscope_api_key: SecretStr | None = None
    dashscope_base_url: str | None = None
    milvus_uri: str = "http://127.0.0.1:19530"
    zhipu_api_key: SecretStr | None = None
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zhipu_model: str = "glm-4.5-flash"

settings = Settings()