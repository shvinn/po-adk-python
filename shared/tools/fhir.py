"""
FHIR tools — query a FHIR R4 server on behalf of the patient in context.

These tools are registered with the agent in agent.py.  At call time, each
tool reads the FHIR credentials (fhir_url, fhir_token, patient_id) from
tool_context.state — values that were injected by fhir_hook.extract_fhir_context
before the LLM was called.  The credentials never appear in the prompt.

─────────────────────────────────────────────────────────────────────────────
Adding your own FHIR tools
─────────────────────────────────────────────────────────────────────────────
1. Write a new function in this file (or create a new file in shared/tools/).
2. Add tool_context: ToolContext as the LAST parameter.
3. Start with  ctx = _get_fhir_context(tool_context); if isinstance(ctx, dict): return ctx
4. Export it from shared/tools/__init__.py.
5. Add it to the tools=[...] list in whichever agent(s) need it.

All FHIR REST calls go through _fhir_get(), which attaches the Bearer token
and sets the Accept header.  httpx is used (already a transitive dependency of
google-adk / a2a-sdk — no extra install required).
"""
import logging

import httpx
from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)

_FHIR_TIMEOUT = 15  # seconds


# ── Private helpers ────────────────────────────────────────────────────────────

def _get_fhir_context(tool_context: ToolContext):
    """
    Read FHIR credentials injected by fhir_hook into the session state.

    Returns (fhir_url, fhir_token, patient_id) on success.
    Returns an error dict if any credential is missing so the caller can
    return it directly as the tool result.
    """
    fhir_url   = tool_context.state.get("fhir_url",   "").rstrip("/")
    fhir_token = tool_context.state.get("fhir_token", "")
    patient_id = tool_context.state.get("patient_id", "")

    missing = [
        name for name, val in [
            ("fhir_url",   fhir_url),
            ("fhir_token", fhir_token),
            ("patient_id", patient_id),
        ]
        if not val
    ]
    if missing:
        return {
            "status": "error",
            "error_message": (
                f"FHIR context is not available — missing: {', '.join(missing)}. "
                "Ensure the caller includes 'fhir-context' in the A2A message metadata."
            ),
        }
    return fhir_url, fhir_token, patient_id


def _fhir_post(fhir_url: str, token: str, path: str, body: dict) -> dict:
    """Perform an authenticated FHIR POST and return the parsed JSON response."""
    response = httpx.post(
        f"{fhir_url}/{path}",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept":        "application/fhir+json",
            "Content-Type":  "application/fhir+json",
        },
        timeout=_FHIR_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def _fhir_get(fhir_url: str, token: str, path: str, params: dict | None = None) -> dict:
    """Perform an authenticated FHIR GET and return the parsed JSON response."""
    response = httpx.get(
        f"{fhir_url}/{path}",
        params=params,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept":        "application/fhir+json",
        },
        timeout=_FHIR_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def _http_error_result(exc: httpx.HTTPStatusError) -> dict:
    return {
        "status":        "error",
        "http_status":   exc.response.status_code,
        "error_message": f"FHIR server returned HTTP {exc.response.status_code}: {exc.response.text[:200]}",
    }


def _connection_error_result(exc: Exception) -> dict:
    return {
        "status":        "error",
        "error_message": f"Could not reach FHIR server: {exc}",
    }


def _coding_display(codings: list) -> str:
    """Return the first human-readable display text from a list of FHIR codings."""
    for c in codings:
        if c.get("display"):
            return c["display"]
    return "Unknown"


# ── Tool: patient demographics ─────────────────────────────────────────────────

