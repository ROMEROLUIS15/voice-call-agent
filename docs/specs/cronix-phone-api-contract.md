# 🔌 Contract: Cronix ↔ Voice Call Agent (`phone-agent-api`)

Minimal HTTP surface that Cronix exposes for the phone channel. It lives in the Cronix repository as a new Edge Function (`supabase/functions/phone-agent-api/`) and is documented there in its own `manifest.md`; this file is the agent side's reference copy. **Any change is made first in the Cronix manifest.**

## 0. Agent side

On the agent, this contract is implemented **only** by `src/voice_call_agent/adapters/cronix_scheduling_api/` (phase 1), behind two ports. The domain never sees HTTP, Cronix error codes or wire formats.

| Endpoint | Port method |
|---|---|
| `POST /v1/calls/start` (§4.1) | `BusinessResolver.resolve_call_business` → `BusinessResolved` \| `BusinessChoiceNeeded` \| `UnknownLine` |
| `POST /v1/calls/{call_sid}/business` (§4.1b) | `BusinessResolver.resolve_spoken_business` → `BusinessResolved` \| `NoBusinessMatch` \| `AmbiguousBusiness` |
| `GET /v1/availability` (§4.2) | `SchedulingBackend.availability` → `AvailableSlots` \| `ClosedDay` |
| `GET /v1/my-appointments` (§4.3) | `SchedulingBackend.upcoming_appointments` |
| `POST /v1/appointments` (§4.4) | `SchedulingBackend.book_appointment` → `WriteSucceeded` \| `WriteRejected` |
| `POST /v1/appointments/{id}/reschedule` (§4.5) | `SchedulingBackend.reschedule_appointment` |
| `POST /v1/appointments/{id}/cancel` (§4.5) | `SchedulingBackend.cancel_appointment` |
| `POST /v1/messages` (§4.6) | `SchedulingBackend.leave_message` |
| `POST /v1/calls/{call_sid}/end` (§4.7) | `SchedulingBackend.close_call` |

Ports: `scheduling_backend/scheduling_port.py`, `call_session/business_resolution.py`. Models: `scheduling_backend/scheduling_models.py`. Business error codes (`SLOT_CONFLICT`, `IDENTITY_MISMATCH`, …) map to typed results (`WriteRejectionReason`); HTTP failures map to `scheduling_backend/scheduling_errors.py` (§6).

## 1. Principles

*   **Reuse, do not duplicate.** Writes use the same RPCs and events as WhatsApp, so a phone appointment is indistinguishable from a WhatsApp one on the dashboard, in notifications and in reminders:
    - book → `fn_book_appointment_wa` (creates the client if missing and checks conflicts atomically);
    - reschedule → `fn_reschedule_appointment_wa`;
    - cancel → update to `cancelled` scoped by `business_id`, like `cancelAppointmentById`;
    - owner notifications → `emitCreatedEvent`, `emitRescheduledEvent`, `emitCancelledEvent`;
    - client by phone → `fn_find_client_by_phone` (same normalization as WhatsApp).
*   **The agent has no database credentials.** Only a signing secret.
*   **Results follow the Cronix Edge Function pattern:** `{ "success": boolean, "error"?: CODE, ... }`.

## 2. Authentication

*   `verify_jwt = false` in `config.toml` (there is no Cronix user behind a call); authentication is an **HMAC-SHA256 signature** with a shared secret (`PHONE_AGENT_SIGNING_SECRET`).
*   Mandatory headers:
    - `X-Cronix-Timestamp`: Unix seconds. Rejected if it differs from the server clock by more than 300 s.
    - `X-Cronix-Signature`: `hex(HMAC_SHA256(secret, timestamp + "." + METHOD + "." + path + "." + body))`.
