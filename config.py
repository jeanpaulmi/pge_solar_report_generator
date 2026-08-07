from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    # MySQL credentials
    DB_USER: str
    DB_PORT: int = 3306

    DB_MODEL_PASSWORD: str
    DB_MODEL_HOST: str

    DB_UAT_MODEL_PASSWORD: str
    DB_UAT_MODEL_HOST: str

    DB_QA_MODEL_PASSWORD: str
    DB_QA_MODEL_HOST: str

    DB_DEV_MODEL_PASSWORD: str
    DB_DEV_MODEL_HOST: str

    DB_AURORA_PASSWORD: str
    DB_AURORA_HOST: str

    DB_UAT_AURORA_PASSWORD: str
    DB_UAT_AURORA_HOST: str

    DB_QA_AURORA_PASSWORD: str
    DB_QA_AURORA_HOST: str

    DB_DEV_AURORA_PASSWORD: str
    DB_DEV_AURORA_HOST: str

    CMS_LCRT_PASSWORD: str
    CMS_LCRT_HOST: str
    
    PSEG_AURORA_PASSWORD: str
    PSEG_AURORA_HOST: str
    
    SCE_AURORA_PASSWORD: str
    SCE_AURORA_HOST: str

    PRICING_ENGINE_PROD_PASSWORD: str
    PRICING_ENGINE_PROD_HOST: str

    PRICING_ENGINE_NONPROD_PASSWORD: str
    PRICING_ENGINE_NONPROD_HOST: str

    # Athena — values live in .env, see .env.example
    ATHENA_DATABASE: str
    ATHENA_S3_STAGING_DIR: str   # s3://your-bucket/athena-results/
    ATHENA_WORKGROUP: str
    ATHENA_REGION: str
    AWS_PROFILE: str

    # PG&E solar report output location (s3://<bucket>/<prefix>/<run folder>/)
    REPORT_S3_BUCKET: str
    REPORT_S3_PREFIX: str

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