def get_patient_demographics(tool_context: ToolContext) -> dict:
    """
    Fetches the demographic information for the current patient from the FHIR server.

    Returns name, date of birth, gender, and primary contact details.
    No arguments required — the patient identity comes from the session context.
    """
    ctx = _get_fhir_context(tool_context)
    if isinstance(ctx, dict):
        return ctx
    fhir_url, fhir_token, patient_id = ctx

    logger.info("tool_get_patient_demographics patient_id=%s", patient_id)
    try:
        patient = _fhir_get(fhir_url, fhir_token, f"Patient/{patient_id}")
    except httpx.HTTPStatusError as e:
        return _http_error_result(e)
    except Exception as e:
        return _connection_error_result(e)

    names    = patient.get("name", [])
    official = next((n for n in names if n.get("use") == "official"), names[0] if names else {})
    given    = " ".join(official.get("given", []))
    family   = official.get("family", "")
    full_name = f"{given} {family}".strip() or "Unknown"

    contacts = [
        {"system": t.get("system"), "value": t.get("value"), "use": t.get("use")}
        for t in patient.get("telecom", [])
    ]

    addrs   = patient.get("address", [])
    address = None
    if addrs:
        a = addrs[0]
        address = ", ".join(filter(None, [
            " ".join(a.get("line", [])),
            a.get("city"), a.get("state"), a.get("postalCode"), a.get("country"),
        ]))

    return {
        "status":         "success",
        "patient_id":     patient_id,
        "name":           full_name,
        "birth_date":     patient.get("birthDate"),
        "gender":         patient.get("gender"),
        "active":         patient.get("active"),
        "contacts":       contacts,
        "address":        address,
        "marital_status": (patient.get("maritalStatus") or {}).get("text"),
    }


# ── Tool: active medications ───────────────────────────────────────────────────

def get_active_medications(tool_context: ToolContext) -> dict:
    """
    Retrieves the patient's current active medication list from the FHIR server.

    Queries MedicationStatement resources with status=active and returns medication
    names, dosage instructions, and prescribing dates.
    No arguments required.
    """
    ctx = _get_fhir_context(tool_context)
    if isinstance(ctx, dict):
        return ctx
    fhir_url, fhir_token, patient_id = ctx

    logger.info("tool_get_active_medications patient_id=%s", patient_id)
    try:
        bundle = _fhir_get(
            fhir_url, fhir_token, "MedicationStatement",
            params={"patient": patient_id, "status": "active", "_count": "50"},
        )
    except httpx.HTTPStatusError as e:
        return _http_error_result(e)
    except Exception as e:
        return _connection_error_result(e)

    medications = []
    for entry in bundle.get("entry", []):
        res         = entry.get("resource", {})
        med_concept = res.get("medicationCodeableConcept", {})
        med_name    = (
            med_concept.get("text")
            or _coding_display(med_concept.get("coding", []))
            or res.get("medicationReference", {}).get("display", "Unknown")
        )
        dosage_list = [d.get("text", "No dosage text") for d in res.get("dosage", [])]
        medications.append({
            "medication":   med_name,
            "status":       res.get("status"),
            "dosage":       dosage_list[0] if dosage_list else "Not specified",
            "date_asserted": res.get("dateAsserted"),
            "prescriber":   (res.get("informationSource") or {}).get("display"),
        })

    return {
        "status":      "success",
        "patient_id":  patient_id,
        "count":       len(medications),
        "medications": medications,
    }


# ── Tool: active conditions (problem list) ─────────────────────────────────────

def get_active_conditions(tool_context: ToolContext) -> dict:
    """
    Retrieves the patient's active conditions and diagnoses from the FHIR server.

    Queries Condition resources with clinical-status=active and returns the
    problem list with condition names, severity, and onset dates.
    No arguments required.
    """
    ctx = _get_fhir_context(tool_context)
    if isinstance(ctx, dict):
        return ctx
    fhir_url, fhir_token, patient_id = ctx

    logger.info("tool_get_active_conditions patient_id=%s", patient_id)
    try:
        bundle = _fhir_get(
            fhir_url, fhir_token, "Condition",
            params={"patient": patient_id, "clinical-status": "active", "_count": "50"},
        )
    except httpx.HTTPStatusError as e:
        return _http_error_result(e)
    except Exception as e:
        return _connection_error_result(e)

    conditions = []
    for entry in bundle.get("entry", []):
        res   = entry.get("resource", {})
        code  = res.get("code", {})
        onset = res.get("onsetDateTime") or (res.get("onsetPeriod") or {}).get("start")
        conditions.append({
            "condition":       code.get("text") or _coding_display(code.get("coding", [])),
            "clinical_status": (
                (res.get("clinicalStatus") or {}).get("coding", [{}])[0].get("code")
            ),
            "severity":        (res.get("severity") or {}).get("text"),
            "onset":           onset,
            "recorded_date":   res.get("recordedDate"),
        })

    return {
        "status":     "success",
        "patient_id": patient_id,
        "count":      len(conditions),
        "conditions": conditions,
    }


