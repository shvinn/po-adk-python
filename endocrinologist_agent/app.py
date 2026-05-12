"""
endocrinologist_agent — A2A application entry point (standalone / testing).

This agent runs in-process inside the orchestrator via AgentTool.
This app.py exists for standalone testing only — it is not included in
docker-compose or the Procfile.

Start standalone with:
    uvicorn endocrinologist_agent.app:a2a_app --host 0.0.0.0 --port 8004
"""
import os

from a2a.types import AgentSkill
from shared.app_factory import create_a2a_app

from .agent import root_agent

a2a_app = create_a2a_app(
    agent=root_agent,
    name="endocrinologist_agent",
    description=(
        "Endocrinologist specialist agent. Interprets glucose, HbA1c, C-peptide, "
        "thyroid, and hormonal lab results using a clinical rule book."
    ),
    url=os.getenv("ENDOCRINOLOGIST_AGENT_URL", os.getenv("BASE_URL", "http://localhost:8004")),
    port=8004,
    fhir_extension_uri=f"{os.getenv('PO_PLATFORM_BASE_URL', 'http://localhost:5139')}/schemas/a2a/v1/fhir-context",
    fhir_scopes=[
        {"name": "patient/Observation.rs", "required": True},
        {"name": "patient/Condition.rs",   "required": True},
        {"name": "patient/Patient.rs",     "required": True},
    ],
    skills=[
        AgentSkill(
            id="endocrinology-assessment",
            name="endocrinology-assessment",
            description="Interprets metabolic and hormonal lab results for diabetes and thyroid conditions.",
            tags=["endocrinology", "diabetes", "thyroid", "clinical"],
        ),
    ],
)
