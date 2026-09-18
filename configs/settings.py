import os

from dotenv import load_dotenv

# Load .env once here
load_dotenv()


class Settings:
    """Environment-driven configuration, loaded once at import time."""

    def __init__(self):
        # ── Logging ──────────────────────────────────────────────────────
        self.app_env = os.getenv("APP_ENV", "dev")
        self.log_level = os.getenv("LOG_LEVEL", "DEBUG")
        self.log_format = os.getenv(
            "LOG_FORMAT",
            "[ %(asctime)s | %(levelname)s | %(seed)s | %(name)s | %(filename)s:%(lineno)d ] %(message)s",
        )
        self.log_date_format = os.getenv("LOG_DATE_FORMAT", "%d/%m/%Y %H:%M:%S")
        self.enable_strands_log = os.getenv("ENABLE_STRANDS_LOG", False)

        # ── Brand / persona ──────────────────────────────────────────────
        self.brand_name = os.getenv("BRAND_NAME", "the store")

        # ── AWS Bedrock ──────────────────────────────────────────────────
        self.region = os.getenv("REGION")

        # One model id drives every agent by default; individual agents can
        # be pointed at a different model via the optional overrides below.
        self.orchestrator_model_id = os.getenv("ORCHESTRATOR_MODEL_ID")
        self.specialist_model_id = (
            os.getenv("SPECIALIST_MODEL_ID") or self.orchestrator_model_id
        )
        self.auth_model_id = (
            os.getenv("AUTH_MODEL_ID") or self.specialist_model_id
        )

        self.guardrail_id = os.getenv("GUARDRAIL_ID")
        self.guardrail_version = os.getenv("GUARDRAIL_VERSION")

        # Knowledge base (FAQ, terms & conditions) queried for support answers
        self.knowledge_base_id = os.getenv("KNOWLEDGE_BASE_ID", "WAGW4RXPZ7")
        self.knowledge_base_top_k = int(os.getenv("KNOWLEDGE_BASE_TOP_K", "5"))

        self.agent_core_mem_id = os.getenv("AGENTCORE_MEMORY_ID")

        # ── E-commerce backend (Express API exposed to the agent as tools) ─
        self.ecommerce_api_base_url = os.getenv("ECOMMERCE_API_BASE_URL")
        self.ecommerce_auth_scheme = os.getenv("ECOMMERCE_AUTH_SCHEME", "Bearer")
        self.ecommerce_api_timeout = int(os.getenv("ECOMMERCE_API_TIMEOUT", "30"))

        self._validate()

    def _validate(self):
        """Only enforce the vars without which the app cannot start."""
        missing = []

        if not self.region:
            missing.append("REGION")
        if not self.orchestrator_model_id:
            missing.append("ORCHESTRATOR_MODEL_ID")

        if missing:
            raise ValueError(f"Missing required env vars: {', '.join(missing)}")


# Singleton instance shared across app
settings = Settings()
