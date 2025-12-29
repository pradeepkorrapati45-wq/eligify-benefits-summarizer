import os
import json
import io
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

import pdfplumber

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8000",
        "https://eligify.vercel.app",
        "https://your-custom-domain.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory="../frontend"), name="static")


# ============================================
# MODELS
# ============================================

class BenefitsRequest(BaseModel):
    raw_text: str


class BenefitsSummary(BaseModel):
    plan_status: str | None = None
    deductible_total: float | None = None
    deductible_remaining: float | None = None
    annual_max_total: float | None = None
    annual_max_remaining: float | None = None
    preventive: str | None = None
    basic: str | None = None
    major: str | None = None
    orthodontics: str | None = None
    frequency_limits: list[str] | None = None
    waiting_periods: list[str] | None = None
    notes: list[str] | None = None


class TreatmentProcedure(BaseModel):
    code: str  # e.g., "D2740"
    description: str  # e.g., "Crown - Porcelain/Ceramic"
    fee: float  # Dentist's fee
    category: str  # "preventive", "basic", "major"


class TreatmentCalculationRequest(BaseModel):
    procedures: List[TreatmentProcedure]
    deductible_remaining: float
    annual_max_remaining: float
    preventive_coverage: float  # e.g., 100.0 for 100%
    basic_coverage: float  # e.g., 80.0 for 80%
    major_coverage: float  # e.g., 50.0 for 50%


class ProcedureCostBreakdown(BaseModel):
    code: str
    description: str
    dentist_fee: float
    insurance_allowed: float
    deductible_applied: float
    insurance_pays: float
    patient_coinsurance: float
    patient_pays: float
    coverage_percentage: float
    notes: List[str] = []


class TreatmentCalculationResponse(BaseModel):
    procedures: List[ProcedureCostBreakdown]
    total_dentist_fees: float
    total_insurance_pays: float
    total_patient_pays: float
    total_deductible_used: float
    remaining_annual_max: float
    summary: str


class OpenDentalSaveRequest(BaseModel):
    patient_name: str
    benefits_data: BenefitsSummary


class OpenDentalSaveResponse(BaseModel):
    success: bool
    message: str
    saved_fields: dict


# ============================================
# PROMPTS
# ============================================

SYSTEM_PROMPT = """
You are an expert dental insurance benefits interpreter trained to extract ONLY dental coverage information 
from long, messy payer portal text or benefit summaries.

Your job is to read the full text provided by the user, identify all relevant dental benefits, 
and return a STRICT JSON object matching the schema below.

-----------------------
EXTRACTION RULES
-----------------------

1. DO NOT hallucinate any values. 
   If a value is not explicitly mentioned, return null or an empty list.

2. DO NOT include non-dental information (vision, medical, employer info, contact info, legal text).

3. PLAN STATUS:
   Normalize plan_status to only one of the following lowercase strings:
   - "active"
   - "inactive"
   - "terminated"
   - "pending"
   If no status is mentioned, return null.

4. COVERAGE LEVELS:
   For preventive, basic, major, and orthodontics:
   - Return ONLY the percentage value (e.g., "100%", "80%", "50%", "0%").
   - Extract the number even if buried in text.

5. DEDUCTIBLE:
   Extract:
   - deductible_total (as a number, not string)
   - deductible_remaining (as a number, not string)
   If only one is mentioned, fill what you can and leave the rest null.

6. ANNUAL MAX:
   Extract:
   - annual_max_total (as a number)
   - annual_max_remaining (as a number, if mentioned)

7. FREQUENCY LIMITS:
   Add any benefits describing service frequency rules, such as:
   - "2 cleanings per year"
   - "1 exam per 6 months"
   - "Bitewing x-rays once per year"
   - "Full mouth x-rays once per 5 years"
   Include as short, clear strings.

8. WAITING PERIODS:
   Extract all waiting periods for:
   - Preventive
   - Basic
   - Major
   Format as: "Preventive: none", "Basic: 6 months", "Major: 12 months"

9. NOTES:
   Include ANY plan details that don't fit the fields above, such as:
   - exclusions (e.g., "no ortho coverage except medically necessary")
   - disclaimers
   - usage history (e.g., "patient used 1 cleaning this year on 03/15/2024")
   - reset rules (e.g., "benefits reset every calendar year on January 1st")
   - special limitations (e.g., "posterior composites downgrade to amalgam")
   - pre-authorization requirements

10. OUTPUT FORMAT:
   You MUST return ONLY valid JSON matching exactly this schema:

{
  "plan_status": string or null,
  "deductible_total": number or null,
  "deductible_remaining": number or null,
  "annual_max_total": number or null,
  "annual_max_remaining": number or null,
  "preventive": string or null,
  "basic": string or null,
  "major": string or null,
  "orthodontics": string or null,
  "frequency_limits": [strings],
  "waiting_periods": [strings],
  "notes": [strings]
}

11. IMPORTANT:
   The output must be valid JSON. Do NOT add explanations, comments, or extra fields.

-----------------------

Begin extracting using these rules.
"""


