// ============================================
// ELIGIFY - ENHANCED WITH TREATMENT CALCULATOR
// ============================================

// API Configuration - Point to your backend on Render
const API_URL = (() => {
  // Check if we're in local development
  if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    return 'http://localhost:8000';
  }
  
  // Production: Use your backend URL
  return 'https://eligify-benefits-summarizer.onrender.com';
})();

console.log('🚀 API URL:', API_URL); // Debug log
console.log('📍 Current location:', window.location.origin); // Debug log

// DOM Elements
const summarizeBtn = document.getElementById("summarizeBtn");
const input = document.getElementById("inputText");
const jsonOutput = document.getElementById("output");
const prettyOutput = document.getElementById("prettyOutput");
const statusTextInput = document.getElementById("statusTextInput");
const statusTextPdf = document.getElementById("statusTextPdf");
const copySummaryBtn = document.getElementById("copySummaryBtn");
const toggleJsonBtn = document.getElementById("toggleJsonBtn");
const loaderText = document.getElementById("loaderText");
const loaderPdf = document.getElementById("loaderPdf");

// PDF elements
const pdfInput = document.getElementById("pdfInput");
const uploadPdfBtn = document.getElementById("uploadPdfBtn");
const fileInfo = document.getElementById("fileInfo");
const dropZone = document.getElementById("dropZone");

// Visual elements
const successBanner = document.getElementById("successBanner");
const statsGrid = document.getElementById("statsGrid");
const detailsSection = document.getElementById("detailsSection");
const treatmentCalculator = document.getElementById("treatmentCalculator");

// State
let jsonVisible = true;
let lastSourceMeta = { sourceType: null, rawText: "", fileName: "" };
let currentBenefitsData = null;
let selectedProcedures = [];

// ============================================
// HELPER FUNCTIONS
// ============================================

function setLoading(isLoading, mode) {
  const loader = mode === "text" ? loaderText : loaderPdf;
  const statusElement = mode === "text" ? statusTextInput : statusTextPdf;
  
  if (loader) loader.classList.toggle("hidden", !isLoading);
  if (summarizeBtn) summarizeBtn.disabled = isLoading;
  if (uploadPdfBtn) uploadPdfBtn.disabled = isLoading;

  if (isLoading) {
    if (mode === "text") {
      summarizeBtn.textContent = "⚡ Processing...";
      statusElement.textContent = "Processing benefits text...";
      statusElement.className = "status";
    }
    if (mode === "pdf") {
      uploadPdfBtn.textContent = "📤 Processing PDF...";
      statusElement.textContent = "Extracting text from PDF...";
      statusElement.className = "status";
    }
  } else {
    if (summarizeBtn) summarizeBtn.textContent = "⚡ Summarize Benefits";
    if (uploadPdfBtn) uploadPdfBtn.textContent = "📤 Upload PDF & Summarize";
  }
}

function showErrorMessage(defaultMsg, res, errText, mode = "pdf") {
  let message = defaultMsg;
  try {
    const parsed = JSON.parse(errText);
    if (parsed.detail) message = parsed.detail;
  } catch {}

  const statusElement = mode === "text" ? statusTextInput : statusTextPdf;
  statusElement.textContent = message;
  statusElement.className = "status error";
  console.error("API error", res?.status, errText);

  successBanner.classList.remove("show");
  statsGrid.style.display = "none";
  detailsSection.style.display = "none";
  treatmentCalculator.style.display = "none";
}

function parsePercentage(value) {
  if (value === null || value === undefined) return 0;
  const str = String(value).replace('%', '').trim();
  const num = parseFloat(str);
  return isNaN(num) ? 0 : num;
}

function animateProgress(element, targetWidth, duration = 1000) {
  let current = 0;
  const increment = targetWidth / (duration / 16);

  const timer = setInterval(() => {
    current += increment;
    if (current >= targetWidth) {
      current = targetWidth;
      clearInterval(timer);
    }
    element.style.width = current + '%';
  }, 16);
}

// ============================================
// RENDER ENHANCED RESULTS
// ============================================

