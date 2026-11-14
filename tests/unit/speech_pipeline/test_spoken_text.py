"""What reaches the voice: a caller turn the model wrote into its reply is never read out."""

from tests.browser_peer import reported_error_codes
from voice_call_agent.speech_pipeline.spoken_text import drop_leaked_turn


async def test_a_turn_the_model_wrote_for_the_caller_is_not_spoken() -> None:
    with reported_error_codes() as codes:
        alone = await drop_leaked_turn("userEl martes ", "sentence")
        after = await drop_leaked_turn("¿Para qué día? userEl martes", "sentence")
        its_own = await drop_leaked_turn("assistantPerfecto, el jueves.", "sentence")
    assert (alone, after, its_own) == ("", "¿Para qué día? ", "")
    assert codes == ["MODEL_LEAKED_TURN"] * 3


async def test_words_that_only_look_like_a_turn_are_spoken_as_they_are() -> None:
    lines = ["El usuario pidió un corte.", "user", "Sí, el user manual."]
    with reported_error_codes() as codes:
        spoken = [await drop_leaked_turn(line, "sentence") for line in lines]
    assert spoken == lines
    assert codes == []
