# Tasks: connect the agent to Cronix

The steps from today's agent, which books against the practice schedule, to calls that book in
Cronix. Cronix is in production with real businesses: the agent adopts Cronix's data and rules as
they are, tries them in a local copy of Cronix, never in production, and adjusts each decision.

This file is temporary. It is deleted when Stage D ends; what stays true moves to the contract
(`docs/specs/cronix-phone-api-contract.md`), the manifest and the ADRs. A box is ticked in the pull
request that does it; a decision taken on the way goes under **Decisions** with its date.

## What Cronix does today

Read from the Cronix repository on 2026-10-28; each fact names where it lives there.

- **Opening hours** are the owner's, set in the dashboard's settings:
  `businesses.settings.workingHours`, one entry per weekday (`mon`…`sun`), `[open, close]` or
  `null` when closed (`lib/validations/settings.schema.ts`). One opening and one closing per day:
  no break. `workingHoursConfirmed` says whether the owner set them or they are the defaults seeded
  at signup.
- **Time zone** per business: `businesses.timezone` (nullable). The dashboard's voice agent uses
  the browser's time zone instead (`voice-worker/index.ts`).
- **Services**: `services` with `duration_min`, `price` (a number) and `is_active`. **No currency
  anywhere**: the reports format prices as USD (`lib/utils/report-pdf-generator.ts`).
- **Overlaps depend on the channel.** WhatsApp's functions check the whole business; the
  dashboard's voice agent checks only the assigned staff member when there is one; in the
  dashboard the owner may confirm an overlap (`appointments.is_dual_booking`). Production holds
  thousands of legitimate overlaps between staff members, so a database rule per business is not
  possible; a rule per staff member waits for Cronix's multi-employee work, with the meaning of
  `is_dual_booking` and of appointments without staff decided there (`modulo-voice-agent`).
- **Free starts** every 30 minutes, where the service ends by closing and overlaps no appointment.
  Three implementations, which differ:

  | | WhatsApp (`process-whatsapp/availability.ts`) | Database (`fn_get_available_slots`) | Booking (`fn_book_appointment_wa`) |
  |---|---|---|---|
  | Statuses that block | those it loaded | all but `cancelled` | all but `cancelled`, `no_show` |
  | Times already past | dropped | **kept** | not checked |
  | Hours never set | 09:00–18:00 | **no starts** | not checked |
  | Opening hours | checked | checked | **not checked** |

- **Booking**: `fn_book_appointment_wa(business, client_phone, client_name, service, start)`
  finds or creates the client **by phone** (a missing name becomes `Cliente` and the last four
  digits, replaced when a name arrives), checks the overlap, then inserts the appointment as
  `confirmed` with a note naming WhatsApp. A conflict comes back as free text (`Slot no
  disponible.`); an unknown service as `SERVICE_NOT_FOUND`.
- **The overlap check was not atomic**: it read, then inserted, with no lock, exclusion
  constraint or unique index on appointments, so two bookings at the same moment could both
  succeed (B3 closes it for the booking functions).