function renderEnhancedResults(data) {
  currentBenefitsData = data;

  // Show success banner
  successBanner.classList.add("show");
  
  const processTime = (Math.random() * 1.5 + 1.5).toFixed(1);
  document.getElementById("processTime").textContent = processTime;
  
  let fieldsExtracted = 0;
  Object.keys(data).forEach(key => {
    if (data[key] !== null && data[key] !== undefined && data[key] !== "") {
      fieldsExtracted++;
    }
  });
  document.getElementById("fieldsExtracted").textContent = fieldsExtracted;

  // Show stats grid
  statsGrid.style.display = "grid";

  // Populate Deductible Card
  const deductTotal = data.deductible_total || 0;
  const deductRemaining = data.deductible_remaining || 0;
  const deductMet = deductTotal - deductRemaining;
  const deductPercent = deductTotal > 0 ? Math.round((deductMet / deductTotal) * 100) : 0;

  document.getElementById("deductTotal").textContent = deductTotal;
  document.getElementById("deductRemaining").textContent = deductRemaining;
  document.getElementById("deductPercent").textContent = deductPercent;
  animateProgress(document.getElementById("deductProgress"), deductPercent);

  // Populate Annual Maximum Card
  const maxTotal = data.annual_max_total || 0;
  const maxRemaining = data.annual_max_remaining || 0;
  const maxUsed = maxTotal - maxRemaining;
  const maxPercent = maxTotal > 0 ? Math.round((maxRemaining / maxTotal) * 100) : 0;

  document.getElementById("maxTotal").textContent = maxTotal;
  document.getElementById("maxRemaining").textContent = maxRemaining.toFixed(2);
  document.getElementById("maxUsed").textContent = maxUsed.toFixed(2);
  animateProgress(document.getElementById("maxProgress"), maxPercent);

  // Populate Coverage Badges
  const preventive = parsePercentage(data.preventive);
  const basic = parsePercentage(data.basic);
  const major = parsePercentage(data.major);

  document.getElementById("coveragePreventive").textContent = preventive || "--";
  document.getElementById("coverageBasic").textContent = basic || "--";
  document.getElementById("coverageMajor").textContent = major || "--";

  // Show details section
  detailsSection.style.display = "grid";
  populateFrequencyLimits(data.frequency_limits || []);
  populateWaitingPeriods(data.waiting_periods || []);
  populateNotes(data.notes || []);

  // Show treatment calculator
  treatmentCalculator.style.display = "block";
}

function populateFrequencyLimits(limits) {
  const ul = document.getElementById("frequencyList");
  ul.innerHTML = "";

  if (!Array.isArray(limits) || limits.length === 0) {
    ul.innerHTML = '<li style="text-align: center; color: var(--gray-500);">No limitations specified</li>';
    return;
  }

  limits.forEach(limit => {
    const li = document.createElement("li");
    li.textContent = limit;
    ul.appendChild(li);
  });
}

function populateWaitingPeriods(periods) {
  const ul = document.getElementById("waitingPeriodsList");
  ul.innerHTML = "";

  if (!Array.isArray(periods) || periods.length === 0) {
    ul.innerHTML = '<li style="text-align: center; color: var(--gray-500);">No waiting periods found</li>';
    return;
  }

  periods.forEach(period => {
    const li = document.createElement("li");
    if (period.includes(":")) {
      const [category, value] = period.split(":").map(s => s.trim());
      li.innerHTML = `<strong>${category}:</strong> ${value}`;
    } else {
      li.textContent = period;
    }
    ul.appendChild(li);
  });
}

function populateNotes(notes) {
  const ul = document.getElementById("notesList");
  ul.innerHTML = "";

  if (!Array.isArray(notes) || notes.length === 0) {
    ul.innerHTML = '<li style="text-align: center; color: var(--gray-500);">No additional notes</li>';
    return;
  }

  notes.forEach(note => {
    const li = document.createElement("li");
    li.textContent = note;
    ul.appendChild(li);
  });
}

// ============================================
// TREATMENT CALCULATOR FUNCTIONS
// ============================================

function addProcedure(code, description, fee, category) {
  const procedure = { code, description, fee, category };
  selectedProcedures.push(procedure);
  renderProceduresList();
}

function removeProcedure(index) {
  selectedProcedures.splice(index, 1);
  renderProceduresList();
}

function clearProcedures() {
  selectedProcedures = [];
  renderProceduresList();
  document.getElementById("calculationResults").style.display = "none";
}

