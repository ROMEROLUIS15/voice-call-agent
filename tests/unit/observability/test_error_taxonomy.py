from voice_call_agent.observability.error_taxonomy import ERROR_CATALOG, ErrorCode, ErrorKind
from voice_call_agent.scheduling_backend.scheduling_models import WriteRejectionReason


def test_every_code_has_its_spec() -> None:
    assert set(ERROR_CATALOG) == set(ErrorCode)
    assert all(spec.code is code for code, spec in ERROR_CATALOG.items())


def test_domain_rejections_are_expected_outcomes_not_failures() -> None:
    for reason in WriteRejectionReason:
        assert ERROR_CATALOG[ErrorCode(reason.value)].kind is ErrorKind.EXPECTED_OUTCOME


def test_security_events_are_outcomes_of_protections() -> None:
    security = [spec for spec in ERROR_CATALOG.values() if spec.security_event]
    assert {spec.code for spec in security} >= {
        ErrorCode.WEBHOOK_SIGNATURE_INVALID,
        ErrorCode.WEBHOOK_REPLAY_REJECTED,
        ErrorCode.RATE_LIMITED,
    }
    assert all(spec.kind is ErrorKind.EXPECTED_OUTCOME for spec in security)


def test_provider_failures_are_real_failures() -> None:
    for code in (ErrorCode.STT_EXCEPTION, ErrorCode.LLM_EXCEPTION, ErrorCode.TTS_EXCEPTION):
        assert ERROR_CATALOG[code].kind is ErrorKind.REAL_FAILURE
