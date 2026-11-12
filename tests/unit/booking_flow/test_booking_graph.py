"""The booking graph: one task and only its functions per node, the code's greeting and
read-back, and transitions that follow each function's outcome (ADR 0019)."""

from datetime import timedelta
from typing import Any, cast

from pipecat.flows import NO_RESPONSE, FlowManager, FlowsFunctionSchema, NodeConfig
from pipecat.frames.frames import TTSSpeakFrame

from tests.practice_catalogs import MONDAY, TWO_BUSINESSES
from tests.write_guard_fixtures import CALL_ID, TUESDAY, GuardedCall, guarded_call
from voice_call_agent.booking_flow.booking_graph import BookingGraph, booking_functions
from voice_call_agent.booking_flow.booking_steps import BookingSteps
from voice_call_agent.booking_flow.spoken_lines import say
from voice_call_agent.booking_flow.step_outcomes import Step
from voice_call_agent.conversation_content.content_loader import load_conversation_content

CONTENT = load_conversation_content()
GREETING = "Hola, Barbería Uno."
ROLE = "rol del negocio"


class _Worker:
    def __init__(self) -> None:
        self.frames: list[object] = []

    async def queue_frame(self, frame: object) -> None:
        self.frames.append(frame)


async def _enter(node: NodeConfig) -> list[object]:
    """Runs the node's actions as Flows does on entering it; the frames it queued."""
    worker = _Worker()
    manager = type("_Manager", (), {"worker": worker})()  # Only the worker is used.
    for action in node.get("pre_actions", []):
        handler = cast(Any, action["handler"])  # Any: Flows types it as either handler shape.
        await handler(action, cast(FlowManager, manager))
    return worker.frames


def _graph(call: GuardedCall) -> tuple[BookingGraph, BookingSteps]:
    steps = BookingSteps(
        call_id=CALL_ID,
        catalog=TWO_BUSINESSES.business("barbershop").services,
        backend=call.backend,
        guard=call.guard,
        content=CONTENT,
        weekly_hours=TWO_BUSINESSES.business("barbershop").weekly_hours,
        today=MONDAY,
    )
    graph = BookingGraph(
        steps=steps,
        content=CONTENT,
        role=ROLE,
        greeting=GREETING,
        on_read_back=lambda: READ_BACKS.append("armed"),
    )
    return graph, steps


READ_BACKS: list[str] = []


def _functions(node: NodeConfig) -> dict[str, FlowsFunctionSchema]:
    return {
        function.name: function
        for function in node.get("functions", [])
        if isinstance(function, FlowsFunctionSchema)
    }


def _said(node: NodeConfig) -> list[str]:
    """What the code says on entering the node; never through Flows' waited-for `tts_say`."""
    actions = node.get("pre_actions", [])
    assert all(action["type"] != "tts_say" for action in actions)
    return [action["text"] for action in actions]


async def _run(function: FlowsFunctionSchema, **arguments: Any) -> tuple[Any, NodeConfig | None]:
    # The handler does not use the manager: the steps keep the call's state.
    result: tuple[Any, NodeConfig | None] = await function.handler(
        arguments, FlowManager.__new__(FlowManager)
    )  # type: ignore[call-arg]
    return result


async def test_the_call_starts_with_the_greeting_and_waits_for_the_caller() -> None:
    graph, _ = _graph(await guarded_call())
    node = graph.initial_node()
    assert node.get("role_message") == ROLE
    assert _said(node) == [GREETING]
    assert node.get("respond_immediately") is False
    [check] = _functions(node).values()
    assert check.name == "check_availability"
    # No enums: a provider that validates them silences the turn; the code checks the service.
    assert "enum" not in check.properties["service_id"]


async def test_choosing_a_time_says_the_free_starts_as_ranges() -> None:
    graph, _ = _graph(await guarded_call())
    check = _functions(graph.initial_node())["check_availability"]
    _, node = await _run(check, service_id="haircut", day_number=TUESDAY.day)
    assert node is not None and node.get("name") == Step.CHOOSE_TIME.value
    # The code says them, as the backend offered them, and the model waits for the choice.
    assert _said(node) == [
        "El martes veintisiete de octubre hay horas libres de las nueve de la mañana a las "
        "cinco y media de la tarde. ¿A qué hora sería la cita?"
    ]
    assert node.get("respond_immediately") is False
    functions = _functions(node)
    assert set(functions) == {"select_start", "check_availability"}
    assert "enum" not in functions["select_start"].properties["start"]
    [task] = node.get("task_messages", [])
    content = str(task["content"])
    assert "(09:00 a 17:30), con inicio cada 30 minutos." in content
    assert "las once de la mañana" not in content  # Ranges, not every start.


