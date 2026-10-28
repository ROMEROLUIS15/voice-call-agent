# Tasks: from the practice schedule to Cronix

The steps from today's agent, which books against the practice schedule, to calls that book in
Cronix, tried at each step and adjusted. Each step says where it happens, what it delivers and how
it is checked. A box is ticked in the pull request that does it; a decision taken on the way is
written under **Decisions** with its date, and in its ADR when it is one.

Contract: `docs/specs/cronix-phone-api-contract.md`. Manifest: `docs/specs/call-module/manifest.md`.

## Stage A: free times said by ranges (agent)

Today the model receives every free start of the day (one every 15 minutes) and offers one or two.
A caller cannot hear what is left. Cronix already offers only the starts where the service ends
before closing and does not overlap another appointment; the agent says why a requested time does
not work.

- [ ] **A1. Spec.** How the free starts become ranges: consecutive starts at the backend's interval
      form one range, which ends when the service would end after its last start. When the day has
      few starts left, they are said one by one; how few is decided here. Why a requested start
      does not work, from the starts and the service's duration: the service would not fit before
      the next appointment or closing, or the time is taken, or the day is closed.
- [ ] **A2. Code.** The ranges and the reason, computed by the code and said in words
      (`booking_flow/`, `conversation_content/`); the time-choice task offers the ranges nearest to
      what the caller asked for (morning, afternoon, a time).
- [ ] **A3. Tests and golden cases.** Unit tests of the ranges and the reasons; model-level cases
      with invented data: a long service asked for near closing, a caller who wants the morning,
      a day with few starts left.
- [ ] **A4. Evals and a practice call.** Model evals with no regression; one practice call that
      asks for a long service near closing.
- [ ] **A5. Pull request** with README, manifest and golden dataset updated.

## Stage B: the contract's endpoints in Cronix (Cronix repository)

Every change follows the Cronix repository's definition of done (contract §8): migrations,
row-level security with its policies, unique indexes and isolation tests between businesses. The
endpoints derive the business from `call_sid`, never from a request body.

- [ ] **B1. A test environment for Cronix.** Where the agent tries Cronix without touching real
      businesses: a local Supabase stack or a staging project, with seeded businesses of invented
      data (services of several durations, opening hours, a closed day, booked appointments).
- [ ] **B2. Where the endpoints run.** Supabase Edge Functions serve the contract's short
      endpoints; the call itself never runs there (manifest, verified facts). Authentication as the
      contract's §2 says.
- [ ] **B3. Currency per business.** A migration with the business's currency (ISO 4217), its
      policies and isolation tests; returned with the catalog when a call starts.
- [ ] **B4. One availability computation.** The free starts that WhatsApp uses (service duration,
      closing, overlapping appointments), shared by the phone endpoint instead of copied.
- [ ] **B5. The v1 endpoints.** `POST /v1/calls/start`, `POST /v1/calls/{call_sid}/business`,
      `GET /v1/availability`, `POST /v1/appointments` (`SLOT_CONFLICT`, idempotency) and
      `POST /v1/calls/{call_sid}/end`, as the contract describes.
- [ ] **B6. Tests.** Contract tests of each endpoint, isolation between businesses, idempotency of a
      booking, a slot taken between the availability and the booking.
- [ ] **B7. Deployed to the test environment** and a pull request in the Cronix repository.

## Stage C: the Cronix adapter (agent)

- [ ] **C1. Contract updated** with the currency and anything Stage B decided differently.
- [ ] **C2. The adapter** (`adapters/cronix_scheduling_api/`): HTTP client with the contract's
      timeouts (§7), authentication, the contract's errors translated to the port's, the business
      resolved from the dialed number.
- [ ] **C3. The currency said.** The business's currency in its context and in the price phrase, so
      no price is said in a currency the business did not give; the practice catalog gets one too.
- [ ] **C4. Settings.** `SCHEDULING_BACKEND=cronix`, the API's address and its secret as a
      `SecretStr`, documented in `.env.example`.
- [ ] **C5. Tests.** Contract tests against recorded responses, negative security tests, tenant
      isolation, and the threat model with the new destination.
- [ ] **C6. Evals and a pull request** (the prompt changes with the currency).

## Stage D: calls against Cronix, and adjustments

- [ ] **D1. The practice entry against Cronix's test environment.** The practice page lists the
      test businesses' numbers; a call books in Cronix's test environment.
- [ ] **D2. Practice calls**, each read back from its transcript, trace and log: a booking, a slot
      taken meanwhile, a closed day, a long service near closing, a question about prices.
- [ ] **D3. Check in Cronix** that each appointment the agent booked is there, once, with its
      service, day, time and client.
- [ ] **D4. Adjust** what the calls show, each decision recorded below and in its ADR.
- [ ] **D5. The phone line against Cronix** once a Venezuelan number exists (manifest §10).

## Open questions

- A midday break in a business's opening hours: Cronix's hours have one opening and one closing
  per day. Adding a break is a Cronix change that the availability computation and the agent would
  follow; it is decided before B4.

## Decisions

Dated entries, newest last.

- 2026-10-28 · The prices are said in the currency each business gives through the contract, never
  in one the model assumes (Stage B3, C3).
- 2026-10-28 · Stage A goes first: it needs only the agent, and its ranges are what the calls
  against Cronix will be judged by.
