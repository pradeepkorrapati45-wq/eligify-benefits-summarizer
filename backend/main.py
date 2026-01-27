import os
import json
import io
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import pdfplumber

load_dotenv()

# Initialize OpenAI client - compatible with both old and new versions
try:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
except TypeError:
    # Fallback for older OpenAI versions
    import openai
    openai.api_key = os.getenv("OPENAI_API_KEY")
    client = None

app = FastAPI(title="Eligify API", version="1.0.0")

# CORS - Allow all origins for demo (restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files - works for both local dev and production
FRONTEND_DIR = "../frontend" if os.path.exists("../frontend") else "./frontend"

# Mount static files BEFORE defining routes
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    print(f"✅ Serving static files from: {FRONTEND_DIR}")
else:
    print(f"⚠️ Frontend directory not found: {FRONTEND_DIR}")


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
    code: str
    description: str
    fee: float
    category: str


class TreatmentCalculationRequest(BaseModel):
    procedures: List[TreatmentProcedure]
    deductible_remaining: float
    annual_max_remaining: float
    preventive_coverage: float
    basic_coverage: float
    major_coverage: float


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
    try:
        if client:
            # New OpenAI client (v1.0+)
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": raw_text},
                ],
                response_format={"type": "json_object"},
            )
            raw_json = completion.choices[0].message.content
        else:
            # Old OpenAI library (v0.x)
            import openai
            completion = openai.ChatCompletion.create(
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
    except Exception as e:
        print(f"Error in summarize_text: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI processing error: {str(e)}")


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
    
    insurance_allowed = procedure.fee
    
    deductible_applied = 0.0
    if deductible_applies and deductible_remaining > 0:
        deductible_applied = min(deductible_remaining, insurance_allowed)
    
    amount_after_deductible = insurance_allowed - deductible_applied
    insurance_pays = amount_after_deductible * (coverage_percentage / 100.0)
    patient_coinsurance = amount_after_deductible * ((100.0 - coverage_percentage) / 100.0)
    patient_pays = deductible_applied + patient_coinsurance
    
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

@app.get("/")
def root():
    """Root endpoint - health check"""
    return {
        "status": "healthy",
        "service": "Eligify API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "app": "/app",
            "summarize_text": "/summarize",
            "summarize_pdf": "/summarize-pdf",
            "calculate_treatment": "/calculate-treatment",
            "save_to_open_dental": "/save-to-open-dental"
        }
    }


@app.get("/health")
def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy", "service": "Eligify API"}


@app.get("/app", response_class=FileResponse)
def serve_index():
    """Serve the frontend application"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        return JSONResponse(
            status_code=404,
            content={
                "error": "Frontend not found",
                "message": "Please ensure frontend files are in the correct directory.",
                "expected_path": FRONTEND_DIR
            }
        )


@app.post("/summarize", response_model=BenefitsSummary)
def summarize_benefits(req: BenefitsRequest):
    """Extract benefits from pasted text"""
    if not req.raw_text or not req.raw_text.strip():
        raise HTTPException(status_code=400, detail="Please provide benefits text")
    return summarize_text(req.raw_text)


@app.post("/summarize-pdf", response_model=BenefitsSummary)
async def summarize_pdf(file: UploadFile = File(...)):
    """Extract benefits from uploaded PDF"""
    
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    try:
        pdf_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {str(e)}")

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text = []
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages_text.append(page_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse PDF: {str(e)}")

    full_text = "\n\n".join(pages_text).strip()

    if not full_text:
        raise HTTPException(
            status_code=400,
            detail="Could not extract text from PDF. Please ensure the PDF contains selectable text."
        )

    return summarize_text(full_text)


@app.post("/calculate-treatment", response_model=TreatmentCalculationResponse)
def calculate_treatment(req: TreatmentCalculationRequest):
    """Calculate patient costs for treatment plan"""
    
    procedure_breakdowns = []
    total_dentist_fees = 0.0
    total_insurance_pays = 0.0
    total_patient_pays = 0.0
    total_deductible_used = 0.0
    
    deductible_remaining = req.deductible_remaining
    
    for procedure in req.procedures:
        if procedure.category.lower() == "preventive":
            coverage_pct = req.preventive_coverage
            deductible_applies = False
        elif procedure.category.lower() == "basic":
            coverage_pct = req.basic_coverage
            deductible_applies = True
        elif procedure.category.lower() == "major":
            coverage_pct = req.major_coverage
            deductible_applies = True
        else:
            coverage_pct = 0.0
            deductible_applies = False
        
        breakdown, deductible_used = calculate_procedure_cost(
            procedure=procedure,
            deductible_remaining=deductible_remaining,
            coverage_percentage=coverage_pct,
            deductible_applies=deductible_applies
        )
        
        procedure_breakdowns.append(breakdown)
        
        total_dentist_fees += breakdown.dentist_fee
        total_insurance_pays += breakdown.insurance_pays
        total_patient_pays += breakdown.patient_pays
        total_deductible_used += deductible_used
        
        deductible_remaining -= deductible_used
    
    remaining_annual_max = req.annual_max_remaining - total_insurance_pays
    
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
    DEMO ENDPOINT: Simulates saving benefits to Open Dental
    In production, this would write to Open Dental database
    """
    
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
    
    return OpenDentalSaveResponse(
        success=True,
        message=f"Successfully saved insurance benefits for {req.patient_name} to Open Dental",
        saved_fields=saved_fields
    )


# ============================================
# ERROR HANDLERS
# ============================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    print(f"Unexpected error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again."}
    )


# ============================================
# STARTUP
# ============================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)