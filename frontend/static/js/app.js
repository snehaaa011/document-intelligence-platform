// app.js -- vanilla JS frontend logic (case study sections 25-28, 48).
// No frameworks; talks to the FastAPI backend via API_BASE_URL so the
// frontend can be deployed separately from the backend.

const API_BASE = window.API_BASE_URL;

function showView(name) {
  document.getElementById("view-upload").classList.toggle("hidden", name !== "upload");
  document.getElementById("view-upload-result").classList.toggle("hidden", true);
  document.getElementById("view-dashboard").classList.toggle("hidden", name !== "dashboard");
  document.getElementById("view-result").classList.toggle("hidden", true);
  document.getElementById("tab-upload").classList.toggle("active", name === "upload");
  document.getElementById("tab-dashboard").classList.toggle("active", name === "dashboard");
  if (name === "dashboard") loadDashboard();
}

function setStage(stageName) {
  const stageList = document.getElementById("stage_list");
  stageList.classList.remove("hidden");
  const order = ["validating", "ocr", "extracting", "validation", "saving"];
  const idx = order.indexOf(stageName);
  order.forEach((s, i) => {
    const el = stageList.querySelector(`[data-stage="${s}"]`);
    el.classList.remove("active", "done");
    if (i < idx) el.classList.add("done");
    else if (i === idx) el.classList.add("active");
  });
}

async function processDocument() {
  const fileInput = document.getElementById("file_input");
  const documentType = document.getElementById("document_type").value;
  const errorBox = document.getElementById("upload_error");
  errorBox.classList.add("hidden");

  if (!fileInput.files.length) {
    errorBox.textContent = "Please choose a file first.";
    errorBox.classList.remove("hidden");
    return;
  }

  const btn = document.getElementById("process_btn");
  btn.disabled = true;
  setStage("validating");

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("document_type", documentType);

  // Simulate stage progression visually while the single request is
  // in flight (the backend does not stream intermediate stages).
  const stageTimers = [
    setTimeout(() => setStage("ocr"), 400),
    setTimeout(() => setStage("extracting"), 1200),
    setTimeout(() => setStage("validation"), 2200),
    setTimeout(() => setStage("saving"), 3000),
  ];

  try {
    const resp = await fetch(`${API_BASE}/api/v1/documents/process`, {
      method: "POST",
      body: formData,
    });
    const data = await resp.json();
    stageTimers.forEach(clearTimeout);
    document.getElementById("stage_list").classList.add("hidden");

    if (!resp.ok) {
      errorBox.textContent = data?.detail?.message || data?.error?.message || "Processing failed.";
      errorBox.classList.remove("hidden");
    } else {
      renderResult(data, "view-upload-result");
      document.getElementById("view-upload-result").classList.remove("hidden");
    }
  } catch (err) {
    stageTimers.forEach(clearTimeout);
    document.getElementById("stage_list").classList.add("hidden");
    errorBox.textContent = "Could not reach the API at " + API_BASE + ". Is the backend running?";
    errorBox.classList.remove("hidden");
  } finally {
    btn.disabled = false;
  }
}

async function loadDashboard() {
  try {
    const resp = await fetch(`${API_BASE}/api/v1/documents`);
    const data = await resp.json();
    const docs = data.documents || [];

    const passCount = docs.filter((d) => d.processing_status === "PASS").length;
    const failCount = docs.filter((d) => d.processing_status === "FAILED").length;

    document.getElementById("stat_grid").innerHTML = `
      <div class="stat-box"><div class="value">${data.total}</div><div class="label">Total processed</div></div>
      <div class="stat-box"><div class="value">${passCount}</div><div class="label">Passed</div></div>
      <div class="stat-box"><div class="value">${failCount}</div><div class="label">Failed</div></div>
      <div class="stat-box"><div class="value">${docs.length ? new Date(docs[0].created_at).toLocaleString() : "-"}</div><div class="label">Most recent</div></div>
    `;

    const tbody = document.getElementById("documents_table_body");
    tbody.innerHTML = "";
    docs.forEach((doc) => {
      const tr = document.createElement("tr");
      tr.className = "clickable";
      tr.innerHTML = `
        <td>${escapeHtml(doc.document_name)}</td>
        <td>${escapeHtml(doc.document_type)}</td>
        <td><span class="badge ${doc.processing_status}">${doc.processing_status}</span></td>
        <td>${new Date(doc.created_at).toLocaleString()}</td>
      `;
      tr.onclick = () => openDocument(doc.document_name);
      tbody.appendChild(tr);
    });
  } catch (err) {
    document.getElementById("documents_table_body").innerHTML =
      `<tr><td colspan="4">Could not reach the API at ${API_BASE}.</td></tr>`;
  }
}

