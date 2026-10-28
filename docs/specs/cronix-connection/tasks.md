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
- **One calendar per business**: any appointment of the business blocks the time, whoever it is
  assigned to (`appointments.assigned_user_id` is not used for availability).
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
- **The overlap check is not atomic**: it reads, then inserts, with no lock, exclusion constraint
  or unique index on appointments. Two bookings at the same moment can both succeed.
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

- [ ] **A1. The practice schedule follows Cronix**: starts every 30 minutes, the service ending
      by closing, one calendar per business, hours as `[open, close]` per weekday, past times
      dropped.
- [ ] **A2. Free times by ranges.** Consecutive starts form a range that ends when the service
      would end after its last start; when few starts are left, they are said one by one (how few
      is decided here). The time-choice task offers the ranges nearest to what the caller asked
      for (morning, afternoon, a time).
- [ ] **A3. Why a time does not work**, from the starts and the service's duration: the service
      would not end before the next appointment or closing, the time is taken, or the day is
      closed.
- [ ] **A4. Tests, golden cases with invented data, model evals and a practice call**; one pull
      request with README, manifest and golden dataset.

## Stage B: the contract's endpoints in Cronix (Cronix repository)

Through Cronix's SDD gate: the phone endpoints are an area without a spec, declared and specified
in Cronix first.

- [ ] **B1. A local Cronix**: Docker, `npx supabase db reset`, and a seed of invented businesses
      (services of several durations, hours with a closed day, booked appointments). Never the
      production project.
- [ ] **B2. The spec in Cronix**: a module for the phone endpoints, with the contract's
      invariants, errors and isolation, read against `modulo-whatsapp-citas` and `modulo-citas-core`.
- [ ] **B3. Bookings that cannot overlap**: the database refuses two overlapping appointments of a
      business (an exclusion constraint or a lock per business), for every channel; the conflict
      answered as a code, not free text. A safety fix that does not wait for the phone line.
- [ ] **B4. One computation of free starts**, the one the booking also applies (statuses, past
      times, opening hours, hours never set), used by WhatsApp, the dashboard's agent and the phone
      endpoints.
- [ ] **B5. The business's currency**, set by the owner with the hours, stored and returned with
      the catalog.
- [ ] **B6. The dialed number**: how a phone line's number reaches its business (a setting like
      WhatsApp's `wa_phone_number_id`).
- [ ] **B7. The v1 endpoints** of the contract, thin over the functions above, with the business
      always from `call_sid`: start of call, business, availability, booking, end of call.
- [ ] **B8. Tests**: pgTAP for the functions and isolation between businesses, `deno test` for the
      endpoints, two bookings of the same time at once.
- [ ] **B9. A pull request in Cronix**, then deployed, after the local tries of Stage D.

## Stage C: the Cronix adapter (agent)

- [ ] **C1. The contract updated** with what Stage B decided: currency, the dialed number, the
      conflict code, the client's phone.
- [ ] **C2. The caller's phone for the booking**: the phone line passes the caller's number, as
      Cronix finds clients by phone; the practice entry passes a fictitious one per call.
- [ ] **C3. The adapter** (`adapters/cronix_scheduling_api/`): HTTP client with the contract's
      timeouts, authentication, the contract's errors translated to the port's.
- [ ] **C4. The currency said**: in the business's context and in the price phrase; the practice
      catalog gets one too.
- [ ] **C5. Settings** (`SCHEDULING_BACKEND=cronix`, the API's address, its secret as `SecretStr`)
      in `.env.example`; contract tests against recorded responses, negative security tests,
      tenant isolation, the threat model; model evals; one pull request.

## Stage D: calls against the local Cronix, and adjustments

- [ ] **D1. The practice entry against the local Cronix**: the page lists the seeded businesses'
      lines; a call books in the local Cronix.
- [ ] **D2. Practice calls**, each read from its transcript, trace and log: a booking, a time taken
      meanwhile, a closed day, a long service near closing, a question about prices.
- [ ] **D3. Each appointment checked in the local Cronix's dashboard**: there once, with its service,
      day, time and client.
- [ ] **D4. Adjustments** recorded below; then Cronix's pull request (B9) and its deployment; the
      phone line against Cronix once a Venezuelan number exists.

## Open questions

- A break in a business's hours (closed at midday): not in Cronix today. Adding it is a Cronix
  change that B4's computation would follow; decided before B4.

## Decisions

- 2026-10-28 · Prices are said in the currency each business gives through the contract, never in
  one the model assumes (B5, C4).
- 2026-10-28 · Cronix's data and rules are the source of truth; the agent adopts them and is tried
  against a local Cronix, never production.