# ── Tool: recent observations (vitals / labs) ──────────────────────────────────

def get_observations(category: str, tool_context: ToolContext) -> dict:
    """
    Retrieves recent clinical observations for the patient from the FHIR server.

    Args:
        category: FHIR observation category. Common values:
                    'vital-signs'    — blood pressure, heart rate, temperature, SpO2
                    'laboratory'     — lab results (CBC, HbA1c, metabolic panel, etc.)
                    'social-history' — smoking status, alcohol use, etc.
                  Defaults to 'vital-signs' if not specified.

    Returns the 20 most recent observations in the category, newest first.
    """
    ctx = _get_fhir_context(tool_context)
    if isinstance(ctx, dict):
        return ctx
    fhir_url, fhir_token, patient_id = ctx

    category = (category or "vital-signs").strip().lower()
    logger.info("tool_get_observations patient_id=%s category=%s", patient_id, category)
    try:
        bundle = _fhir_get(
            fhir_url, fhir_token, "Observation",
            params={"patient": patient_id, "category": category, "_sort": "-date", "_count": "20"},
        )
    except httpx.HTTPStatusError as e:
        return _http_error_result(e)
    except Exception as e:
        return _connection_error_result(e)

    observations = []
    for entry in bundle.get("entry", []):
        res  = entry.get("resource", {})
        code = res.get("code", {})
        obs_name = code.get("text") or _coding_display(code.get("coding", []))

        value, unit = None, None
        if "valueQuantity" in res:
            vq    = res["valueQuantity"]
            value = vq.get("value")
            unit  = vq.get("unit") or vq.get("code")
        elif "valueCodeableConcept" in res:
            value = (res["valueCodeableConcept"].get("text")
                     or _coding_display(res["valueCodeableConcept"].get("coding", [])))
        elif "valueString" in res:
            value = res["valueString"]

        components = []
        for comp in res.get("component", []):
            comp_code = (comp.get("code") or {})
            comp_name = comp_code.get("text") or _coding_display(comp_code.get("coding", []))
            comp_vq   = comp.get("valueQuantity", {})
            components.append({
                "name":  comp_name,
                "value": comp_vq.get("value"),
                "unit":  comp_vq.get("unit") or comp_vq.get("code"),
            })

        observations.append({
            "observation":    obs_name,
            "value":          value,
            "unit":           unit,
            "components":     components or None,
            "effective_date": res.get("effectiveDateTime") or (res.get("effectivePeriod") or {}).get("start"),
            "status":         res.get("status"),
            "interpretation": (
                (res.get("interpretation") or [{}])[0].get("text")
                or _coding_display((res.get("interpretation") or [{}])[0].get("coding", []))
            ),
        })

    return {
        "status":       "success",
        "patient_id":   patient_id,
        "category":     category,
        "count":        len(observations),
        "observations": observations,
    }


# ── Tool: encounter history ────────────────────────────────────────────────────

