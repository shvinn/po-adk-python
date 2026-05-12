# ClinIQ — AI-Powered Clinical Decision Support
## Agents Assemble Hackathon Submission

---

## Overview

ClinIQ is a multi-agent clinical decision support system built on Google ADK and the A2A protocol, integrated with the Prompt Opinion (PO) healthcare platform. It guides a doctor from a patient's first symptom presentation through to a confirmed diagnosis — using real FHIR patient data at every step.

A team of specialist AI agents — each with a clinical rule book — collaborate to diagnose a patient, check medication safety, and write the encounter back to FHIR.

---

## The Problem

Doctors spend an average of 20+ minutes reviewing patient charts before making decisions. Critical patterns across visits, labs, and conditions are easy to miss. ClinIQ solves this by deploying a team of AI specialist agents that read the entire FHIR record, reason across it, and surface actionable clinical insights in seconds.

---

## The Solution

```
Doctor (via Prompt Opinion)
        │
        ▼
   Orchestrator (Triage + Routing)
   ├── Fetches patient data
   ├── Routes to specialist agents based on symptoms/labs
   ├── Assembles unified clinical response
   └── Records encounters and lab results back to FHIR
        │
        ├── healthcare_fhir_agent   (FHIR reads + writes)
        ├── endocrinologist_agent   (metabolic / hormonal rule book)
        ├── cardiologist_agent      (cardiovascular rule book)
        ├── neurologist_agent       (neurological rule book)
        ├── pharmacist_agent        (medication safety rule book)
        └── general_agent           (date/time, ICD-10 lookups)
```

---

## Agent Roles

### Orchestrator
- Single entry point — the only agent the chatbot talks to
- Three-level triage protocol: simple lookup → specialist → multi-specialist
- Routes based on explicit symptom/lab keyword matching
- Never answers clinical questions from its own knowledge
- Assembles all specialist outputs into a unified response
- Automatically triggers pharmacist review when a new treatment is planned
- Offers to record the encounter after diagnosis is confirmed

### healthcare_fhir_agent
- All FHIR reads and writes — pure data layer, no clinical reasoning
- Tools: `get_patient_demographics`, `get_active_medications`, `get_active_conditions`, `get_observations`, `get_encounters`, `create_observation`, `create_encounter`

### endocrinologist_agent
- Rule book: HbA1c thresholds, fasting glucose, Type 1 vs Type 2 differentiation (C-peptide, GAD antibody), pediatric considerations, thyroid function, DKA red flags
- Tools: `get_observations`, `get_active_conditions`, `get_patient_demographics`

### cardiologist_agent
- Rule book: Blood pressure classification (adult + pediatric), heart rate, lipid panel, cardiovascular risk scoring, arrhythmia indicators
- Tools: `get_observations`, `get_active_conditions`, `get_patient_demographics`

### neurologist_agent
- Rule book: Peripheral neuropathy screening, autonomic neuropathy, cognitive impairment thresholds, imaging interpretation, diabetes-related screening schedule, neurological red flags
- Tools: `get_observations`, `get_active_conditions`, `get_patient_demographics`, `get_encounters`

### pharmacist_agent
- Rule book: Drug-drug interactions, renal/hepatic dosing adjustments, contraindications by condition, pediatric weight-based dosing, new treatment safety checks
- Tools: `get_active_medications`, `get_active_conditions`, `get_patient_demographics`, `get_observations`

### general_agent
- Stateless utility — no FHIR, no clinical reasoning
- Tools: `get_current_datetime`, `look_up_icd10`

---

## FHIR Tools

| Tool | Resource | Direction |
|---|---|---|
| `get_patient_demographics` | Patient | Read |
| `get_active_medications` | MedicationRequest | Read |
| `get_active_conditions` | Condition | Read |
| `get_observations` | Observation | Read |
| `get_encounters` | Encounter | Read |
| `create_observation` | Observation | Write |
| `create_encounter` | Encounter | Write |

### LOINC Codes Supported (create_observation)
| Lab | LOINC |
|---|---|
| HbA1c | 4548-4 |
| Fasting glucose | 1558-6 |
| C-peptide | 1986-9 |
| GAD antibody | 56695-0 |
| LDL | 2089-1 |
| HDL | 2085-9 |
| Triglycerides | 2571-8 |
| Creatinine | 2160-0 |
| Potassium | 2823-3 |
| TSH | 3016-3 |
| BNP | 42637-9 |
| Troponin | 6598-7 |
| eGFR | 62238-1 |
| Hemoglobin | 718-7 |

---

## Clinical Workflow (Demo Scenario)

### Conversation 1 — First Visit: Symptom Presentation
> "@orchestrator Start a new visit for this patient and give me a brief."

Orchestrator → `healthcare_fhir_agent` → patient demographics + active conditions + recent vitals

> "@orchestrator The patient is complaining of persistent fatigue, frequent urination especially at night, excessive thirst throughout the day, and unintentional weight loss of approximately 8 pounds over the last 6 weeks. No prior diabetes diagnosis. What are your thoughts and what labs should we order?"

Orchestrator → `endocrinologist_agent` → recognises classic triad → orders HbA1c, fasting glucose, C-peptide, GAD antibody, urinalysis

> "@orchestrator Record this visit. I am Dr. Smith. Reason for visit is new patient presentation with symptoms of polyuria, polydipsia, fatigue, and unexplained weight loss."