*   The signature is compared in constant time. Invalid signature → `401` without a descriptive body.
*   Rate limit per `business_id` and per `call_sid` (reusing Cronix's Redis rate limiter).

## 3. New data model in Cronix

| Table | Key columns | Purpose |
|---|---|---|
| `voice_lines` | `phone_e164` **unique**, `business_id`, `active`, `greeting`, `recording_enabled` | Dialed number → business. A number belongs to one business only. |
| `phone_calls` | `call_sid` PK, `channel`, `business_id` (null until resolved on WhatsApp), `from_phone`, `identity_verified`, `started_at`, `ended_at`, `outcome` | Call record; anchors the `business_id` and the identity verification for the following requests. |
| `phone_idempotency` | `key` PK, `business_id`, `response jsonb`, `created_at` | Stored response per idempotency key (retention: 7 days). |

*   RLS enabled; access only with `service_role` from the Edge Function. Owners can **read** `voice_lines` and `phone_calls` of their business through `current_business_id()`.
*   Covered with pgTAP: isolation between businesses and uniqueness of `phone_e164`.

## 4. Endpoints

All under `/functions/v1/phone-agent-api`. All except `calls/start` receive `call_sid`; the server reads the `business_id` from `phone_calls` and does **not** accept it from the body.

### 4.1 `POST /v1/calls/start`
Resolves the business and returns the call context. `call_sid` is the call's identifier in its channel (Twilio `CallSid` or Meta's `call_id`).

