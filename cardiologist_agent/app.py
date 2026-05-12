"""
cardiologist_agent — A2A application entry point (standalone / testing).

Runs in-process inside the orchestrator via AgentTool.
This app.py exists for standalone testing only.

Start standalone with:
    uvicorn cardiologist_agent.app:a2a_app --host 0.0.0.0 --port 8005
"""
import os

from a2a.types import AgentSkill
from shared.app_factory import create_a2a_app

from .agent import root_agent

a2a_app = create_a2a_app(
    agent=root_agent,
    name="cardiologist_agent",
    description=(
        "Cardiologist specialist agent. Interprets blood pressure, heart rate, lipid panels, "
        "and cardiovascular risk using a clinical rule book."
    ),
    url=os.getenv("CARDIOLOGIST_AGENT_URL", os.getenv("BASE_URL", "http://localhost:8005")),
    port=8005,
    fhir_extension_uri=f"{os.getenv('PO_PLATFORM_BASE_URL', 'http://localhost:5139')}/schemas/a2a/v1/fhir-context",
    fhir_scopes=[
        {"name": "patient/Observation.rs", "required": True},
        {"name": "patient/Condition.rs",   "required": True},
        {"name": "patient/Patient.rs",     "required": True},
    ],
    skills=[
        AgentSkill(
            id="cardiology-assessment",
            name="cardiology-assessment",
            description="Interprets cardiovascular vitals, lipid panels, and calculates cardiovascular risk.",
            tags=["cardiology", "hypertension", "lipids", "clinical"],
        ),
    ],
)
