# ADR 0006: Names by function and ports for external systems

*   **Status:** Accepted
*   **Date:** 2026-10-18

## Context
The first version named the package and modules after the project and the systems they talked to, and the domain would have called the Cronix HTTP API directly. That couples the dialog and the pipeline to one backend and one set of vendors, and generic module names hide responsibilities.

## Decision
*   The package is agnostic: `voice_call_agent`. Every module is named after what it does; generic names (`utils`, `helpers`, `manager`, `handler`, …) are banned.
*   The domain depends on ports: `SchedulingBackend` and `BusinessResolver`. "Cronix" appears only in `adapters/cronix_scheduling_api/` and in the composition root that wires it.
*   Vendor factories (Deepgram, language model providers) live in `adapters/`, so the speech pipeline knows no vendor.
*   Architecture tests enforce the naming rules, the "Cronix" boundary and the dependency direction. Constitution §10.

## Alternatives considered
*   **Keep the project-named package and a direct HTTP client in the domain.** Not chosen: it couples the domain to one backend.
*   **Generic helper modules.** Not chosen: unclear ownership, and they grow without bound.

## Consequences
*   Easier: another scheduling backend or destination can be added behind the same ports; tests guard the boundaries automatically.
*   Harder: more modules and one level of indirection. The Cronix adapter must serialize the call's channel for the contract, which needs a recorded INV-8 exemption in phase 1.
