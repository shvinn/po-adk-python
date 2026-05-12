"""
neurologist_agent — A2A application entry point (standalone / testing).

Runs in-process inside the orchestrator via AgentTool.
This app.py exists for standalone testing only.

Start standalone with:
    uvicorn neurologist_agent.app:a2a_app --host 0.0.0.0 --port 8006
"""
import os

from a2a.types import AgentSkill
from shared.app_factory import create_a2a_app

from .agent import root_agent

a2a_app = create_a2a_app(
    agent=root_agent,
    name="neurologist_agent",
    description=(
        "Neurologist specialist agent. Identifies peripheral neuropathy, cognitive decline, "
        "and neurological risk from FHIR observations using a clinical rule book."
    ),
    url=os.getenv("NEUROLOGIST_AGENT_URL", os.getenv("BASE_URL", "http://localhost:8006")),
    port=8006,
    fhir_extension_uri=f"{os.getenv('PO_PLATFORM_BASE_URL', 'http://localhost:5139')}/schemas/a2a/v1/fhir-context",
    fhir_scopes=[
        {"name": "patient/Observation.rs", "required": True},
        {"name": "patient/Condition.rs",   "required": True},
        {"name": "patient/Patient.rs",     "required": True},
    ],
    skills=[
        AgentSkill(
            id="neurology-assessment",
            name="neurology-assessment",
            description="Identifies neuropathy, cognitive impairment, and neurological risk factors.",
            tags=["neurology", "neuropathy", "cognitive", "clinical"],
        ),
    ],
)
