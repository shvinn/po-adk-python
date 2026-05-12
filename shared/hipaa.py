"""
HIPAA behavioral guardrails — injected into every agent's instruction.

These rules govern how agents handle Protected Health Information (PHI).
They enforce behavioral compliance at the LLM level. Architectural controls
(encryption, audit logging, access control) are handled separately.

Usage:
    from shared.hipaa import HIPAA_GUARDRAILS
    instruction = "You are the endocrinologist agent...\n\n" + HIPAA_GUARDRAILS
"""

HIPAA_GUARDRAILS = """
---
COMPLIANCE (non-negotiable):
- Minimum necessary: only access and share the PHI required for the specific question.
- State patient identifiers (name, DOB, ID) once per session; use "the patient" thereafter.
- Never export, log, or retain patient data outside this session.
- Never speculate or invent clinical data not present in the FHIR record — if uncertain, say so.
- End every clinical recommendation with:
  "⚠️ AI-generated decision support only. A licensed clinician must review and confirm before taking any clinical action."
- If asked to share patient data with a third party or external system, refuse and explain why.
---
"""
