"""The composition root wires every real component without touching the network."""

from tests.settings_factory import make_service_settings
from voice_call_agent.call_transports.twilio_media_streams.call_termination import (
    TwilioCallTerminator,
)
from voice_call_agent.call_transports.whatsapp_calling.call_acceptance import (
    WhatsAppCallAcceptor,
)
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.practice_schedule.practice_catalog import load_practice_catalog
from voice_call_agent.service_composition import compose_service
from voice_call_agent.speech_pipeline.conversation_runner import PipecatConversationRunner


def test_both_entries_are_wired_when_configured() -> None:
    components = compose_service(make_service_settings(max_concurrent_calls=3))
    assert isinstance(components.conversation_runner, PipecatConversationRunner)
    assert isinstance(components.call_terminator, TwilioCallTerminator)
    assert isinstance(components.call_acceptor, WhatsAppCallAcceptor)
    assert components.supervisor.can_accept_call()


def test_disabled_entries_get_no_components() -> None:
    components = compose_service(
        make_service_settings(
            public_base_url=None,
            twilio_account_sid=None,
            twilio_auth_token=None,
            whatsapp_access_token=None,
            whatsapp_phone_number_id=None,
            whatsapp_app_secret=None,
            whatsapp_verify_token=None,
        )
    )
    assert components.call_terminator is None
    assert components.call_acceptor is None


def test_the_practice_schedule_is_wired_only_when_chosen() -> None:
    assert compose_service(make_service_settings()).business_resolver is None
    practice = compose_service(
        make_service_settings(scheduling_backend="practice", environment="development")
    )
    assert isinstance(practice.business_resolver, InMemorySchedule)


def test_the_practice_page_gets_a_line_per_practice_number() -> None:
    assert compose_service(make_service_settings()).practice_lines == ()
    practice = compose_service(
        make_service_settings(scheduling_backend="practice", environment="development")
    )
    names = {line.business_name for line in practice.practice_lines}
    assert names == {business.name for business in load_practice_catalog().businesses}