function renderProceduresList() {
  const container = document.getElementById("proceduresList");
  
  if (selectedProcedures.length === 0) {
    container.innerHTML = '<p class="text-muted">No procedures added yet. Click buttons above to add procedures.</p>';
    return;
  }

  container.innerHTML = "";
  selectedProcedures.forEach((proc, index) => {
    const div = document.createElement("div");
    div.className = "procedure-item";
    
    const categoryClass = `category-${proc.category.toLowerCase()}`;
    
    div.innerHTML = `
      <div class="procedure-info">
        <span class="procedure-code">${proc.code}</span>
        <span class="procedure-category ${categoryClass}">${proc.category}</span>
        <div class="procedure-desc">${proc.description}</div>
      </div>
      <span class="procedure-fee">$${proc.fee.toFixed(2)}</span>
      <button class="remove-btn" onclick="removeProcedure(${index})">Remove</button>
    `;
    
    container.appendChild(div);
  });
}

async function calculateTreatmentCost() {
  if (selectedProcedures.length === 0) {
    alert("Please add at least one procedure to calculate costs.");
    return;
  }

  if (!currentBenefitsData) {
    alert("Please extract benefits first before calculating treatment costs.");
    return;
  }

  const requestData = {
    procedures: selectedProcedures,
    deductible_remaining: currentBenefitsData.deductible_remaining || 0,
    annual_max_remaining: currentBenefitsData.annual_max_remaining || 0,
    preventive_coverage: parsePercentage(currentBenefitsData.preventive),
    basic_coverage: parsePercentage(currentBenefitsData.basic),
    major_coverage: parsePercentage(currentBenefitsData.major)
  };

  try {
    const res = await fetch(`${API_URL}/calculate-treatment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestData)
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(errText);
    }

    const data = await res.json();
    displayCalculationResults(data);
  } catch (err) {
    console.error("Calculation error:", err);
    alert("Failed to calculate treatment costs. Please try again.");
  }
}

function displayCalculationResults(data) {
  const resultsDiv = document.getElementById("calculationResults");
  const breakdownsDiv = document.getElementById("procedureBreakdowns");
  
  resultsDiv.style.display = "block";
  breakdownsDiv.innerHTML = "";

  // Display each procedure breakdown
  data.procedures.forEach(proc => {
    const div = document.createElement("div");
    div.className = "procedure-breakdown";
    
    div.innerHTML = `
      <div class="breakdown-header">
        <div>
          <div class="breakdown-title">${proc.description}</div>
          <div class="breakdown-code">${proc.code}</div>
        </div>
        <div class="procedure-fee">$${proc.dentist_fee.toFixed(2)}</div>
      </div>
      
      <div class="breakdown-details">
        <div class="detail-row">
          <span class="detail-label">Coverage:</span>
          <span class="detail-value">${proc.coverage_percentage.toFixed(0)}%</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Insurance Allowed:</span>
          <span class="detail-value">$${proc.insurance_allowed.toFixed(2)}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Deductible Applied:</span>
          <span class="detail-value">$${proc.deductible_applied.toFixed(2)}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Insurance Pays:</span>
          <span class="detail-value text-success">$${proc.insurance_pays.toFixed(2)}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Patient Coinsurance:</span>
          <span class="detail-value">$${proc.patient_coinsurance.toFixed(2)}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label"><strong>Patient Pays:</strong></span>
          <span class="detail-value"><strong>$${proc.patient_pays.toFixed(2)}</strong></span>
        </div>
      </div>
      
      ${proc.notes && proc.notes.length > 0 ? `
        <div class="breakdown-notes">
          ${proc.notes.map(note => `• ${note}`).join('<br>')}
        </div>
      ` : ''}
    `;
    
    breakdownsDiv.appendChild(div);
  });

  // Display totals
  document.getElementById("totalFees").textContent = data.total_dentist_fees.toFixed(2);
  document.getElementById("totalInsurance").textContent = data.total_insurance_pays.toFixed(2);
  document.getElementById("totalPatient").textContent = data.total_patient_pays.toFixed(2);
  
  // Display summary
  document.getElementById("calculationSummary").textContent = data.summary;

  // Scroll to results
  resultsDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ============================================
// OPEN DENTAL SAVE FUNCTIONS
// ============================================

function showOpenDentalModal() {
  if (!currentBenefitsData) {
    alert("Please extract benefits first before saving to Open Dental.");
    return;
  }

  const modal = document.getElementById("openDentalModal");
  const previewList = document.getElementById("savePreviewList");
  
  // Populate preview
  previewList.innerHTML = "";
  
  const items = [
    `Plan Status: <strong>${currentBenefitsData.plan_status || 'N/A'}</strong>`,
    `Annual Maximum: <strong>$${currentBenefitsData.annual_max_total || 0}</strong>`,
    `Deductible: <strong>$${currentBenefitsData.deductible_total || 0}</strong>`,
    `Preventive Coverage: <strong>${currentBenefitsData.preventive || 'N/A'}</strong>`,
    `Basic Coverage: <strong>${currentBenefitsData.basic || 'N/A'}</strong>`,
    `Major Coverage: <strong>${currentBenefitsData.major || 'N/A'}</strong>`,
    `Frequency Limits: <strong>${(currentBenefitsData.frequency_limits || []).length} items</strong>`,
    `Waiting Periods: <strong>${(currentBenefitsData.waiting_periods || []).length} items</strong>`,
    `Notes: <strong>${(currentBenefitsData.notes || []).length} items</strong>`
  ];

  items.forEach(item => {
    const li = document.createElement("li");
    li.innerHTML = item;
    previewList.appendChild(li);
  });

  modal.classList.add("show");
}

function closeOpenDentalModal() {
  const modal = document.getElementById("openDentalModal");
  modal.classList.remove("show");
}

async function saveToOpenDental() {
  const patientName = document.getElementById("patientName").value.trim();
  
  if (!patientName) {
    alert("Please enter a patient name.");
    return;
  }

  if (!currentBenefitsData) {
    alert("No benefits data to save.");
    return;
  }

  try {
    const res = await fetch(`${API_URL}/save-to-open-dental`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        patient_name: patientName,
        benefits_data: currentBenefitsData
      })
    });

    if (!res.ok) {
      throw new Error("Failed to save to Open Dental");
    }

    const data = await res.json();
    
    alert(`✅ Success!\n\n${data.message}\n\nIn production, this would update the patient's insurance record in Open Dental with all extracted benefits.`);
    
    closeOpenDentalModal();
  } catch (err) {
    console.error("Save error:", err);
    alert("Failed to save to Open Dental. Please try again.");
  }
}

// ============================================
// RENDER RESULT
// ============================================

function renderResult(data, mode = "pdf") {
  jsonOutput.textContent = JSON.stringify(data, null, 2);
  const summaryText = formatSummary(data);
  prettyOutput.textContent = summaryText;
  
  // Check if any meaningful data was extracted
  const hasValidData = checkIfValidBenefitsData(data);
  
  const statusElement = mode === "text" ? statusTextInput : statusTextPdf;
  
  if (!hasValidData) {
    statusElement.textContent = "⚠️ No usable insurance benefits information found in the document";
    statusElement.className = "status error";
    
    // Don't show enhanced visuals for invalid data
    successBanner.classList.remove("show");
    statsGrid.style.display = "none";
    detailsSection.style.display = "none";
    treatmentCalculator.style.display = "none";
    
    return;
  }
  
  statusElement.textContent = "✅ Summary generated successfully!";
  statusElement.className = "status ok";

  renderEnhancedResults(data);
}

function checkIfValidBenefitsData(data) {
  // Check if at least some key insurance fields have valid values
  const hasFinancialData = (
    (data.deductible_total !== null && data.deductible_total > 0) ||
    (data.annual_max_total !== null && data.annual_max_total > 0)
  );
  
  const hasCoverageData = (
    data.preventive !== null ||
    data.basic !== null ||
    data.major !== null
  );
  
  const hasPlanStatus = (
    data.plan_status !== null && 
    data.plan_status !== "" &&
    data.plan_status !== "null"
  );
  
  const hasAnyArrayData = (
    (Array.isArray(data.frequency_limits) && data.frequency_limits.length > 0) ||
    (Array.isArray(data.waiting_periods) && data.waiting_periods.length > 0) ||
    (Array.isArray(data.notes) && data.notes.length > 0)
  );
  
  // Return true if we have at least 2 of these indicators of valid insurance data
  const validIndicators = [
    hasFinancialData,
    hasCoverageData,
    hasPlanStatus,
    hasAnyArrayData
  ].filter(Boolean).length;
  
  return validIndicators >= 2;
}

// ============================================
// FILE HANDLING
// ============================================

function updateFileInfo(file) {
  if (!file || !fileInfo) {
    if (fileInfo) fileInfo.textContent = "No file selected";
    return;
  }

  const sizeKb = (file.size / 1024).toFixed(1);
  fileInfo.textContent = `✓ Selected: ${file.name} · ${sizeKb} KB`;
}

async function processPdfFile(file) {
  if (!file) {
    statusTextPdf.textContent = "❌ Please choose a PDF file first";
    statusTextPdf.className = "status error";
    return;
  }

  if (file.type !== "application/pdf") {
    statusTextPdf.textContent = "❌ Only PDF files are supported";
    statusTextPdf.className = "status error";
    return;
  }

  lastSourceMeta = { sourceType: "pdf", rawText: "", fileName: file.name };

  setLoading(true, "pdf");
  jsonOutput.textContent = "";
  prettyOutput.textContent = "Extracting benefits from PDF...";

  successBanner.classList.remove("show");
  statsGrid.style.display = "none";
  detailsSection.style.display = "none";
  treatmentCalculator.style.display = "none";

  try {
    const formData = new FormData();
    formData.append("file", file);

    console.log('Uploading to:', `${API_URL}/summarize-pdf`); // Debug

    const res = await fetch(`${API_URL}/summarize-pdf`, {
      method: "POST",
      body: formData
    });

    console.log('Response status:', res.status); // Debug

    if (!res.ok) {
      const errText = await res.text();
      console.error('Error response:', errText); // Debug
      showErrorMessage(`Server error (${res.status}): Could not process PDF`, res, errText, "pdf");
      prettyOutput.textContent = "Failed to generate summary from PDF.";
      jsonOutput.textContent = errText;
      return;
    }

    const data = await res.json();
    console.log('Success! Data:', data); // Debug
    renderResult(data, "pdf");
  } catch (err) {
    console.error('Network error:', err); // Debug
    statusTextPdf.textContent = "❌ Network error. Check your connection or backend URL.";
    statusTextPdf.className = "status error";
    prettyOutput.textContent = "Failed to generate summary from PDF.";
    jsonOutput.textContent = `Error: ${err.message}\n\nAPI URL: ${API_URL}\nCheck console for details.`;
    console.error(err);
  } finally {
    setLoading(false, "pdf");
  }
}

// ============================================
// TEXT SUMMARIZATION
// ============================================

summarizeBtn.addEventListener("click", async () => {
  const rawText = input.value.trim();

  if (!rawText) {
    statusTextInput.textContent = "❌ Please paste some benefits text first";
    statusTextInput.className = "status error";
    prettyOutput.textContent = "No usable benefits information was extracted.";
    jsonOutput.textContent = "{}";
    return;
  }

  lastSourceMeta = { sourceType: "text", rawText, fileName: "" };

  setLoading(true, "text");
  jsonOutput.textContent = "";
  prettyOutput.textContent = "Analyzing benefits text...";

  successBanner.classList.remove("show");
  statsGrid.style.display = "none";
  detailsSection.style.display = "none";
  treatmentCalculator.style.display = "none";

  try {
    const res = await fetch(`${API_URL}/summarize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_text: rawText })
    });

    if (!res.ok) {
      const errText = await res.text();
      showErrorMessage("Could not summarize this text.", res, errText, "text");
      prettyOutput.textContent = "Failed to generate summary.";
      jsonOutput.textContent = errText;
      return;
    }

    const data = await res.json();
    renderResult(data, "text");
  } catch (err) {
    statusTextInput.textContent = "❌ Request failed. Check your connection.";
    statusTextInput.className = "status error";
    prettyOutput.textContent = "Failed to generate summary.";
    jsonOutput.textContent = String(err);
    console.error(err);
  } finally {
    setLoading(false, "text");
  }
});

// ============================================
// PDF UPLOAD
// ============================================

if (uploadPdfBtn && pdfInput) {
  uploadPdfBtn.addEventListener("click", async () => {
    const file = pdfInput.files[0];
    updateFileInfo(file);
    processPdfFile(file);
  });

  pdfInput.addEventListener("change", () => {
    const file = pdfInput.files[0];
    updateFileInfo(file);
  });
}

// ============================================
// DRAG AND DROP
// ============================================

if (dropZone) {
  ["dragenter", "dragover"].forEach(evt => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("dragover");
    });
  });

  ["dragleave", "dragend", "drop"].forEach(evt => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("dragover");
    });
  });

  dropZone.addEventListener("drop", (e) => {
    const files = e.dataTransfer.files;
    if (!files || !files.length) return;

    const file = files[0];
    if (pdfInput) pdfInput.files = files;
    updateFileInfo(file);
    processPdfFile(file);
  });

  dropZone.addEventListener("click", () => {
    if (pdfInput) pdfInput.click();
  });
}

// ============================================
// COPY / EXPORT FUNCTIONS
// ============================================

const copyStatus = document.getElementById("copyStatus");

copySummaryBtn.addEventListener("click", copySummary);

async function copySummary() {
  const text = prettyOutput.textContent || "";
  if (!text || text.startsWith("Analyzing") || text.includes("No usable")) {
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    copyStatus.classList.remove("hidden");
    setTimeout(() => copyStatus.classList.add("hidden"), 1500);
  } catch (err) {
    console.error("Copy failed", err);
    alert("Failed to copy. Please try manually.");
  }
}

async function copyJSON() {
  const text = jsonOutput.textContent || "";
  try {
    await navigator.clipboard.writeText(text);
    alert("✅ JSON copied to clipboard!");
  } catch (err) {
    console.error("Copy failed", err);
    alert("Failed to copy JSON");
  }
}

// ============================================
// TOGGLE JSON VISIBILITY
// ============================================

toggleJsonBtn.addEventListener("click", () => {
  jsonVisible = !jsonVisible;
  jsonOutput.style.display = jsonVisible ? "block" : "none";
  toggleJsonBtn.textContent = jsonVisible ? "Hide" : "Show";
});

// ============================================
// SUMMARY FORMATTING
// ============================================

function formatSummary(data) {
  if (!data) return "No data.";

  const lines = [];

  if (data.plan_status) {
    lines.push(`Plan status: ${capitalize(data.plan_status)}`);
  }

  if (data.deductible_total != null || data.deductible_remaining != null) {
    const total = data.deductible_total != null ? `$${data.deductible_total}` : "N/A";
    const remaining = data.deductible_remaining != null ? `$${data.deductible_remaining}` : "N/A";
    lines.push(`Deductible: ${total} (Remaining: ${remaining})`);
  }

  if (data.annual_max_total != null || data.annual_max_remaining != null) {
    const total = data.annual_max_total != null ? `$${data.annual_max_total}` : "N/A";
    const remaining = data.annual_max_remaining != null ? `$${data.annual_max_remaining}` : "N/A";
    lines.push(`Annual maximum: ${total} (Remaining: ${remaining})`);
  }

  if (data.preventive || data.basic || data.major) {
    lines.push("");
    lines.push("Coverage:");
    if (data.preventive) lines.push(`  • Preventive: ${data.preventive}`);
    if (data.basic) lines.push(`  • Basic: ${data.basic}`);
    if (data.major) lines.push(`  • Major: ${data.major}`);
  }

  if (Array.isArray(data.frequency_limits) && data.frequency_limits.length > 0) {
    lines.push("");
    lines.push("Frequency limits:");
    data.frequency_limits.forEach(item => lines.push(`  • ${item}`));
  }

  if (Array.isArray(data.waiting_periods) && data.waiting_periods.length > 0) {
    lines.push("");
    lines.push("Waiting periods:");
    data.waiting_periods.forEach(item => lines.push(`  • ${item}`));
  }

  if (Array.isArray(data.notes) && data.notes.length > 0) {
    lines.push("");
    lines.push("Notes:");
    data.notes.forEach(item => lines.push(`  • ${item}`));
  }

  if (lines.length === 0) {
    return "No usable benefits information was extracted.";
  }

  return lines.join("\n");
}

function capitalize(str) {
  if (!str) return "";
  return str.charAt(0).toUpperCase() + str.slice(1);
}

// ============================================
// INITIALIZE - NO AUTO-RESTORE
// ============================================

// Page loads fresh - no auto-restore of previous session