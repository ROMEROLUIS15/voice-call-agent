# 🔌 Contract: Cronix ↔ Voice Call Agent (`phone-agent-api`)

Minimal HTTP surface that Cronix exposes for the phone channel (`phone-agent-api`). It is implemented and documented in the Cronix repository, the source of truth for its data model, its internals and its definition of done; this file is the agent side's copy of the HTTP surface. **Any change is made first on the Cronix side.**

## 0. Agent side

On the agent, this contract is implemented **only** by `src/voice_call_agent/adapters/cronix_scheduling_api/` (phase 1), behind two ports. The domain never sees HTTP, Cronix error codes or wire formats.

| Endpoint | Port method |
|---|---|
| `POST /v1/calls/start` (§4.1) | `BusinessResolver.resolve_call_business` → `BusinessResolved` \| `BusinessChoiceNeeded` \| `UnknownLine` |
| `POST /v1/calls/{call_sid}/business` (§4.1b) | `BusinessResolver.resolve_spoken_business` → `BusinessResolved` \| `NoBusinessMatch` \| `AmbiguousBusiness` |
| `GET /v1/availability` (§4.2) | `SchedulingBackend.availability` → `AvailableSlots` \| `ClosedDay` |
| `GET /v1/my-appointments` (§4.3, v1.1) | `SchedulingBackend.upcoming_appointments` |
| `POST /v1/appointments` (§4.4) | `SchedulingBackend.book_appointment` → `WriteSucceeded` \| `WriteRejected` |
| `POST /v1/appointments/{id}/reschedule` (§4.5, v1.1) | `SchedulingBackend.reschedule_appointment` |
| `POST /v1/appointments/{id}/cancel` (§4.5, v1.1) | `SchedulingBackend.cancel_appointment` |
| `POST /v1/messages` (§4.6, v1.1) | `SchedulingBackend.leave_message` |
| `POST /v1/calls/{call_sid}/end` (§4.7) | `SchedulingBackend.close_call` |

**Tenant boundary:** the adapter sends `call_sid`, never `business_id` (§4); `tests/architecture/test_tenant_boundary.py` fails if a request model or a port method gains a tenant field, and request models reject unknown fields, so a business id proposed by the LLM never reaches a request.

Ports: `scheduling_backend/scheduling_port.py`, `call_session/business_resolution.py`. Models: `scheduling_backend/scheduling_models.py`. Business error codes (`SLOT_CONFLICT`, `IDENTITY_MISMATCH`, …) map to typed results (`WriteRejectionReason`); HTTP failures map to `scheduling_backend/scheduling_errors.py` (§6).

## 1. Principles

*   **Reuse, do not duplicate.** Writes go through the same booking logic and owner notifications as Cronix's WhatsApp channel, so a phone appointment is indistinguishable from a WhatsApp one on the dashboard, in notifications and in reminders. Booking creates the client if missing and checks conflicts atomically; clients are found by phone with the same normalization as WhatsApp.
*   **The agent has no database credentials.** Only a signing secret.
*   **Results** have the shape `{ "success": boolean, "error"?: CODE, ... }`.

## 2. Authentication

*   There is no Cronix user behind a call: authentication is an **HMAC-SHA256 signature** with a shared secret (`PHONE_AGENT_SIGNING_SECRET`).
*   Mandatory headers:
    - `X-Cronix-Timestamp`: Unix seconds. Rejected if it differs from the server clock by more than 300 s.
    - `X-Cronix-Signature`: `hex(HMAC_SHA256(secret, timestamp + "." + METHOD + "." + path + "." + body))`.
*   The signature is compared in constant time. Invalid signature → `401` without a descriptive body.
*   Rate limit per business and per `call_sid`.

## 3. Call record

Cronix keeps a record per call (business, channel, caller phone, whether the identity is verified, outcome) and the stored response of each idempotency key, for 7 days. A dialed number belongs to one business only. The endpoints read the business and the identity from the call record, never from a request body. The tables, row-level security and isolation tests behind it are defined in the Cronix repository (§8).

## 4. Endpoints

All under `/functions/v1/phone-agent-api`. All except `calls/start` receive `call_sid`; the server reads the business from the call record (§3) and does **not** accept it from the body.

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
*   `channel = "twilio"`: the business is the one whose voice line is the dialed number `to`. Errors: `UNKNOWN_LINE`.
*   `channel = "whatsapp"`: the business comes from the WhatsApp routing without slug (the sender's active session, then the client's phone). If it cannot be decided, it answers `{ "success": true, "business": null, "needs_business_choice": true }` and the agent asks for the business (see 4.1b).
*   `known_client` returns **only the first name**, and only when the call's identity is verified (`channel = "whatsapp"`); on the phone line it is `null`, because a spoofed caller ID must not reveal whose number it is (constitution §4).
*   Cronix stores `identity_verified = (channel == "whatsapp")` in the call record; the appointment endpoints (§4.3, §4.5) read it from there, **never** from the request body.