# ============================================
# CORE FUNCTIONS
# ============================================

def summarize_text(raw_text: str) -> BenefitsSummary:
    """
    Core AI engine: given raw text (from textarea or PDF),
    call OpenAI and map to BenefitsSummary.
    """
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ],
        response_format={"type": "json_object"},
    )

    raw_json = completion.choices[0].message.content
    data = json.loads(raw_json)
    return BenefitsSummary(**data)


def calculate_procedure_cost(
    procedure: TreatmentProcedure,
    deductible_remaining: float,
    coverage_percentage: float,
    deductible_applies: bool = True
) -> tuple[ProcedureCostBreakdown, float]:
    """
    Calculate cost breakdown for a single procedure.
    Returns: (breakdown, deductible_used)
    """
    
    # Insurance typically allows 100% of fee for in-network
    # For demo purposes, we'll use 100% of fee as allowed amount
    insurance_allowed = procedure.fee
    
    # Determine if deductible applies
    deductible_applied = 0.0
    if deductible_applies and deductible_remaining > 0:
        deductible_applied = min(deductible_remaining, insurance_allowed)
    
    # Amount subject to coinsurance (after deductible)
    amount_after_deductible = insurance_allowed - deductible_applied
    
    # Insurance pays their percentage of remaining amount
    insurance_pays = amount_after_deductible * (coverage_percentage / 100.0)
    
    # Patient pays deductible + their coinsurance percentage
    patient_coinsurance = amount_after_deductible * ((100.0 - coverage_percentage) / 100.0)
    patient_pays = deductible_applied + patient_coinsurance
    
    # Add notes
    notes = []
    if deductible_applied > 0:
        notes.append(f"${deductible_applied:.2f} applied to deductible")
    if coverage_percentage < 100:
        notes.append(f"Patient pays {100 - coverage_percentage:.0f}% coinsurance")
    if coverage_percentage == 100:
        notes.append("Covered at 100% - no patient cost")
    
    breakdown = ProcedureCostBreakdown(
        code=procedure.code,
        description=procedure.description,
        dentist_fee=procedure.fee,
        insurance_allowed=insurance_allowed,
        deductible_applied=deductible_applied,
        insurance_pays=insurance_pays,
        patient_coinsurance=patient_coinsurance,
        patient_pays=patient_pays,
        coverage_percentage=coverage_percentage,
        notes=notes
    )
    
    return breakdown, deductible_applied


# ============================================
# ENDPOINTS
# ============================================

@app.get("/", response_class=FileResponse)
def serve_index():
    return FileResponse("../frontend/index.html")


@app.post("/summarize", response_model=BenefitsSummary)
def summarize_benefits(req: BenefitsRequest):
    return summarize_text(req.raw_text)


@app.post("/summarize-pdf", response_model=BenefitsSummary)
async def summarize_pdf(file: UploadFile = File(...)):
    """
    V2: PDF upload → extract text → reuse same AI engine.
    """
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Please upload a valid PDF file.")

    pdf_bytes = await file.read()

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text: list[str] = []
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages_text.append(page_text)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read the PDF file.")

    full_text = "\n\n".join(pages_text).strip()

    if not full_text:
        raise HTTPException(status_code=400, detail="Could not extract any text from the PDF.")

    return summarize_text(full_text)