def get_encounters(tool_context: ToolContext) -> dict:
    """
    Retrieves the patient's doctor visit history from the FHIR server.

    Returns all encounters sorted by date (newest first), including visit type,
    reason, doctor name, and duration. No arguments required.
    """
    ctx = _get_fhir_context(tool_context)
    if isinstance(ctx, dict):
        return ctx
    fhir_url, fhir_token, patient_id = ctx

    logger.info("tool_get_encounters patient_id=%s", patient_id)
    try:
        bundle = _fhir_get(
            fhir_url, fhir_token, "Encounter",
            params={"patient": patient_id, "_sort": "-date", "_count": "50"},
        )
    except httpx.HTTPStatusError as e:
        return _http_error_result(e)
    except Exception as e:
        return _connection_error_result(e)

    encounters = []
    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})

        visit_type = None
        for t in res.get("type", []):
            visit_type = t.get("text") or _coding_display(t.get("coding", []))
            if visit_type:
                break

        reason = None
        for r in res.get("reasonCode", []):
            reason = r.get("text") or _coding_display(r.get("coding", []))
            if reason:
                break

        participants = [
            p.get("individual", {}).get("display")
            for p in res.get("participant", [])
            if p.get("individual", {}).get("display")
        ]

        period = res.get("period", {})
        encounters.append({
            "encounter_id":  res.get("id"),
            "status":        res.get("status"),
            "visit_type":    visit_type,
            "reason":        reason,
            "start":         period.get("start"),
            "end":           period.get("end"),
            "practitioners": participants,
            "class":         (res.get("class") or {}).get("display"),
        })

    return {
        "status":      "success",
        "patient_id":  patient_id,
        "count":       len(encounters),
        "encounters":  encounters,
    }


# ── Tool: create observation (lab result) ─────────────────────────────────────

# LOINC codes for common lab results used in clinical demos.
# Extend this table or pass a custom loinc_code argument to cover other tests.
_LOINC_TABLE: dict[str, tuple[str, str]] = {
    "hba1c":           ("4548-4",  "Hemoglobin A1c/Hemoglobin.total in Blood"),
    "glucose":         ("1558-6",  "Fasting glucose [Mass/volume] in Serum or Plasma"),
    "c-peptide":       ("1986-9",  "C peptide [Mass/volume] in Serum or Plasma"),
    "gad antibody":    ("56695-0", "Glutamate decarboxylase Ab [Units/volume] in Serum"),
    "ldl":             ("2089-1",  "Cholesterol in LDL [Mass/volume] in Serum or Plasma"),
    "hdl":             ("2085-9",  "Cholesterol in HDL [Mass/volume] in Serum or Plasma"),
    "triglycerides":   ("2571-8",  "Triglycerides [Mass/volume] in Serum or Plasma"),
    "creatinine":      ("2160-0",  "Creatinine [Mass/volume] in Serum or Plasma"),
    "potassium":       ("2823-3",  "Potassium [Moles/volume] in Serum or Plasma"),
    "sodium":          ("2951-2",  "Sodium [Moles/volume] in Serum or Plasma"),
    "tsh":             ("3016-3",  "Thyrotropin [Units/volume] in Serum or Plasma"),
    "bnp":             ("42637-9", "Natriuretic peptide B [Mass/volume] in Serum or Plasma"),
    "troponin":        ("6598-7",  "Troponin T.cardiac [Mass/volume] in Serum or Plasma"),
    "egfr":            ("62238-1", "Glomerular filtration rate/1.73 sq M.predicted"),
    "hemoglobin":      ("718-7",   "Hemoglobin [Mass/volume] in Blood"),
}


