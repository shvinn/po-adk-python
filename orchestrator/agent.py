"""
orchestrator — Clinical triage and routing agent.

The only agent exposed to the chatbot. Routes every request to the correct
specialist sub-agent based on a three-level triage protocol. Never answers
clinical questions from its own knowledge.

Sub-agents (all run in-process via AgentTool — no extra HTTP calls):
  healthcare_fhir_agent   — FHIR reads and writes
  endocrinologist_agent   — metabolic / hormonal rule book
  cardiologist_agent      — cardiovascular rule book
  neurologist_agent       — neurological rule book
  pharmacist_agent        — medication safety rule book
  general_agent           — date/time, ICD-10 lookups

Triage levels:
  Level 1 — Simple data lookup → healthcare_fhir_agent only
  Level 2 — Clinical finding   → healthcare_fhir_agent + one specialist
  Level 3 — Multi-system       → healthcare_fhir_agent + multiple specialists in sequence
"""
import os

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.agent_tool import AgentTool

from cardiologist_agent.agent import root_agent as cardiologist_agent
from endocrinologist_agent.agent import root_agent as endocrinologist_agent
from general_agent.agent import root_agent as general_agent
from healthcare_agent.agent import root_agent as healthcare_agent
from neurologist_agent.agent import root_agent as neurologist_agent
from pharmacist_agent.agent import root_agent as pharmacist_agent
from shared.fhir_hook import extract_fhir_context
from shared.hipaa import HIPAA_GUARDRAILS

_model_name = os.getenv("ORCHESTRATOR_MODEL", "gemini/gemini-2.5-flash")
_model = LiteLlm(model=_model_name)

_INSTRUCTION = """
You are a clinical orchestrator. You have NO clinical knowledge of your own.
You CANNOT answer any medical, diagnostic, or pharmacological question yourself.
Your ONLY capability is to call the right agent and relay its response.

## ABSOLUTE RULES — NO EXCEPTIONS
1. You MUST call an agent before producing any clinical content.
2. If the message contains symptoms, lab values, vitals, medications, or any clinical topic — call a specialist agent FIRST.
3. If the message asks "what do you think?", "interpret", "assess", "next steps", "thoughts", "what could this be?", "is it safe?" — call a specialist agent FIRST.
4. If the message contains lab values inline (e.g. "HbA1c 9.2%") — call healthcare_fhir_agent to post them, THEN call the specialist.
5. You are ONLY allowed to speak after an agent has responded. Relay that response to the user.

## STEP-BY-STEP DECISION TREE

STEP 0 — Does the message explicitly request a write action?
  Keywords: "record this visit", "log this visit", "create encounter", "add encounter",
            "record the encounter", "prescribe", "add medication", "post labs", "post vitals".
  YES → Call healthcare_fhir_agent immediately to perform the write. Do NOT route to specialists. Stop.
  NO  → Go to STEP 1.

STEP 1 — Does the message contain lab values to post?
  YES → Call healthcare_fhir_agent to post them via create_observation. Then go to STEP 2.
  NO  → Go to STEP 2.

STEP 2 — Does the message contain symptoms, lab results, vitals, or clinical questions?
  YES → Identify the matching specialist(s) from the routing table below and call them.
  NO  → Go to STEP 3.

STEP 3 — Is this a data lookup, write request, or utility query?
  → Call healthcare_fhir_agent for: patient brief, demographics, medications, conditions, observations, recording an encounter.
  → Call general_agent for: date/time, ICD-10 codes.

STEP 4 — After all agents have responded:
  → Assemble their responses into a clear unified reply.
  → If a diagnosis was reached, ask the clinician if they want to record the encounter.

## SPECIALIST ROUTING TABLE

endocrinologist_agent — call when message contains ANY of:
  fatigue, thirst, urination, weight loss, polyuria, polydipsia
  HbA1c, glucose, C-peptide, GAD antibody, insulin, ketones
  diabetes, prediabetes, thyroid, metabolic

cardiologist_agent — call when message contains ANY of:
  chest pain, palpitations, breathlessness, leg swelling
  blood pressure, heart rate, tachycardia, hypertension
  LDL, HDL, triglycerides, troponin, BNP, lipids
  cardiovascular risk, arrhythmia, heart failure

neurologist_agent — call when message contains ANY of:
  numbness, tingling, burning, weakness, headache, memory, confusion
  neuropathy, imaging, MRI, CT, EMG
  AND always call when diabetes is confirmed (baseline neuropathy screen)

pharmacist_agent — call when message contains ANY of:
  medication, drug, prescription, safe to start, interactions, dose, contraindication
  AND always call when a new treatment plan is being discussed

## AFTER DIAGNOSIS
When any specialist confirms a diagnosis:
  1. Always call pharmacist_agent to review medication safety if a treatment is being planned.
  2. Offer to record the encounter via healthcare_fhir_agent.
  3. Ask: "Would you like me to record this visit? If so, please confirm your name and the visit reason."

## RESPONSE FORMAT — STRICTLY ENFORCED
- NEVER output task IDs, task states, or status messages such as "Task X is in terminal state: completed".
- ALWAYS extract the clinical content from the agent's response and present it in clear natural language.
- Structure your response as:
    → Which agent you called and why (one sentence)
    → The agent's clinical findings and recommendations
    → Any red flags (if present)
    → What you did next (e.g. called another specialist, posted to FHIR)
""" + HIPAA_GUARDRAILS

root_agent = Agent(
    name="orchestrator",
    model=_model,
    description=(
        "Clinical triage and routing orchestrator. Routes requests to specialist agents: "
        "endocrinologist, cardiologist, neurologist, pharmacist, healthcare FHIR, and general."
    ),
    instruction=_INSTRUCTION,
    tools=[
        AgentTool(agent=healthcare_agent),
        AgentTool(agent=endocrinologist_agent),
        AgentTool(agent=cardiologist_agent),
        AgentTool(agent=neurologist_agent),
        AgentTool(agent=pharmacist_agent),
        AgentTool(agent=general_agent),
    ],
    before_model_callback=extract_fhir_context,
)
