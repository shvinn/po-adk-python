# ClinIQ — AI-Powered Clinical Decision Support
### Agents Assemble Hackathon · Track: Agent (A2A) · Platform: Prompt Opinion

---

## What is ClinIQ?

ClinIQ is a multi-agent clinical decision support system that guides a doctor from a patient's first symptom presentation through to a confirmed diagnosis and treatment plan — using real FHIR R4 patient data at every step.

A team of six specialist AI agents, each equipped with a clinical rule book, collaborate through a central orchestrator to read the patient's full health record, reason across it, and surface actionable clinical insights in seconds. Every finding is grounded in live FHIR data — not LLM guessing.

---

## Architecture

```
Doctor (via Prompt Opinion chatbot)
        │
        ▼
   ┌─────────────────────────────────────────┐
   │           Orchestrator                  │
   │  · Three-level triage protocol          │
   │  · Routes based on symptom/lab keywords │
   │  · Assembles unified clinical response  │
   │  · Proactive pharmacist safety checks   │
   └──────────────┬──────────────────────────┘
                  │  (in-process via AgentTool — zero HTTP latency)
        ┌─────────┼──────────────────────────────────┐
        │         │         │          │              │
        ▼         ▼         ▼          ▼              ▼
healthcare_  endocrin-  cardiol-  neurologist_  pharmacist_
fhir_agent   ologist    ogist     agent         agent
             _agent     _agent
```

**Key principle:** All specialist agents run in-process via ADK `AgentTool`. FHIR credentials travel in A2A message metadata — they never appear in the LLM prompt.

---

## Agents

### Orchestrator
The only agent the chatbot talks to. It implements a three-level triage protocol:

| Level | Trigger | Action |
|---|---|---|
| 1 — Simple lookup | Data request (demographics, chart brief) | Routes to `healthcare_fhir_agent` only |
| 2 — Clinical finding | Symptoms, labs, or clinical question | Routes to `healthcare_fhir_agent` + one specialist |
| 3 — Multi-system | Multiple specialties requested | Routes to `healthcare_fhir_agent` + multiple specialists in sequence |

**Routing is keyword-driven and explicit** — the orchestrator never answers clinical questions from its own knowledge. It:
- Detects explicit write requests (encounter, medication, condition) and routes them directly without triggering specialist agents
- Auto-triggers `pharmacist_agent` whenever a new treatment is being discussed
- Offers to record the encounter once a diagnosis is confirmed

---

### healthcare_fhir_agent
Pure FHIR data layer — all reads and writes. No clinical reasoning.

**Read tools:**
| Tool | FHIR Resource | Returns |
|---|---|---|
| `get_patient_demographics` | `Patient` | Name, DOB, gender, contacts, address |
| `get_active_medications` | `MedicationStatement` | Active medications, dosage, prescriber |
| `get_active_conditions` | `Condition` | Active diagnoses, severity, onset date |
| `get_observations` | `Observation` | Vitals and lab results by category |
| `get_encounters` | `Encounter` | Visit history, reason, practitioner, dates |

**Write tools:**
| Tool | FHIR Resource | Creates |
|---|---|---|
| `create_observation` | `Observation` | Lab result with LOINC code, value, and unit |
| `create_encounter` | `Encounter` | Visit record with reason and practitioner |
| `create_medication` | `MedicationStatement` | Active medication with dosage instructions |
| `create_condition` | `Condition` | Confirmed clinical condition with ICD-10 code |

---

### endocrinologist_agent
Interprets metabolic and hormonal lab results using a rule book.

**Clinical rule book:**
- **HbA1c thresholds:** Normal (<5.7%) → Prediabetes (5.7–6.4%) → Diabetes (≥6.5%) → Poor control (≥9.0%)
- **Fasting glucose:** Normal (<100) → Prediabetes (100–125) → Diabetes (≥126) → DKA risk (>400)
- **Type 1 vs Type 2 differentiation:**
  - C-peptide low + GAD antibody positive → Type 1 DM → initiate insulin
  - C-peptide low + GAD antibody negative → Consider MODY → genetics referral
  - C-peptide normal/high + GAD antibody negative → Type 2 DM → Metformin first-line
- **Thyroid:** TSH thresholds for hypo/hyperthyroidism
- **DKA red flags:** Glucose >400, ketones present, HHS indicators

**Tools:** `get_observations`, `get_active_conditions`, `get_patient_demographics`

---

### cardiologist_agent
Evaluates cardiovascular risk from vitals and lipid panels.

**Clinical rule book:**
- **Blood pressure (adult):** Normal → Elevated → Stage 1 HTN (130–139/80–89) → Stage 2 HTN (≥140/90) → Hypertensive crisis (≥180/120)
- **Blood pressure (pediatric):** Age/sex/height-adjusted percentile classification
- **Heart rate:** Tachycardia (>100 adult), bradycardia (<60), arrhythmia indicators
- **Lipid panel:** LDL thresholds (optimal <100, statin indicated ≥160), HDL risk assessment, triglycerides
- **Cardiovascular risk scoring:** New diabetes → automatic risk elevation; diabetes + HTN → high risk; statin consideration with dyslipidemia

**Red flags:** BP ≥ 180/120, HR >150 or <40, chest pain + elevated HR, elevated troponin

**Tools:** `get_observations`, `get_active_conditions`, `get_patient_demographics`

---

### neurologist_agent
Screens for peripheral neuropathy, autonomic dysfunction, and cognitive impairment.

