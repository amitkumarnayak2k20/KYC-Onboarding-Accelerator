import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "kyc-onboarding-agent")
    app_version: str = os.getenv("APP_VERSION", "0.1.0")
    environment: str = os.getenv("ENVIRONMENT", "local")
    database_path: str = os.getenv("DATABASE_PATH", "./kyc_demo.db")
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock").lower()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    otel_enabled: bool = os.getenv("OTEL_ENABLED", "false").lower() == "true"
    otel_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    drift_window_size: int = int(os.getenv("DRIFT_WINDOW_SIZE", "20"))
    drift_min_samples: int = int(os.getenv("DRIFT_MIN_SAMPLES", "10"))
    drift_warning_accuracy: float = float(os.getenv("DRIFT_WARNING_ACCURACY", "0.97"))
    drift_critical_accuracy: float = float(os.getenv("DRIFT_CRITICAL_ACCURACY", "0.95"))

settings = Settings()
