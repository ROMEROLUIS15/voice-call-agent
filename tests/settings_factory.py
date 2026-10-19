"""Complete settings for tests, with per-test overrides."""

from voice_call_agent.settings.service_settings import ServiceSettings

PUBLIC_BASE_URL = "https://agent.example.com"
TWILIO_AUTH_TOKEN = "twilio-auth-token"
META_APP_SECRET = "meta-app-secret"
META_VERIFY_TOKEN = "meta-verify-token"


def make_service_settings(**overrides: object) -> ServiceSettings:
    values: dict[str, object] = {
        "deepgram_api_key": "dg-key",
        "groq_api_key": "groq-key",
        "public_base_url": PUBLIC_BASE_URL,
        "twilio_account_sid": "AC00000000000000000000000000000000",
        "twilio_auth_token": TWILIO_AUTH_TOKEN,
        "whatsapp_access_token": "wa-token",
        "whatsapp_phone_number_id": "123456789",
        "whatsapp_app_secret": META_APP_SECRET,
        "whatsapp_verify_token": META_VERIFY_TOKEN,
        # FastAPI's TestClient sends `Host: testserver`.
        "allowed_hosts": "testserver",
    }
    values.update(overrides)
    # `model_validate` skips the environment and `.env` sources: only these values count.
    return ServiceSettings.model_validate(values)
