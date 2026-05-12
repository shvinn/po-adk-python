"""
orchestrator — A2A application entry point.

Start the server with:
    uvicorn orchestrator.app:a2a_app --host 0.0.0.0 --port 8003

The agent card is served publicly at:
    GET http://localhost:8003/.well-known/agent-card.json

All other endpoints require an X-API-Key header (see shared/middleware.py).
"""
import os

from a2a.types import AgentSkill
from shared.app_factory import create_a2a_app

from .agent import root_agent

a2a_app = create_a2a_app(
    agent=root_agent,
    name="orchestrator",
    description=(
        "ClinIQ clinical orchestrator. Triages and routes requests to specialist agents: "
        "endocrinologist, cardiologist, neurologist, pharmacist, healthcare FHIR, and general. "
        "The single entry point for all clinical queries."
    ),
    url=os.getenv("ORCHESTRATOR_URL", os.getenv("BASE_URL", "http://localhost:8003")),
    port=8003,
    # The orchestrator supports FHIR context so it can pass credentials through
    # to the healthcare sub-agent.
    fhir_extension_uri=f"{os.getenv('PO_PLATFORM_BASE_URL', 'http://localhost:5139')}/schemas/a2a/v1/fhir-context",
    # Same SMART scopes as healthcare_agent — the orchestrator delegates to it
    # in-process and the credentials flow through shared session state.
    fhir_scopes=[
        {"name": "patient/Patient.rs",           "required": True},
        {"name": "patient/MedicationRequest.rs", "required": True},
        {"name": "patient/Condition.rs",         "required": True},
        {"name": "patient/Observation.cruds",    "required": True},
        {"name": "patient/Encounter.cruds",      "required": True},
    ],
    skills=[
        AgentSkill(
            id="clinical-orchestration",
            name="clinical-orchestration",
            description=(
                "Triages clinical queries and routes to specialist agents: "
                "endocrinologist, cardiologist, neurologist, pharmacist, FHIR data, and general utilities."
            ),
            tags=["clinical", "orchestrator", "routing", "triage"],
        ),
    ],
)