async def test_a_time_that_does_not_work_is_said_with_why_before_the_free_times() -> None:
    graph, _ = _graph(await guarded_call())
    check = _functions(graph.initial_node())["check_availability"]
    _, node = await _run(check, service_id="haircut", day_number=TUESDAY.day, start="07:00")
    assert node is not None
    [said] = _said(node)
    assert said.startswith("A las siete de la mañana queda fuera del horario de ese día, de ")
    assert "El martes veintisiete de octubre hay horas libres de las nueve" in said


async def test_the_proposal_is_read_back_by_the_code_and_the_model_waits() -> None:
    graph, _ = _graph(await guarded_call())
    check = _functions(graph.initial_node())["check_availability"]
    _, name_node = await _run(check, service_id="haircut", day_number=TUESDAY.day, start="15:30")
    assert name_node is not None
    assert set(_functions(name_node)) == {"propose_booking", "check_availability"}
    # The code asks for the name: no second model round to ask it.
    assert _said(name_node) == ["¿A nombre de quién sería la cita?"]
    assert name_node.get("respond_immediately") is False
    _, confirm = await _run(_functions(name_node)["propose_booking"], client_name="Ana Ejemplo")
    assert confirm is not None and confirm.get("name") == Step.CONFIRM.value
    assert confirm.get("respond_immediately") is False
    assert _said(confirm) == [
        "Para confirmar: Corte, el martes veintisiete de octubre, a las tres y media "
        "de la tarde, a nombre de Ana Ejemplo. ¿Está bien así?"
    ]
    assert set(_functions(confirm)) == {"confirm_booking", "change_request", "check_availability"}


async def test_a_name_given_with_the_chosen_time_skips_asking_for_it() -> None:
    call = await guarded_call()
    graph, _ = _graph(call)
    check = _functions(graph.initial_node())["check_availability"]
    _, choose = await _run(check, service_id="haircut", day_number=TUESDAY.day)
    assert choose is not None
    assert "client_name" not in _functions(choose)["select_start"].required
    call.caller_speaks()
    select = _functions(choose)["select_start"]
    _, confirm = await _run(select, start="15:30", client_name="Ana Ejemplo")
    assert confirm is not None and confirm.get("name") == Step.CONFIRM.value
    assert _said(confirm)[0].endswith("a nombre de Ana Ejemplo. ¿Está bien así?")


async def test_the_booking_is_announced_by_the_code_and_the_model_waits() -> None:
    call = await guarded_call()
    graph, _ = _graph(call)
    check = _functions(graph.initial_node())["check_availability"]
    _, name_node = await _run(check, service_id="haircut", day_number=TUESDAY.day, start="15:30")
    assert name_node is not None
    _, confirm = await _run(_functions(name_node)["propose_booking"], client_name="Ana Ejemplo")
    assert confirm is not None
    call.caller_speaks()
    _, booked = await _run(_functions(confirm)["confirm_booking"])
    assert booked is not None and booked.get("name") == Step.BOOKED.value
    # What the backend booked, said by the code: no second model round to announce it.
    assert _said(booked) == [
        "Listo, la cita quedó agendada para el martes veintisiete de octubre, a las tres y media "
        "de la tarde. ¿Algo más en lo que pueda ayudar?"
    ]
    assert booked.get("respond_immediately") is False
    assert set(_functions(booked)) == {"new_request"}