### 4.1b `POST /v1/calls/{call_sid}/business`
Only for WhatsApp without a resolved business. Receives the name the caller said, compares it with the active businesses and, if there is a reliable match, sets the call's `business_id` (once) and returns the same context as 4.1.
```json
{ "spoken_name": "barbería de ana" }
```
Errors: `NO_MATCH`, `AMBIGUOUS` (with up to 3 candidate names for the agent to ask about), `ALREADY_SET`.

### 4.2 `GET /v1/availability?call_sid=…&service_id=…&date=YYYY-MM-DD`
Free slots of that day for that service, in the business's local time, computed with the same logic as WhatsApp.
```json
{ "success": true, "date": "2026-10-22", "slots": ["09:00", "09:30", "15:00"] }
```
Errors: `INVALID_ARGS`, `CLOSED_DAY`.

### 4.3 `GET /v1/my-appointments?call_sid=…` (v1.1)
Future active appointments of the client whose phone matches the call's `from`. If the call is **not** `identity_verified` (phone line), it answers `IDENTITY_REQUIRED` unless the request carries the identity proof of §4.5; the proof is personal data, so it never travels in the URL.
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
*   Books with the call's `from` as the client's phone, through the same booking logic as WhatsApp.
*   A taken slot is answered as `SLOT_CONFLICT`; the endpoint never propagates the free text of the underlying booking logic.
*   Success notifies the owner as a WhatsApp booking does.
```json
{ "success": true, "appointment_id": "uuid" }
```
Errors: `SLOT_CONFLICT`, `INVALID_ARGS`, `OUTSIDE_HOURS`.

### 4.5 `POST /v1/appointments/{id}/reschedule` and `POST /v1/appointments/{id}/cancel` (v1.1)
Mandatory header: `Idempotency-Key`. If the call is **not** `identity_verified` (phone line), the body must include an **identity proof** (constitution §4); on WhatsApp calls it is omitted:
```json
{ "call_sid": "CA…", "new_date": "2026-10-24", "new_time": "10:00",   // reschedule only
  "identity": { "method": "name_and_date", "client_name": "Ana Pérez", "appointment_date": "2026-10-22" } }
```
*   The appointment must belong to the call's business **and** to a client with the same phone as `from`.
*   `name_and_date`: the server compares the normalized name with the client's and the date with the appointment's. Cronix does the comparison, not the agent.
*   `otp` (later phase): `{ "method": "otp", "code": "123456" }` after `POST /v1/otp/send`.
*   Success notifies the owner as on WhatsApp.

Errors: `NOT_FOUND`, `IDENTITY_REQUIRED`, `IDENTITY_MISMATCH`, `SLOT_CONFLICT` (reschedule).
`NOT_FOUND` and `IDENTITY_MISMATCH` do not reveal whether the appointment exists for another client.

### 4.6 `POST /v1/messages` — take a message (v1.1)
When the agent cannot resolve the request (unverified identity, out-of-scope request). Not when Cronix fails: the message would be stored in Cronix (AC-9).
```json
{ "call_sid": "CA…", "caller_name": "Ana", "reason": "Quiere cambiar su cita del jueves", "callback_phone": "+58412…" }
```
Stored as an owner notification; how it is stored is decided on the Cronix side before v1.1.

### 4.7 `POST /v1/calls/{call_sid}/end`
Closes the call record with its outcome (`booked`, `rescheduled`, `cancelled`, `message_taken`, `info_only`, `abandoned`). Latency and cost stay in the agent's call trace (ADR 0009).

## 5. Idempotency

*   Writes require `Idempotency-Key`: the id of the proposal the caller confirmed, a UUID generated when the agent **proposes** the action, not when it executes it (ADR 0011).
*   First time: it is executed and the response is stored (§3).
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

## 8. Changes on the Cronix side

Every change on the Cronix side of this contract follows the Cronix repository's definition of done: migrations, row-level security with its policies, the unique indexes this contract relies on and isolation tests between businesses, in the same change. Whatever that repository decides, the endpoints derive the business from `call_sid`, never from a request body.