@app.post("/calculate-treatment", response_model=TreatmentCalculationResponse)
def calculate_treatment(req: TreatmentCalculationRequest):
    """
    Calculate patient costs for a treatment plan based on insurance benefits.
    """
    
    procedure_breakdowns = []
    total_dentist_fees = 0.0
    total_insurance_pays = 0.0
    total_patient_pays = 0.0
    total_deductible_used = 0.0
    
    deductible_remaining = req.deductible_remaining
    
    for procedure in req.procedures:
        # Determine coverage percentage based on category
        if procedure.category.lower() == "preventive":
            coverage_pct = req.preventive_coverage
            deductible_applies = False  # Preventive usually doesn't apply to deductible
        elif procedure.category.lower() == "basic":
            coverage_pct = req.basic_coverage
            deductible_applies = True
        elif procedure.category.lower() == "major":
            coverage_pct = req.major_coverage
            deductible_applies = True
        else:
            coverage_pct = 0.0
            deductible_applies = False
        
        # Calculate cost breakdown
        breakdown, deductible_used = calculate_procedure_cost(
            procedure=procedure,
            deductible_remaining=deductible_remaining,
            coverage_percentage=coverage_pct,
            deductible_applies=deductible_applies
        )
        
        procedure_breakdowns.append(breakdown)
        
        # Update running totals
        total_dentist_fees += breakdown.dentist_fee
        total_insurance_pays += breakdown.insurance_pays
        total_patient_pays += breakdown.patient_pays
        total_deductible_used += deductible_used
        
        # Update remaining deductible
        deductible_remaining -= deductible_used
    
    # Calculate remaining annual max
    remaining_annual_max = req.annual_max_remaining - total_insurance_pays
    
    # Generate summary
    summary = f"Total treatment cost: ${total_dentist_fees:.2f}. "
    summary += f"Insurance will pay: ${total_insurance_pays:.2f}. "
    summary += f"Patient responsibility: ${total_patient_pays:.2f}. "
    
    if total_deductible_used > 0:
        summary += f"(Includes ${total_deductible_used:.2f} deductible). "
    
    summary += f"Remaining annual maximum after treatment: ${remaining_annual_max:.2f}."
    
    return TreatmentCalculationResponse(
        procedures=procedure_breakdowns,
        total_dentist_fees=total_dentist_fees,
        total_insurance_pays=total_insurance_pays,
        total_patient_pays=total_patient_pays,
        total_deductible_used=total_deductible_used,
        remaining_annual_max=remaining_annual_max,
        summary=summary
    )


@app.post("/save-to-open-dental", response_model=OpenDentalSaveResponse)
def save_to_open_dental(req: OpenDentalSaveRequest):
    """
    DEMO ENDPOINT: Simulates saving benefits data to Open Dental.
    In production, this would actually write to Open Dental database.
    """
    
    # Simulate what would be saved to Open Dental
    saved_fields = {
        "patient_name": req.patient_name,
        "plan_status": req.benefits_data.plan_status,
        "insurance_plan": {
            "annual_max": req.benefits_data.annual_max_total,
            "annual_max_used": (
                req.benefits_data.annual_max_total - req.benefits_data.annual_max_remaining
                if req.benefits_data.annual_max_total and req.benefits_data.annual_max_remaining
                else None
            ),
            "deductible": req.benefits_data.deductible_total,
            "deductible_used": (
                req.benefits_data.deductible_total - req.benefits_data.deductible_remaining
                if req.benefits_data.deductible_total and req.benefits_data.deductible_remaining
                else None
            ),
        },
        "coverage_percentages": {
            "diagnostic_preventive": req.benefits_data.preventive,
            "basic_restorative": req.benefits_data.basic,
            "major_restorative": req.benefits_data.major,
            "orthodontics": req.benefits_data.orthodontics,
        },
        "frequency_limitations": req.benefits_data.frequency_limits or [],
        "benefit_notes": req.benefits_data.notes or [],
        "waiting_periods": req.benefits_data.waiting_periods or [],
    }
    
    # In production, you would:
    # 1. Connect to Open Dental MySQL database
    # 2. Find the patient record by name/ID
    # 3. Update the insplan, inssub, and benefit tables
    # 4. Log the transaction
    
    return OpenDentalSaveResponse(
        success=True,
        message=f"Successfully saved insurance benefits for {req.patient_name} to Open Dental",
        saved_fields=saved_fields
    )


@app.get("/health")
def health_check():
    """Simple health check endpoint"""
    return {"status": "healthy", "service": "Eligify API"}