async def test_a_weekday_that_does_not_match_the_date_is_asked_by_the_code() -> None:
    graph, _ = _graph(await guarded_call())
    check = _functions(graph.initial_node())["check_availability"]
    _, node = await _run(check, service_id="haircut", day_number=TUESDAY.day, weekday="jueves")
    assert node is not None and node.get("name") == Step.WHICH_DAY.value
    assert _said(node) == [
        "El veintisiete de octubre es martes. ¿La cita es para el martes veintisiete de octubre "
        "o para el jueves veintinueve de octubre?"
    ]
    assert node.get("respond_immediately") is False
    assert set(_functions(node)) == {"check_availability"}
    [task] = node.get("task_messages", [])
    assert "(2026-10-27)" in str(task["content"]) and "(2026-10-29)" in str(task["content"])
    again = _functions(node)["check_availability"]
    _, chosen = await _run(again, service_id="haircut", day_number=TUESDAY.day, weekday="martes")
    assert chosen is not None and chosen.get("name") == Step.CHOOSE_TIME.value


async def test_a_step_that_stays_returns_no_node() -> None:
    graph, _ = _graph(await guarded_call())
    check = _functions(graph.initial_node())["check_availability"]
    result, node = await _run(check, service_id="massage", day_number=TUESDAY.day)
    assert (result["status"], node) == ("unknown_service", None)


async def test_a_line_the_code_says_on_a_result_is_spoken_and_the_model_waits() -> None:
    graph, _ = _graph(await guarded_call())
    check = _functions(graph.initial_node())["check_availability"]
    sunday = (TUESDAY + timedelta(days=5)).day
    result, node = await _run(check, service_id="haircut", day_number=sunday)
    assert result["status"] == "closed_day"
    assert node is not None and node["name"] == "request"
    assert _said(node) == [
        "El domingo uno de noviembre no se atiende. ¿Para qué otro día sería la cita?"
    ]
    assert node["respond_immediately"] is False


async def test_a_service_queued_in_the_same_turn_keeps_the_first_ones_node() -> None:
    graph, _ = _graph(await guarded_call())
    check = _functions(graph.initial_node())["check_availability"]
    await _run(check, service_id="haircut", day_number=TUESDAY.day, start="11:00")
    result, node = await _run(check, service_id="full", day_number=TUESDAY.day, start="11:00")
    assert result["status"] == "queued"
    assert cast(object, node) is NO_RESPONSE  # Flows' sentinel: stay silent on the node.


async def test_a_chosen_time_that_is_not_free_is_answered_by_the_code() -> None:
    call = await guarded_call()
    graph, _ = _graph(call)
    check = _functions(graph.initial_node())["check_availability"]
    _, choose = await _run(check, service_id="haircut", day_number=TUESDAY.day)
    assert choose is not None
    call.caller_speaks()
    result, node = await _run(_functions(choose)["select_start"], start="03:00")
    assert result == {"status": "not_offered", "start": "03:00"}
    # The code says why and offers again; the model does not answer it in a second round.
    assert node is not None and node["name"] == Step.CHOOSE_TIME.value
    [said] = _said(node)
    assert said.startswith("A las tres de la madrugada queda fuera del horario de ese día")
    assert node.get("respond_immediately") is False


async def test_the_read_back_says_the_services_waiting_for_the_proposal() -> None:
    graph, _ = _graph(await guarded_call())
    check = _functions(graph.initial_node())["check_availability"]
    said = {"day_number": TUESDAY.day, "start": "11:00"}
    await _run(check, service_id="haircut", client_name="Ana Ejemplo", **said)
    result, node = await _run(check, service_id="full", **said)
    # Queued in the same response as the proposal: the read-back is built again with it, so
    # the caller hears it waits and does not ask for it again.
    assert result["status"] == "queued"
    assert node is not None and cast(object, node) is not NO_RESPONSE
    assert node["name"] == Step.CONFIRM.value
    assert _said(node) == [
        "Para confirmar: Corte, el martes veintisiete de octubre, a las once de la mañana, a "
        "nombre de Ana Ejemplo. Después seguimos con corte y barba. ¿Está bien así?"
    ]


async def test_the_next_service_is_announced_in_one_line_with_its_read_back() -> None:
    call = await guarded_call()
    graph, _ = _graph(call)
    check = _functions(graph.initial_node())["check_availability"]
    said = {"day_number": TUESDAY.day, "start": "11:00"}
    await _run(check, service_id="haircut", client_name="Ana Ejemplo", **said)
    await _run(check, service_id="full", **said)
    call.caller_speaks()
    confirm = _functions(graph.node(Step.CONFIRM))["confirm_booking"]
    _, node = await _run(confirm)
    assert node is not None and node["name"] == "confirm"
    # One line, so the caller hears one reply: the booking done, the next service, its read-back.
    [line] = _said(node)
    assert line.startswith("Listo, la cita de corte quedó agendada")
    assert "Ahora, la de corte y barba. Para confirmar: Corte y barba" in line