Orchestrator → `healthcare_fhir_agent` → `create_encounter` ✅

---

### Conversation 2 — Second Visit: Lab Results
> "@orchestrator Post lab results: HbA1c 9.2%, fasting glucose 280 mg/dL, C-peptide 0.4 ng/mL."

Orchestrator → `healthcare_fhir_agent` → `create_observation` × 3 ✅

> "@orchestrator Interpret the lab results and give me a full clinical assessment."

Orchestrator → `endocrinologist_agent` → reads posted labs via `get_observations` → HbA1c 9.2% confirms diabetes, C-peptide 0.4 ng/mL low → Type 1 suspected → recommend GAD antibody

> "@orchestrator Is it safe to start this patient on insulin given their current condition and medical history?"

Orchestrator → `pharmacist_agent` → no current medications, no contraindications → safe to proceed

> "@orchestrator Record this visit. I am Dr. Smith. Reason is review of lab results and initial diabetes management planning."

Orchestrator → `healthcare_fhir_agent` → `create_encounter` ✅

---

### Conversation 3 — Third Visit: Multi-Specialist Review
> "@orchestrator The patient is back for follow-up. They have been diagnosed with Type 1 Diabetes Mellitus. Give me a full multi-specialty assessment — I want cardiology, neurology, and pharmacy all reviewed today."

Orchestrator → Level 3 triage → consults in sequence:
- `cardiologist_agent` → cardiovascular risk elevated with new diabetes diagnosis
- `neurologist_agent` → baseline neuropathy screen triggered
- `pharmacist_agent` → reviews insulin initiation safety

> "@orchestrator The patient mentioned some occasional numbness and tingling in their feet over the past few weeks."

Orchestrator → `neurologist_agent` → peripheral neuropathy indicators flagged

> "@orchestrator Post vitals: blood pressure 138/86 mmHg, heart rate 102 bpm. Have the cardiologist assess."

Orchestrator → `healthcare_fhir_agent` → posts vitals → `cardiologist_agent` → Stage 1 hypertension + tachycardia noted

> "@orchestrator Record this visit. I am Dr. Smith. Reason is follow-up for Type 1 Diabetes Mellitus, peripheral neuropathy screening, and cardiovascular risk assessment."

Orchestrator → `healthcare_fhir_agent` → `create_encounter` ✅

---

## Technical Architecture

### Stack
- **Framework:** Google ADK (Agent Development Kit)
- **Protocol:** A2A v1
- **LLM:** Gemini 2.5 Flash via LiteLLM (swappable to GPT-4o, Claude, Vertex)
- **Platform:** Prompt Opinion
- **Data:** FHIR R4

### Agent Communication
- All specialist agents run **in-process** via ADK `AgentTool` — zero HTTP latency between agents
- FHIR credentials extracted once by orchestrator's `before_model_callback`, shared across all specialist agents via session state
- Credentials never appear in prompts

### Security
- X-API-Key authentication on all external endpoints
- FHIR credentials travel in A2A message metadata, never in prompt text
- HIPAA behavioral guardrails injected into every agent's instruction from `shared/hipaa.py`
- Minimum necessary PHI principle enforced via agent instructions
- Every clinical output carries: *"⚠️ AI-generated decision support only. A licensed clinician must review and confirm before taking any clinical action."*

### Multi-turn Conversation Fix
- Prompt Opinion reuses task IDs across conversation turns
- Fixed in `shared/middleware.py`: strips `taskId` from `message/send` params so each turn creates a fresh A2A task while preserving `contextId` for FHIR session continuity

---

## Project Structure

```
po-adk-python/
├── orchestrator/               # Triage + routing agent (entry point)
├── healthcare_agent/           # FHIR reads + writes
├── endocrinologist_agent/      # Metabolic / hormonal rule book
├── cardiologist_agent/         # Cardiovascular rule book
├── neurologist_agent/          # Neurological rule book
├── pharmacist_agent/           # Medication safety rule book
├── general_agent/              # Date/time, ICD-10 lookups
└── shared/
    ├── tools/fhir.py           # All FHIR read/write tools + LOINC table
    ├── hipaa.py                # HIPAA guardrails (injected into all agents)
    ├── fhir_hook.py            # FHIR credential extraction callback
    ├── middleware.py           # API key auth + PO compatibility + task ID fix
    └── app_factory.py          # A2A agent card factory
```

---

## Key Differentiators

1. **Real bidirectional FHIR** — reads history AND writes lab results + encounters back
2. **Specialist rule books** — each agent applies clinical thresholds, not just LLM guessing
3. **Proactive triage** — orchestrator routes automatically based on symptom/lab keywords
4. **HIPAA-aware by design** — guardrails in every agent, credentials never in prompts
5. **In-process agents** — zero latency between specialist consultations
6. **Multi-turn conversation** — fixed A2A task reuse issue for natural conversation flow

---

## Setup & Running

```bash
# 1. Configure environment
cp .env.example .env
# Fill in GOOGLE_API_KEY or OPENAI_API_KEY, API_KEYS, ORCHESTRATOR_URL

# 2. Start all agents
docker compose up --build

# 3. Expose orchestrator via ngrok
ngrok http 8003

# 4. Update ORCHESTRATOR_URL in .env with ngrok URL and restart
```

---

## Submission

- **Track:** Agent (A2A)
- **Platform:** Prompt Opinion
- **Protocol:** A2A v1 + FHIR R4
- **Team:** Solo
