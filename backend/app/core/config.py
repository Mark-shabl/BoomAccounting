from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=False)

    database_url: str = Field(default="sqlite:///./dev.db", validation_alias="DATABASE_URL")
    jwt_secret: str = Field(default="change-me", validation_alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    access_token_exp_minutes: int = Field(default=60 * 24 * 7, validation_alias="ACCESS_TOKEN_EXP_MINUTES")

    hf_token: str | None = Field(default=None, validation_alias="HF_TOKEN")
    models_dir: str = Field(default="/models", validation_alias="MODELS_DIR")

    cors_origins: str = Field(default="http://localhost:5173", validation_alias="CORS_ORIGINS")

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("hf_token", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v


settings = Settings()