async function openDocument(name) {
  const resp = await fetch(`${API_BASE}/api/v1/documents/${encodeURIComponent(name)}`);
  const data = await resp.json();
  renderResult(data, "view-result", true);
  document.getElementById("view-dashboard").classList.add("hidden");
  document.getElementById("view-result").classList.remove("hidden");
}

function backToDashboard() {
  document.getElementById("view-result").classList.add("hidden");
  showView("dashboard");
}

function fmtEvidence(ev) {
  if (!ev || ev.value === null || ev.value === undefined) {
    return `<div class="v null">Not available</div>`;
  }
  const evidenceLine = ev.source_text ? `<div class="evidence">"${escapeHtml(ev.source_text)}"${ev.page_number ? " (p." + ev.page_number + ")" : ""}</div>` : "";
  return `<div class="v">${ev.value}${ev.currency ? " " + ev.currency : ""}${ev.unit_scale ? " (" + ev.unit_scale + ")" : ""}</div>${evidenceLine}`;
}

function fieldBox(label, innerHtml) {
  return `<div class="field-item"><div class="k">${escapeHtml(label)}</div>${innerHtml}</div>`;
}

function renderResult(data, containerId, showBack = false) {
  const container = document.getElementById(containerId);
  const extracted = data.extracted_data || {};
  const isInvoice = data.document_type === "invoice";

  let html = "";
  if (showBack) html += `<div class="back-link" onclick="backToDashboard()">&larr; Back to dashboard</div>`;

  html += `<div class="card">
    <h2>${escapeHtml(data.document_name)}
      <span class="badge ${data.processing_status}" style="margin-left:10px;">${data.processing_status}</span>
    </h2>
    <div style="color:#64748b; font-size:13px;">
      Type: ${escapeHtml(data.document_type)} &middot;
      OCR used: ${data.processing_metadata?.ocr_used ? "yes" : "no"} &middot;
      Provider: ${escapeHtml(data.processing_metadata?.extraction_provider || "n/a")} &middot;
      ${data.processing_metadata?.processing_time_ms ?? 0} ms
      ${data.overall_confidence !== null && data.overall_confidence !== undefined ? " &middot; Confidence: " + (data.overall_confidence * 100).toFixed(1) + "%" : ""}
    </div>
  </div>`;

  if (data.error) {
    html += `<div class="error-box"><b>${escapeHtml(data.error.code)}:</b> ${escapeHtml(data.error.message)}</div>`;
  }

  // File validation
  const fv = data.file_validation || {};
  html += `<div class="card">
    <h2>File validation</h2>
    <div class="field-grid">
      ${fieldBox("Supported format", `<div class="v">${fv.is_supported_format ? "Yes" : "No"}</div>`)}
      ${fieldBox("Readable", `<div class="v">${fv.is_readable ? "Yes" : "No"}</div>`)}
      ${fieldBox("Within page limit", `<div class="v">${fv.is_within_page_limit ? "Yes" : "No"}</div>`)}
      ${fieldBox("File type", `<div class="v">${escapeHtml(fv.file_type || "-")}</div>`)}
      ${fieldBox("Page count", `<div class="v">${fv.page_count ?? "-"}</div>`)}
    </div>
    ${fv.errors && fv.errors.length ? `<div class="error-box">${fv.errors.map(escapeHtml).join("<br/>")}</div>` : ""}
  </div>`;

  // Extracted fields
  if (isInvoice && extracted.invoice_fields) {
    const f = extracted.invoice_fields;
    html += `<div class="card"><h2>Extracted invoice fields</h2><div class="field-grid">
      ${fieldBox("Vendor", `<div class="v ${f.vendor_name ? "" : "null"}">${escapeHtml(f.vendor_name || "Not available")}</div>`)}
      ${fieldBox("Invoice number", fmtEvidence(f.invoice_number))}
      ${fieldBox("Invoice date", fmtEvidence(f.invoice_date))}
      ${fieldBox("Due date", fmtEvidence(f.due_date))}
      ${fieldBox("Subtotal", fmtEvidence(f.subtotal))}
      ${fieldBox("Tax amount", fmtEvidence(f.tax_amount))}
      ${fieldBox("Discount", fmtEvidence(f.discount_amount))}
      ${fieldBox("Total amount", fmtEvidence(f.total_amount))}
      ${fieldBox("Cash tendered", fmtEvidence(f.cash_tendered))}
      ${fieldBox("Change returned", fmtEvidence(f.change_returned))}
      ${fieldBox("Vendor Tax ID", `<div class="v ${f.vendor_tax_id ? "" : "null"}">${escapeHtml(f.vendor_tax_id || "Not available")}</div>`)}
    </div></div>`;

    if (extracted.invoice_line_items && extracted.invoice_line_items.length) {
      html += `<div class="card"><h2>Line items</h2><table><thead><tr>
        <th>Description</th><th>HSN/SAC</th><th>Qty</th><th>Unit price</th><th>Tax rate</th><th>Line total</th>
      </tr></thead><tbody>`;
      extracted.invoice_line_items.forEach((li) => {
        html += `<tr>
          <td>${escapeHtml(li.description || "-")}</td>
          <td>${escapeHtml(li.hsn_sac || "-")}</td>
          <td>${li.quantity?.value ?? "-"}</td>
          <td>${li.unit_price?.value ?? "-"}</td>
          <td>${li.tax_rate?.value ?? "-"}</td>
          <td>${li.line_total?.value ?? "-"}</td>
        </tr>`;
      });
      html += `</tbody></table></div>`;
    }
  } else if (extracted.statement_line_items) {
    html += `<div class="card"><h2>Extracted line items (periods: ${(extracted.periods || []).map(escapeHtml).join(", ") || "n/a"})</h2>
      <table><thead><tr><th>Section</th><th>Field</th><th>Canonical</th>${(extracted.periods || []).map((p) => `<th>${escapeHtml(p)}</th>`).join("")}</tr></thead><tbody>`;
    extracted.statement_line_items.forEach((item) => {
      const periodMap = {};
      (item.periods || []).forEach((p) => (periodMap[p.label] = p.evidence?.value));
      html += `<tr>
        <td>${escapeHtml(item.section || "-")}</td>
        <td>${escapeHtml(item.field_name)}</td>
        <td>${escapeHtml(item.canonical_name || "-")}</td>
        ${(extracted.periods || []).map((p) => `<td>${periodMap[p] ?? "-"}</td>`).join("")}
      </tr>`;
    });
    html += `</tbody></table></div>`;
  }

  if (extracted.additional_fields && Object.keys(extracted.additional_fields).length) {
    html += `<div class="card"><h2>Additional fields</h2><div class="field-grid">
      ${Object.entries(extracted.additional_fields).map(([k, v]) => fieldBox(k, `<div class="v">${escapeHtml(String(v))}</div>`)).join("")}
    </div></div>`;
  }

  // Validation
  if (data.validation) {
    html += `<div class="card"><h2>Financial validation
      <span class="badge ${data.validation.overall_status}" style="margin-left:10px;">${data.validation.overall_status}</span></h2>
      <table><thead><tr><th>Check</th><th>Formula</th><th>Calculated</th><th>Reported</th><th>Tolerance</th><th>Status</th></tr></thead><tbody>`;
    (data.validation.checks || []).forEach((c) => {
      html += `<tr>
        <td>${escapeHtml(c.name)}${c.period_label ? "<br/><small>" + escapeHtml(c.period_label) + "</small>" : ""}</td>
        <td><small>${escapeHtml(c.formula)}</small></td>
        <td>${c.calculated_value ?? "-"}</td>
        <td>${c.reported_value ?? "-"}</td>
        <td>${c.tolerance ?? "-"}</td>
        <td><span class="badge ${c.status}">${c.status}</span></td>
      </tr>`;
    });
    html += `</tbody></table>
      ${data.validation.issues && data.validation.issues.length ? `<div class="error-box">${data.validation.issues.map(escapeHtml).join("<br/>")}</div>` : ""}
    </div>`;
  }

  if (extracted.extraction_warnings && extracted.extraction_warnings.length) {
    html += `<div class="card"><h2>Extraction notes</h2>${extracted.extraction_warnings.map((w) => `<div>${escapeHtml(w)}</div>`).join("")}</div>`;
  }

  // Raw JSON
  html += `<div class="card"><h2>Raw JSON</h2><pre class="json-view">${escapeHtml(JSON.stringify(data, null, 2))}</pre></div>`;

  container.innerHTML = html;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