```json
// request
{ "call_sid": "CA…", "channel": "twilio" | "whatsapp",
  "to": "+13055550100", "from": "+584121234567" }

// response
{
  "success": true,
  "business": { "name": "Barbería Ana", "timezone": "America/Caracas",
                "greeting": "Gracias por llamar a Barbería Ana…", "recording_enabled": false },
  "services": [ { "id": "uuid", "name": "Corte de cabello", "duration_min": 30, "price": 10 } ],
  "working_hours": { "mon": ["09:00", "18:00"], "sun": null },
  "known_client": { "first_name": "Ana" }   // or null
}
```
*   `channel = "twilio"`: the business comes from `voice_lines` by `to`. Errors: `UNKNOWN_LINE`.
*   `channel = "whatsapp"`: the business comes from the WhatsApp routing without slug (session in `wa_sessions`, then the client's phone). If it cannot be decided, it answers `{ "success": true, "business": null, "needs_business_choice": true }` and the agent asks for the business (see 4.1b).
*   `known_client` returns **only the first name**: the agent needs nothing more to greet.
*   Cronix stores `identity_verified = (channel == "whatsapp")` in `phone_calls`; the reschedule and cancel endpoints read it from there, **never** from the request body.

### 4.1b `POST /v1/calls/{call_sid}/business`
Only for WhatsApp without a resolved business. Receives the name the caller said, compares it with the active businesses and, if there is a reliable match, sets the call's `business_id` (once) and returns the same context as 4.1.
```json
{ "spoken_name": "barbería de ana" }
```
Errors: `NO_MATCH`, `AMBIGUOUS` (with up to 3 candidate names for the agent to ask about), `ALREADY_SET`.

### 4.2 `GET /v1/availability?call_sid=…&service_id=…&date=YYYY-MM-DD`
Free slots of that day for that service, in the business's local time, computed with the same logic as WhatsApp (`computeAvailableSlots`).
```json
{ "success": true, "date": "2026-10-22", "slots": ["09:00", "09:30", "15:00"] }
```
Errors: `INVALID_ARGS`, `CLOSED_DAY`.

### 4.3 `GET /v1/my-appointments?call_sid=…`
Future active appointments of the client whose phone matches the call's `from`.
```json
{ "success": true, "appointments": [ { "id": "uuid", "service": "Corte de cabello",
  "date": "2026-10-22", "time": "15:00" } ] }
```
It does not include the client's full name nor data of other clients.

### 4.4 `POST /v1/appointments` — book
Mandatory header: `Idempotency-Key`.
```json
{ "call_sid": "CA…", "service_id": "uuid", "date": "2026-10-22", "time": "15:00",
  "client_name": "Ana Pérez" }
```
*   Calls `fn_book_appointment_wa` with the call's `from` as the client's phone.
*   If the RPC answers `success: false` because the slot is taken, the endpoint translates it to `SLOT_CONFLICT` (today the RPC returns free text, "Slot no disponible."; the endpoint must not propagate that text).
*   Success → `emitCreatedEvent` (owner notification, bell and push, as on WhatsApp).
```json
{ "success": true, "appointment_id": "uuid" }
```
Errors: `SLOT_CONFLICT`, `INVALID_ARGS`, `OUTSIDE_HOURS`.

### 4.5 `POST /v1/appointments/{id}/reschedule` and `POST /v1/appointments/{id}/cancel`
Mandatory header: `Idempotency-Key`. If the call is **not** `identity_verified` (phone line), the body must include an **identity proof** (constitution §4); on WhatsApp calls it is omitted:
```json
{ "call_sid": "CA…", "new_date": "2026-10-24", "new_time": "10:00",   // reschedule only
  "identity": { "method": "name_and_date", "client_name": "Ana Pérez", "appointment_date": "2026-10-22" } }
```
*   The appointment must belong to the call's business **and** to a client with the same phone as `from`.
*   `name_and_date`: the server compares the normalized name with the client's and the date with the appointment's. Cronix does the comparison, not the agent.
*   `otp` (later phase): `{ "method": "otp", "code": "123456" }` after `POST /v1/otp/send`.
*   Success → `emitRescheduledEvent` / `emitCancelledEvent`.

Errors: `NOT_FOUND`, `IDENTITY_REQUIRED`, `IDENTITY_MISMATCH`, `SLOT_CONFLICT` (reschedule).
`NOT_FOUND` and `IDENTITY_MISMATCH` do not reveal whether the appointment exists for another client.

### 4.6 `POST /v1/messages` — take a message
When the agent cannot resolve the request (unverified identity, Cronix error, out-of-scope request).
```json
{ "call_sid": "CA…", "caller_name": "Ana", "reason": "Quiere cambiar su cita del jueves", "callback_phone": "+58412…" }
```
Stored as an owner notification reusing Cronix's notification channel (new type `phone_message`). **Decision pending:** dedicated table vs. reusing `notifications`.

### 4.7 `POST /v1/calls/{call_sid}/end`
Closes the call record with its outcome (`booked`, `rescheduled`, `cancelled`, `message_taken`, `info_only`, `abandoned`) and the aggregated latency metrics. Feeds Cronix's observability dashboard.

## 5. Idempotency

*   Writes require `Idempotency-Key` (a UUID generated by the agent when it **proposes** the action, not when it executes it).
*   First time: it is executed and the response is stored in `phone_idempotency`.
*   Same key again: the stored response is returned without executing again.
*   Same key with a different body: `409 IDEMPOTENCY_MISMATCH`.

## 6. Errors and HTTP codes

| Situation | HTTP | Body | Agent side |
|---|---|---|---|
| Business outcome (conflict, not found, identity) | 200 | `{ "success": false, "error": CODE }` | Typed result (`WriteRejected`, resolution results) |
| Invalid or expired signature | 401 | empty | `SchedulingBackendRejectedRequestError` |
| Rate limit | 429 | `Retry-After` | Retried once, then `SchedulingBackendUnavailableError` |
| Transient error (database, dependency) | 503 | `Retry-After` | Retried once, then `SchedulingBackendUnavailableError` |
| Same idempotency key, different body | 409 | `IDEMPOTENCY_MISMATCH` | `IdempotencyKeyReusedError` |
| Non-recoverable logic error | 500 | captured in Sentry; the agent does **not** retry | `SchedulingBackendRejectedRequestError` |

The agent retries **only** `429` and `503`, with the same `Idempotency-Key`, and at most once within the call (the caller is waiting).

## 7. Agent-side timeouts

*   Reads: 1.5 s. Writes: 3 s. Configured in the adapter's settings (phase 1).
*   If a write times out, the agent assumes **neither** success nor failure: it calls `GET /v1/my-appointments` to check the real state before saying anything.