def create_observation(
    test_name: str,
    value: float,
    unit: str,
    tool_context: ToolContext,
    loinc_code: str = "",
    loinc_display: str = "",
) -> dict:
    """
    Posts a new lab result (Observation) for the current patient to the FHIR server.

    Args:
        test_name:     Name of the lab test (e.g. "HbA1c", "glucose", "LDL").
                       Used to look up the LOINC code automatically from the
                       built-in table if loinc_code is not provided.
        value:         Numeric result value (e.g. 9.2).
        unit:          Unit of measure (e.g. "%", "mg/dL", "ng/mL", "mEq/L").
        loinc_code:    Optional LOINC code override. If provided, skips the
                       built-in lookup and uses this code directly.
        loinc_display: Optional display name override for the LOINC code.

    Returns whether the observation was successfully created.
    """
    ctx = _get_fhir_context(tool_context)
    if isinstance(ctx, dict):
        return ctx
    fhir_url, fhir_token, patient_id = ctx

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Resolve LOINC code — explicit override takes priority, then table lookup.
    key = test_name.strip().lower()
    if loinc_code:
        code = loinc_code
        display = loinc_display or test_name
    elif key in _LOINC_TABLE:
        code, display = _LOINC_TABLE[key]
    else:
        # Partial match fallback
        match = next(((c, d) for k, (c, d) in _LOINC_TABLE.items() if key in k or k in k), None)
        if match:
            code, display = match
        else:
            return {
                "status": "error",
                "error_message": (
                    f"Unknown test name '{test_name}'. Provide a loinc_code explicitly, "
                    f"or use one of: {', '.join(sorted(_LOINC_TABLE.keys()))}."
                ),
            }

    observation = {
        "resourceType": "Observation",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory",
                        "display": "Laboratory",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": code,
                    "display": display,
                }
            ],
            "text": test_name,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": now,
        "issued": now,
        "valueQuantity": {
            "value": value,
            "unit": unit,
            "system": "http://unitsofmeasure.org",
            "code": unit,
        },
    }

    logger.info(
        "tool_create_observation patient_id=%s test=%s loinc=%s value=%s %s",
        patient_id, test_name, code, value, unit,
    )
    try:
        result = _fhir_post(fhir_url, fhir_token, "Observation", observation)
        return {
            "status": "success",
            "message": f"Lab result posted: {test_name} = {value} {unit}.",
            "observation_id": result.get("id"),
            "loinc_code": code,
            "loinc_display": display,
        }
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            return {
                "status": "error",
                "write_supported": False,
                "message": f"FHIR server rejected the write with HTTP {e.response.status_code} — server is read-only or token lacks write scopes.",
            }
        return _http_error_result(e)
    except Exception as e:
        return _connection_error_result(e)


# ── Tool: create condition ────────────────────────────────────────────────────

def create_condition(
    condition_name: str,
    practitioner: str,
    tool_context: ToolContext,
    icd10_code: str = "",
    severity: str = "",
    onset_date: str = "",
) -> dict:
    """
    Records a new clinical condition (diagnosis) for the current patient in the FHIR server.

    Args:
        condition_name: Name of the condition (e.g. "Migraine", "Hypertension").
        practitioner:   Name of the recording clinician (e.g. "Dr. Smith").
        icd10_code:     Optional ICD-10 code (e.g. "G43.909" for migraine).
                        If omitted, the condition is recorded by display name only.
        severity:       Optional severity text: "mild", "moderate", or "severe".
        onset_date:     Optional onset date in YYYY-MM-DD format. Defaults to today.

    Returns whether the Condition was successfully created.
    """
    ctx = _get_fhir_context(tool_context)
    if isinstance(ctx, dict):
        return ctx
    fhir_url, fhir_token, patient_id = ctx

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    recorded_date = onset_date or now[:10]

    coding = [{"system": "http://hl7.org/fhir/sid/icd-10", "code": icd10_code, "display": condition_name}] if icd10_code else []

    condition = {
        "resourceType": "Condition",
        "clinicalStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active", "display": "Active"}]
        },
        "verificationStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "confirmed", "display": "Confirmed"}]
        },
        "code": {"coding": coding, "text": condition_name},
        "subject": {"reference": f"Patient/{patient_id}"},
        "recordedDate": now,
        "recorder": {"display": practitioner},
    }

    if severity:
        condition["severity"] = {"text": severity}
    if onset_date:
        condition["onsetDateTime"] = onset_date

    logger.info(
        "tool_create_condition patient_id=%s condition=%s icd10=%s",
        patient_id, condition_name, icd10_code,
    )
    try:
        result = _fhir_post(fhir_url, fhir_token, "Condition", condition)
        return {
            "status": "success",
            "message": f"Condition recorded: {condition_name}.",
            "condition_id": result.get("id"),
            "condition": condition_name,
            "icd10_code": icd10_code or "not specified",
            "recorded_by": practitioner,
        }
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            return {
                "status": "error",
                "write_supported": False,
                "message": f"FHIR server rejected the write with HTTP {e.response.status_code} — server is read-only or token lacks write scopes.",
            }
        return _http_error_result(e)
    except Exception as e:
        return _connection_error_result(e)


