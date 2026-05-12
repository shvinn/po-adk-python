"""
healthcare_agent — Agent definition.

This agent has read-only access to a patient's FHIR R4 record.
FHIR credentials (server URL, bearer token, patient ID) are injected via the
A2A message metadata by the caller (e.g. Prompt Opinion) and extracted into
session state by extract_fhir_context before every LLM call.

To customise:
  • Change model, description, and instruction below.
  • Add or remove tools from the tools=[...] list.
  • Add new FHIR tools in shared/tools/fhir.py and export from shared/tools/__init__.py.
  • Add non-FHIR tools in shared/tools/ or locally in a tools/ folder here.
"""
import os

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from shared.fhir_hook import extract_fhir_context
from shared.hipaa import HIPAA_GUARDRAILS
from shared.tools import (
    create_encounter,
    create_medication,
    create_observation,
    get_active_conditions,
    get_active_medications,
    get_patient_demographics,
    get_observations,
)

# ── Model selection ────────────────────────────────────────────────────────────
# Set HEALTHCARE_AGENT_MODEL in your .env to switch models.
#
# All models are handled via LiteLLM. Use the appropriate prefix:
#   HEALTHCARE_AGENT_MODEL=gemini/gemini-2.5-flash   (Google AI Studio, default)
#   HEALTHCARE_AGENT_MODEL=openai/gpt-4o
#   HEALTHCARE_AGENT_MODEL=anthropic/claude-sonnet-4-6
#   HEALTHCARE_AGENT_MODEL=vertex_ai/gemini-2.5-flash
# ──────────────────────────────────────────────────────────────────────────────
_model_name = os.getenv("HEALTHCARE_AGENT_MODEL", "gemini/gemini-2.5-flash")
_model = LiteLlm(model=_model_name)

root_agent = Agent(
    name="healthcare_fhir_agent",
    model=_model,
    description=(
        "A clinical assistant that queries a patient's FHIR health record "
        "to answer questions about demographics, medications, conditions, and observations."
    ),
    instruction=(
        "You are a clinical data assistant with access to a patient's FHIR health record. "
        "Use the available tools to retrieve and write data to the connected FHIR server. "
        "Always use tools — never make up or guess clinical information. "
        "Present medical information clearly and concisely, as if briefing a clinician. "
        "When asked to create, add, or record anything — such as an encounter or visit — always call the appropriate write tool directly without asking for confirmation. "
        "If a tool returns an error, explain what went wrong and suggest how to resolve it. "
        "If FHIR context is not available, let the caller know they need to include it in their request."
        + HIPAA_GUARDRAILS
    ),
    tools=[
        get_patient_demographics,
        get_active_medications,
        get_active_conditions,
        get_observations,
        create_encounter,
        create_medication,
        create_observation,
    ],
    # Runs before every LLM call.
    # Reads fhir_url, fhir_token, and patient_id from A2A message metadata
    # and writes them into session state so tools can call the FHIR server.
    before_model_callback=extract_fhir_context,
)