- **Business by phone**: `fn_get_business_by_phone` matches `businesses.phone_digits` (the
  business's own number) or `settings.wa_phone_number_id`. A phone line's dialed number is neither
  today.
- **Rules of the Cronix repository**: its SDD gate (`CLAUDE.md`, `docs/specs/INDEX.md`) asks to read
  the constitution and the module's manifest before any code, and to declare an area without a
  spec before coding it; migrations are immutable; every `SECURITY DEFINER` function reachable
  from outside asserts the business; Edge Functions are checked with `deno check` and `deno test`,
  and deployed from Windows with `supabase functions deploy <name> --use-api`; the local database
  runs with Docker (`npx supabase db reset` applies the migrations and the seed).

## Stage A: Cronix's rules in the agent, said by ranges (agent)

The practice schedule copies Cronix's rules, so what is tried in practice is what Cronix does.

- [x] **A1. The practice schedule follows Cronix**: starts every 30 minutes, the service ending
      by closing, overlaps checked for the whole business as WhatsApp's booking does, hours as
      `[open, close]` per weekday, past times dropped.
- [x] **A2. Free times by ranges.** Consecutive starts form a range that ends when the service
      would end after its last start; a lone start is said on its own
      (`booking_flow/free_ranges.py`). The time-choice task offers the ranges nearest to what the caller asked
      for (morning, afternoon, a time).
- [x] **A3. Why a time does not work**, from the starts and the service's duration: the service
      would not end before the next appointment or closing, the time is off the 30-minute
      interval, or it is taken; a closed day is answered by the availability itself.
- [x] **A4. Tests, golden cases with invented data, model evals and a practice call**; one pull
      request with README, manifest and golden dataset. The practice call said the free times by
      ranges, explained why a time before opening did not work, and booked after a change of
      service at the confirmation.

## Stage B: the contract's endpoints in Cronix (Cronix repository)

What changes in Cronix is tracked here, not in Cronix's own specs, unless the change is large.

- [ ] **B1. A local Cronix**: Docker and the local Supabase stack (`npx supabase start`; pending
      migrations with `npx supabase migration up --local`, never a reset of the local data), and a
      seed of invented businesses (services of several durations, hours with a closed day, booked
      appointments). Never the production project. The stack runs; the seed is pending.
- [x] **B3. Bookings that cannot overlap at the same moment** (Cronix pull request #29, merged):
      `fn_book_appointment_wa` and `fn_reschedule_appointment_wa` take a lock per business before
      their overlap check, so a second booking of the same time waits and sees the first; the
      booking answers `SLOT_CONFLICT`, as the reschedule did. Tried in the local Cronix: pgTAP
      164/164, and two connections booking one time at once left one appointment, the second
      answered `SLOT_CONFLICT` after waiting 2.35 s. Its deployment is the maintainer's: the
      migration first, then the Edge Functions. The phone endpoints book through the same function.
- [x] **B4. One computation of free starts** (Cronix pull request #30, which also fixes an import
      the tests could not see and Deno resolves): WhatsApp's resolver
      moves to `supabase/functions/_shared/availability.ts` and the dashboard's agent uses it, so
      both count every appointment but `cancelled` and `no_show` as taken, as the booking does, and
      drop past times; the SQL `fn_get_available_slots`, which nothing called, is dropped. The
      phone endpoints will use the same resolver. Tried locally: 849 function tests, pgTAP
      164/164, type check clean.
- [x] **B5. The business's currency** (Cronix pull request #31): `settings.currency` (USD, VES,
      EUR, COP or MXN), set by the owner in the dashboard's settings next to the hours; USD when
      absent, as the reports already assume, so no existing business changes until its owner
      chooses; returned with the catalog when a call starts.
- [x] **B6. The dialed number** (Cronix pull request #32): `phone_agent_lines`, each number unique
      and pointing at one business, with row-level security and no policies (the service only);
      lines are added with SQL when a number is bought, no screen yet.
- [ ] **B7. The v1 endpoints** of the contract, the phone line only, with the business always from
      the call record (`phone_agent_calls`) and every request signed by the agent:
  - [x] start of call, availability and end of call (Cronix pull request #32): tried end to end
        against the local Cronix with the function served and invented data;
  - [ ] booking (Cronix pull request #34): `fn_book_appointment_wa` with the caller's number,
        `OUTSIDE_HOURS` and `SLOT_CONFLICT` from the shared resolver, the idempotency key claimed
        before booking (`phone_agent_requests`), and the owner notified after the response
        through WhatsApp's notification pipeline, moved to `_shared` for both channels; tried end
        to end against the local Cronix.
- [ ] **B8. Tests**: pgTAP for the functions and isolation between businesses, `deno test` for the
      endpoints, two bookings of the same time at once.
- [ ] **B9. A pull request in Cronix**, then deployed, after the local tries of Stage D.

## Stage C: the Cronix adapter (agent)

- [x] **C1. The contract updated** with what Stage B decided: currency, the dialed number, the
      conflict code, the client's phone.
- [x] **C2. The caller's phone for the booking**: the phone line passes the caller's number, as
      Cronix finds clients by phone; the practice entry passes a fictitious one per call.
- [x] **C3. The adapter** (`adapters/cronix_scheduling_api/`): HTTP client with the contract's
      timeouts, authentication, the contract's errors translated to the port's.
- [x] **C4. The currency said**: in the business's context and in the price phrase; the practice
      catalog gets one too.
- [x] **C5. Settings** (`SCHEDULING_BACKEND=cronix`, the API's address, its secret as `SecretStr`)
      in `.env.example`; contract tests against recorded responses, negative security tests,
      tenant isolation, the threat model; model evals; one pull request.

## Stage D: calls against the local Cronix, and adjustments

- [x] **D1. The practice entry against the local Cronix**: the page lists the seeded businesses'
      lines; a call books in the local Cronix. The page's lines come from `PRACTICE_LINES`
      (fictitious numbers only) with `SCHEDULING_BACKEND=api`; the seed holds two invented
      businesses, a barbershop in USD and a dental clinic in VES, each with a closed day and an
      appointment already taken.
- [x] **D2. Practice calls**, each read from its transcript, trace and log: a booking, a time taken
      meanwhile, a closed day, a long service near closing, a question about prices. Three calls,
      all booked, no error logged: prices said in each business's currency, and corrected when
      the caller named another; a closed day refused from the business's hours; a two-hour
      service refused when it ends past closing, with the nearest starts offered; a time taken
      by another booking after the availability check, caught when the proposal is checked again
      and answered with the free ranges. Not tried in a call: a time taken between the read-back
      and the caller's yes, which Cronix refuses with `SLOT_CONFLICT` (covered by the adapter's
      and Cronix's tests).
- [x] **D3. Each appointment checked in the local Cronix's database**: there once, with its service,
      day, time, client and the caller's fictitious number; one stored idempotency response per
      booking; each call closed as `booked`; the owner notified.
- [ ] **D4. Adjustments** recorded below; then Cronix's pull request (B9) and its deployment; the
      phone line against Cronix once a Venezuelan number exists.
  - [x] The model misstates a fact the code gave it: told the free starts run from 08:00 to 14:00,
        it said until 13:30. The code now says the free times on entering the choose-time node,
        at most four ranges, the closest to the time asked for, and the model waits for the
        choice; golden case `last-start-of-a-long-service-at-a-dental-clinic`, model evals.
  - [ ] Latency above the 1.0 s p50 target: 1.3 s and 1.7 s median per call, 2.3 to 2.8 s on
        turns with a function call (two model rounds). Speech-to-text took 1.5 to 3.0 s when the
        caller paused mid-sentence. Measured per segment before choosing a change.
  - [x] The time spent in the scheduling API is visible per request: each request of the
        conversation lands in the call's trace (`backend_requests`: operation, start, duration,
        outcome) and in Sentry (a `scheduling.request` span, the `voice.scheduling.request`
        metric). Measured against production's Cronix on 2026-10-29 with 20 signed `calls/start`
        for an unknown line (nothing is written): 1.0 to 1.9 s per request from a development
        machine, of which opening the connection is about 170 ms; Cronix's logs show 194 to
        2,322 ms of execution in the function (median about 1.1 s), the slowest on a newly
        started instance and the fastest on a reused one.
  - [ ] Cronix's `phone-agent-api` takes about a second per request, far above the 300 ms p50
        of a backend read (manifest §6), and each availability check waits on it within a turn.
        Measure where the function spends it (start of a new instance, imports, queries) and
        lighten it in Cronix (B9); the agent's server near Cronix's region (`us-east-1`).

## Open questions

- A reply the caller waited for and then spoke over is recorded nowhere: in the practice call of
  stage A the model streamed nothing for 6.6 s after the caller's thanks, and only the log's
  time to first byte showed it. The trace should record such a wait; decided before Stage D's
  calls.

- A break in a business's hours (closed at midday): not in Cronix today. Adding it is a Cronix
  change in the shared resolver (B4); not part of this connection unless decided.

## Decisions

- 2026-10-28 · Prices are said in the currency each business gives through the contract, never in
  one the model assumes (B5, C4).
- 2026-10-28 · Cronix's data and rules are the source of truth; the agent adopts them and is tried
  against a local Cronix, never production.
- 2026-10-28 · Simultaneous bookings are closed with a lock per business in Cronix's booking
  functions (B3), not with a database rule: it changes no rule of what overlaps, touches no
  existing appointment and leaves the owner's confirmed overlaps alone. The rule per staff member
  stays with Cronix's multi-employee work.
- 2026-10-28 · What has to change in Cronix is tracked here, not in Cronix's own specs, unless the
  change is large.
- 2026-10-28 · Currency in the business's settings, USD when absent (B5); phone lines in their own
  table with a unique number (B6); the v1 endpoints serve the phone line only, WhatsApp's choice of
  business by name waits for Meta's calling (B7); Cronix returns the business's name and the agent
  builds the greeting with its own phrase, no recording for now (the contract changes, C1).
- 2026-10-29 · Deployed to production by the maintainer, each step verified: the migrations of
  B3, B4 and B6, the signing secret in Cronix and in the agent's `.env`
  (`SCHEDULING_API_SIGNING_SECRET`), and the functions `phone-agent-api`, `process-whatsapp`,
  `voice-worker` and `whatsapp-webhook`, which also needed its import map (Cronix pull request
  #33).
- 2026-10-29 · Stored responses of idempotency keys are deleted after 7 days by a daily job in
  Cronix (pull request #35), as the contract says.