# ── Tool: create medication (MedicationStatement) ─────────────────────────────

def create_medication(
    medication_name: str,
    dosage: str,
    practitioner: str,
    tool_context: ToolContext,
    rx_norm_code: str = "",
    frequency: str = "",
) -> dict:
    """
    Records a new medication (MedicationStatement) for the current patient in the FHIR server.

    Args:
        medication_name: Name of the medication (e.g. "Metformin", "Insulin glargine").
        dosage:          Dosage instruction text (e.g. "500 mg twice daily with meals").
        practitioner:    Name of the prescribing doctor (e.g. "Dr. Smith").
        rx_norm_code:    Optional RxNorm code for the medication. If omitted, the
                         medication is recorded by display name only.
        frequency:       Optional frequency text (e.g. "once daily", "BID").
                         If provided, added as a separate dosage timing note.

    Returns whether the MedicationStatement was successfully created.
    """
    ctx = _get_fhir_context(tool_context)
    if isinstance(ctx, dict):
        return ctx
    fhir_url, fhir_token, patient_id = ctx

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    med_concept: dict = {"text": medication_name}
    if rx_norm_code:
        med_concept["coding"] = [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": rx_norm_code, "display": medication_name}]

    dosage_text = f"{dosage}. {frequency}".strip(". ") if frequency else dosage

    medication_statement = {
        "resourceType": "MedicationStatement",
        "status": "active",
        "medicationCodeableConcept": med_concept,
        "subject": {"reference": f"Patient/{patient_id}"},
        "dateAsserted": now,
        "informationSource": {"display": practitioner},
        "dosage": [{"text": dosage_text}],
    }

    logger.info(
        "tool_create_medication patient_id=%s medication=%s prescriber=%s",
        patient_id, medication_name, practitioner,
    )
    try:
        result = _fhir_post(fhir_url, fhir_token, "MedicationStatement", medication_statement)
        return {
            "status": "success",
            "message": f"Medication recorded: {medication_name} — {dosage_text}.",
            "medication_statement_id": result.get("id"),
            "medication": medication_name,
            "dosage": dosage_text,
            "prescriber": practitioner,
        }
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            return {
                "status": "error",
                "write_supported": False,
                "message": f"FHIR server rejected the write with HTTP {e.response.status_code} — server is read-only or token lacks write scopes.",
            }
        return _http_error_result(e)
    except Exception as e:
        return _connection_error_result(e)


# ── Tool: create encounter ─────────────────────────────────────────────────────

def create_encounter(reason: str, practitioner: str, tool_context: ToolContext) -> dict:
    """
    Creates a new doctor visit (Encounter) for the current patient in the FHIR server.

    Args:
        reason:       The reason for the visit (chief complaint or purpose).
        practitioner: Name of the doctor or practitioner conducting the visit.

    Returns whether the encounter was successfully created.
    """
    ctx = _get_fhir_context(tool_context)
    if isinstance(ctx, dict):
        return ctx
    fhir_url, fhir_token, patient_id = ctx

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    encounter = {
        "resourceType": "Encounter",
        "status": "finished",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "AMB",
            "display": "Ambulatory"
        },
        "type": [{"text": "General Practice Visit"}],
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": now, "end": now},
        "participant": [{"individual": {"display": practitioner}}],
        "reasonCode": [{"text": reason}],
    }

    logger.info("tool_create_encounter patient_id=%s reason=%s", patient_id, reason)
    try:
        result = _fhir_post(fhir_url, fhir_token, "Encounter", encounter)
        return {
            "status": "success",
            "write_supported": True,
            "message": f"Encounter created successfully.",
            "encounter_id": result.get("id"),
        }
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            return {
                "status": "error",
                "write_supported": False,
                "message": f"FHIR server rejected the write with HTTP {e.response.status_code} — server is read-only or token lacks write scopes.",
            }
        return _http_error_result(e)
    except Exception as e:
        return _connection_error_result(e)