async def test_not_booked_offers_nothing_more_to_call() -> None:
    graph, _ = _graph(await guarded_call())
    assert _functions(graph.node(Step.NOT_BOOKED)) == {}


def test_every_function_the_model_receives_is_described() -> None:
    functions = booking_functions()
    assert set(functions) == {
        "check_availability",
        "select_start",
        "propose_booking",
        "confirm_booking",
        "change_request",
        "new_request",
    }
    assert functions["propose_booking"]["required"] == ["client_name"]
    # The day is worked out by the code from the caller's words: the model need not pass it.
    assert functions["check_availability"]["required"] == ["service_id"]


async def test_a_line_the_code_says_is_spoken_and_never_waited_for() -> None:
    queued: list[object] = []

    class _Worker:
        async def queue_frame(self, frame: object) -> None:
            queued.append(frame)

    class _Manager:
        worker = _Worker()

    action = say("Hola.")
    await action["handler"](dict(action), _Manager())  # type: ignore[arg-type,call-arg]
    [frame] = queued
    assert isinstance(frame, TTSSpeakFrame) and frame.text == "Hola."


def test_no_schema_constraint_a_provider_could_reject_a_turn_on() -> None:
    for function in booking_functions().values():
        for spec in function["properties"].values():
            types = spec.get("anyOf", [spec])
            assert all(not {"format", "pattern", "enum"} & set(t) for t in types), spec


async def test_a_time_said_in_words_is_answered_with_the_field_to_correct() -> None:
    graph, _ = _graph(await guarded_call())
    check = _functions(graph.initial_node())["check_availability"]
    result, node = await _run(check, service_id="haircut", day_number=TUESDAY.day, start="seven am")
    assert (result, node) == ({"status": "invalid_arguments", "fields": ["start"]}, None)


async def test_every_read_back_is_watched_and_no_other_line_is() -> None:
    READ_BACKS.clear()
    call = await guarded_call()
    graph, _ = _graph(call)
    await _enter(graph.initial_node())  # The greeting is not watched.
    assert READ_BACKS == []
    check = _functions(graph.initial_node())["check_availability"]
    said = {"day_number": TUESDAY.day, "start": "11:00"}
    _, confirm = await _run(check, service_id="haircut", client_name="Ana Ejemplo", **said)
    assert confirm is not None
    [frame] = await _enter(confirm)
    # Armed when the line is queued: speech over it from then on is speech over the read-back.
    assert READ_BACKS == ["armed"] and isinstance(frame, TTSSpeakFrame)
    await _run(check, service_id="full", **said)
    call.caller_speaks()
    _, next_confirm = await _run(_functions(graph.node(Step.CONFIRM))["confirm_booking"])
    assert next_confirm is not None
    await _enter(next_confirm)  # The booking done and the next read-back, in one line.
    assert READ_BACKS == ["armed", "armed"]


async def test_a_read_back_not_heard_is_read_again_in_one_line_and_watched_again() -> None:
    READ_BACKS.clear()
    heard = [False]
    call = await guarded_call(read_back_heard=lambda: heard[0])
    graph, _ = _graph(call)
    check = _functions(graph.initial_node())["check_availability"]
    said = {"day_number": TUESDAY.day, "start": "11:00"}
    _, confirm = await _run(check, service_id="haircut", client_name="Ana Ejemplo", **said)
    assert confirm is not None
    await _enter(confirm)
    call.caller_speaks()  # "Sí" over the read-back.
    result, again = await _run(_functions(confirm)["confirm_booking"])
    assert result["status"] == "read_back_repeated"
    assert again is not None and again["name"] == Step.CONFIRM.value
    [line] = _said(again)
    assert line.startswith("Perdón, lo repito completo. Para confirmar: Corte, el martes")
    await _enter(again)
    assert READ_BACKS == ["armed", "armed"]
    assert await call.backend.upcoming_appointments(CALL_ID) == []  # Nothing was written.
