"""What the judge reads: the call in order, each tool with the line spoken after its result."""

from evals.conversation_harness.call_transcript import SpokenTurn, call_transcript
from evals.conversation_harness.scripted_speech import RecordedToolCall
from evals.judge_scoring import judge_scenario
from tests.evals.eval_runs_factory import golden_case

AVAILABILITY = RecordedToolCall(
    "check_availability", {"service_id": "s", "day": "2026-10-27"}, {"slots": ["10:00"]}
)
PROPOSAL = RecordedToolCall("propose_booking", {"service_id": "s"}, {"proposal_id": "p"})


def test_a_line_said_before_a_tool_does_not_shift_the_call() -> None:
    lines = ["Hola.", "Un momento, reviso.", "Tengo libre a las diez.", "Te propongo las diez."]
    turns = call_transcript(
        lines,
        {2: (AVAILABILITY,), 3: (PROPOSAL,)},
        [(1, "Quiero una cita mañana."), (3, "A las diez está bien.")],
    )
    assert turns == (
        SpokenTurn("assistant", "Hola."),
        SpokenTurn("user", "Quiero una cita mañana."),
        SpokenTurn("assistant", "Un momento, reviso."),
        SpokenTurn("assistant", "Tengo libre a las diez.", (AVAILABILITY,)),
        SpokenTurn("user", "A las diez está bien."),
        SpokenTurn("assistant", "Te propongo las diez.", (PROPOSAL,)),
    )


def test_tools_with_nothing_said_after_them_still_reach_the_judge() -> None:
    turns = call_transcript(["Hola."], {1: (PROPOSAL,)}, [(1, "Sí, confirmo.")])
    assert turns[-2:] == (
        SpokenTurn("user", "Sí, confirmo."),
        SpokenTurn("assistant", "", (PROPOSAL,)),
    )


def test_the_judge_reads_the_prompt_the_model_received() -> None:
    case = golden_case("unpublished-price-at-a-dental-clinic")
    scenario = judge_scenario(case, "PROMPT OF THE BUSINESS THE CALL REACHED")
    assert scenario.startswith(case.title)
    assert scenario.endswith("PROMPT OF THE BUSINESS THE CALL REACHED")
