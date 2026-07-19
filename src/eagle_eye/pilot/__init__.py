"""Eagle Eye Zenith V6 — PILOT FORGE: the operational pilot spine.

This package is the V6 layer that turns the verified synthetic system into a
locally deployable, pilot-grade reference implementation. It builds the
missing operational spine — durable storage, identity, key custody, process-
isolated evaluation, authorized ingestion, the shadow-execution lifecycle,
observability, and operator commands — WITHOUT claiming any production
capability that has not been mechanically or synthetically verified here.

CLAIM DISCIPLINE (unchanged from V5, enforced in receipts):
  - Everything in this package is a LOCAL PILOT REFERENCE IMPLEMENTATION.
  - Local SQLite storage is NOT production infrastructure.
  - The local development issuer is NOT a production identity provider.
  - Local key providers are NOT a production KMS.
  - Process isolation is MECHANICALLY VERIFIED process isolation, NOT
    organizational isolation.
  - External execution stays disabled and fail-closed.

The product loop this package implements:
  AUTHORIZED INGEST -> TENANT-BOUND IDENTITY -> DURABLE EVIDENCE -> DECISION
  -> HUMAN REQUEST -> INDEPENDENT APPROVAL -> SHADOW EXECUTION
  -> OUTCOME CAPTURE -> REPLAY -> EXPORTABLE AUDIT RECEIPT
"""

PILOT_SPEC = "eagle-eye-pilot/6.0"
