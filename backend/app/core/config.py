from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App & JWT Auth
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    DEBUG: bool = True
    REQUEST_LOGGING_ENABLED: bool = False
    REQUEST_LOG_DIRECTORY: str = "logs"
    ELASTICSEARCH_URL: str | None = None

    # Database Settings
    DB_NAME: str = "TimeKeepingDB"
    DB_USER: str = "postgres"
    DB_PASSWORD: str
    DB_HOST: str = "postgres_db"
    DB_PORT: int = 5432
    DATABASE_URL: str

    # Redis & Cache Settings
    REDIS_HOST: str = "redis"
    SUMMARY_CACHE_TTL: int = 120
    DASHBOARD_CACHE_REDIS_URL: str | None = None
    DASHBOARD_CACHE_TTL: int = 900
    CELERY_BEAT_CRON_MINUTE: str = "*/5"

    # SMTP Settings
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str
    SMTP_PASS: str
    SMTP_FROM: str

    # Attendance clock-in policy
    ATTENDANCE_GEOFENCE_ENFORCE_DESKTOP: bool = True
    ATTENDANCE_KIOSK_ENABLED: bool = False
    ATTENDANCE_KIOSK_ALLOWED_IPS: str = ""
    ATTENDANCE_KIOSK_REQUIRED_ROLES: str = "admin"

    # Login lockout (identity.users.failed_login_count / locked_until)
    AUTH_MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    AUTH_LOCKOUT_MINUTES: int = 15

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()