**Clinical rule book:**
- **Peripheral neuropathy:** Symptom-triggered screen (numbness, tingling, burning, weakness); diabetes diagnosis always triggers baseline screen
- **Autonomic neuropathy:** Resting tachycardia, orthostatic hypotension, gastroparesis + diabetes
- **Cognitive assessment:** MMSE/MoCA thresholds, rapid decline workup, dementia screening (age >65)
- **Imaging interpretation:** White matter hyperintensities, cerebral atrophy, EMG conduction velocity, acute focal lesions
- **Headache classification:** Tension-type, migraine, thunderclap (subarachnoid hemorrhage protocol)
- **Diabetes screening schedule:** Baseline at diagnosis; annually from year 5 (T1D) and year 1 (T2D)

**Red flags:** Sudden focal deficit (stroke protocol), thunderclap headache, new-onset seizure, meningism

**Tools:** `get_observations`, `get_active_conditions`, `get_patient_demographics`, `get_encounters`

---

### pharmacist_agent
Reviews medication safety before any new treatment is started.

**Clinical rule book:**
- **Drug-drug interactions (flagged explicitly):**
  - Metformin + Topiramate → carbonic anhydrase inhibition → lactic acidosis risk (HIGH) → recommend Propranolol as alternative
  - Metformin + IV contrast → hold 48h pre/post imaging
  - Insulin + beta-blockers → masked hypoglycemia
  - Insulin + corticosteroids → glucose elevation, dose adjustment
  - SSRIs + triptans → serotonin syndrome
  - Warfarin + NSAIDs/antibiotics → INR fluctuation
- **Renal dosing:** eGFR <60 → dose review; eGFR <30 → Metformin contraindicated; eGFR <15 → insulin only
- **Hepatic dosing:** ALT/AST >3× ULN → hepatic drug review; severe impairment → Metformin contraindicated
- **Contraindications:** Metformin + heart failure (EF <35%), thiazolidinediones + heart failure, NSAIDs + CKD
- **Pediatric flags:** Weight-based dosing verification; adult doses in patients <18 flagged for review

**Output always includes:** interaction severity (high/medium/low), contraindication flags, dosage assessment, safe-to-proceed / substitute recommendation

**Tools:** `get_active_medications`, `get_active_conditions`, `get_patient_demographics`, `get_observations`

---

### general_agent
Stateless utility agent — no FHIR, no clinical reasoning.

**Tools:**
- `get_current_datetime(timezone)` — current date/time in any IANA timezone
- `look_up_icd10(term)` — ICD-10-CM code lookup from built-in reference table

---

## FHIR Write Tools — LOINC Reference

| Lab | LOINC Code |
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

## Key Design Decisions

### 1. Specialist Rule Books — not LLM guessing
Every clinical decision traces back to a numbered rule in the agent's instruction. Thresholds are explicit and deterministic. The LLM reasons within the rule book, not around it.

### 2. Bidirectional FHIR
ClinIQ reads patient history AND writes back: lab results (`create_observation`), visits (`create_encounter`), prescriptions (`create_medication`), and diagnoses (`create_condition`) — all persisted to the FHIR server during the conversation.

### 3. HIPAA by design
HIPAA guardrails are injected into every agent's instruction from `shared/hipaa.py`. FHIR credentials travel in A2A metadata, extracted by `before_model_callback` into session state — they never appear in any prompt. Every clinical output carries an AI-generated decision support disclaimer.

### 4. Zero-latency specialist consultation
All agents run in-process via ADK `AgentTool`. There are no inter-agent HTTP calls — the orchestrator calls specialists the way a function calls another function.

### 5. Multi-turn conversation fix
Prompt Opinion reuses task IDs across turns. Fixed in `shared/middleware.py`: strips `taskId` from `message/send` params so each turn creates a fresh A2A task while preserving `contextId` for FHIR session continuity.

### 6. Explicit triage routing — STEP 0 write guard
The orchestrator decision tree includes a STEP 0 that intercepts explicit write commands ("record this visit", "create encounter", "prescribe", "add condition") before symptom keywords trigger specialist routing — preventing write requests from being accidentally routed to clinical agents.

---

## Technical Stack

| Component | Technology |
|---|---|
| Agent framework | Google ADK |
| Agent protocol | A2A v1 |
| LLM | Gemini 2.5 Flash via LiteLLM (swappable to GPT-4o, Claude, Vertex AI) |
| Platform | Prompt Opinion |
| Health data | FHIR R4 |
| Transport | ASGI / uvicorn |
| Deployment | Docker Compose + ngrok |

---

## Project Structure

```
po-adk-python/
├── orchestrator/               # Triage + routing agent (single entry point)
├── healthcare_agent/           # All FHIR reads and writes
├── endocrinologist_agent/      # Metabolic / hormonal rule book
├── cardiologist_agent/         # Cardiovascular rule book
├── neurologist_agent/          # Neurological rule book
├── pharmacist_agent/           # Medication safety rule book
├── general_agent/              # Date/time, ICD-10 lookups
└── shared/
    ├── tools/fhir.py           # All 9 FHIR read/write tools + LOINC table
    ├── hipaa.py                # HIPAA guardrails injected into every agent
    ├── fhir_hook.py            # FHIR credential extraction (before_model_callback)
    ├── middleware.py           # API key auth + PO compatibility + task ID fix
    └── app_factory.py          # A2A agent card factory (A2A v1 compliant)
```

---

*⚠️ AI-generated decision support only. A licensed clinician must review and confirm before taking any clinical action.*
