# Document Intelligence Platform

An end-to-end AI-powered Document Intelligence system built for an AI Engineer Internship technical assessment. It ingests invoices, balance sheets, profit & loss statements, and cash flow statements (PDF/JPG/PNG), runs OCR + AI/rule-based extraction, performs deterministic financial validation, persists every result, and exposes everything through a REST API and a small dashboard.

---

## 1. Problem Statement

Financial back-offices receive documents (invoices, financial statements) in inconsistent, often scanned or photographed formats. Manually re-keying these into structured data is slow and error-prone.

The goal of this project is to automatically:

1. Accept an uploaded document + its declared type.
2. Validate the file, OCR it if needed, and extract meaningful visible fields into structured JSON, without hallucinating values that are not actually on the page.
3. Run deterministic financial-formula validation against the extracted numbers, understanding units, comparative periods, and negative/bracketed values.
4. Persist every result and expose it through a REST API and dashboard.

The system supports exactly four document types (selected explicitly by the caller, not auto-classified):

- `invoice`
- `balance_sheet`
- `profit_and_loss`
- `cash_flow_statement`

---

## 2. Solution Overview

```text
Upload
   |
   v
File Validation
   |
   v
Native Text Detection
   |
   +---- usable native text ----+
   |                            |
   +---- scanned/insufficient --+
                |
                v
               OCR
                |
                v
      AI / Rule-based Extraction
                |
                v
       Structured JSON + Evidence
                |
                v
      Deterministic Validation
                |
                v
          Confidence Score
                |
                v
            Persistence
                |
                v
       REST API + Dashboard
```

Document type selection is performed explicitly by the frontend/API caller. Automatic document classification is outside the assessment scope.

---

## 3. Architecture

![Architecture](docs/architecture.png)

```text
project-root/
├── backend/
│   ├── app/
│   │   ├── main.py                         FastAPI app entrypoint
│   │   ├── api/routes/documents.py         REST endpoints
│   │   ├── core/
│   │   │   ├── config.py                   Application configuration
│   │   │   ├── database.py                 SQLAlchemy database setup
│   │   │   └── logging.py                  Application logging
│   │   ├── models/
│   │   │   └── document.py                 SQLAlchemy ORM model
│   │   ├── schemas/
│   │   │   ├── document.py                 API contracts
│   │   │   └── extraction.py               Extraction contracts
│   │   ├── services/
│   │   │   ├── document_validation_service.py
│   │   │   ├── ocr_service.py
│   │   │   ├── extraction_service.py
│   │   │   ├── financial_validation_service.py
│   │   │   └── document_service.py         Pipeline orchestrator
│   │   ├── providers/
│   │   │   ├── ocr_providers.py            OCR provider abstraction
│   │   │   └── extraction_providers.py     LLM/fallback providers
│   │   ├── prompts/                         Document-specific prompts
│   │   ├── repositories/
│   │   │   └── document_repository.py      Persistence abstraction
│   │   └── utils/
│   │       ├── number_parser.py
│   │       ├── image_utils.py
│   │       └── evidence_utils.py
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html
│   └── static/
│       ├── css/
│       │   └── style.css
│       └── js/
│           └── app.js
├── docs/
│   └── architecture.png
├── sample_outputs/
│   ├── balance_sheet.json
│   ├── cash_flow_statement.json
│   ├── invoice.json
│   ├── invoice_noisy_photographed.json
│   └── profit_and_loss.json
├── .env.example
├── .gitignore
├── docker-compose.yml
└── README.md
```

Clean separation is maintained between API, OCR, extraction, validation, persistence, frontend, configuration, and tests.

---

## 4. Technology Stack & Why

| Layer | Choice | Why |
|---|---|---|
| API framework | **FastAPI** | Async-friendly, automatic OpenAPI/Swagger documentation, native Pydantic integration, and minimal boilerplate for an assessment project. |
| Validation/schemas | **Pydantic v2** | Enforces structured request, response, and extraction contracts and prevents malformed data from silently propagating. |
| OCR | **Tesseract** via `pytesseract` | Free, local, no API key/network dependency, and suitable for scanned documents and the supplied dataset. |
| PDF handling | **Poppler utilities** | Used for native text extraction, page counting, and rendering PDF pages for OCR. |
| Image preprocessing | **OpenCV + Pillow** | Provides orientation correction, denoising, contrast enhancement, and sharpening for difficult scans/photos. |
| Semantic extraction | **Google Gemini + deterministic rule-based fallback** | Gemini is the intended semantic extraction path, while the fallback keeps the complete pipeline usable without an external API key. |
| Validation math | **Plain deterministic Python** | Financial correctness must be reproducible and auditable and therefore is not delegated to an LLM. |
| Database | **SQLite (dev) / PostgreSQL (prod)** via SQLAlchemy | SQLite provides zero-setup local development while PostgreSQL provides persistent production storage. |
| Frontend | **Vanilla HTML/CSS/JS** | No build step, simple deployment, and easy to explain during an interview. |
| Deployment | **Docker + Render** | Provides a reproducible runtime with Tesseract, Poppler, FastAPI, and PostgreSQL connectivity. |

---

## 5. OCR Approach

The OCR pipeline was designed to support native PDFs, flattened/scanned PDFs, and image-based documents.

### 5.1 Native Text Detection

For PDFs, each page's native text layer is checked first using:

```bash
pdftotext -layout
```

If the extracted native text contains fewer than 40 characters, the page is treated as scanned/flattened and OCR is performed.

This avoids unnecessary OCR when a usable text layer exists.

### 5.2 PDF Rendering and OCR

Pages requiring OCR are rasterized using Poppler and passed to Tesseract.

The current deployed configuration uses:

```text
OCR_DPI=300
```

### 5.3 Image Preprocessing

The preprocessing pipeline in `utils/image_utils.py` performs:

- EXIF orientation correction
- image-size inspection
- blur estimation
- conservative contrast enhancement
- denoising for difficult images
- sharpening where appropriate

### 5.4 Row Reconstruction from Word Bounding Boxes

The implementation uses Tesseract's `image_to_data` output to reconstruct tabular rows from word bounding boxes:

1. Words are clustered by vertical position.
2. Words within each row are sorted left-to-right.
3. The reconstructed row is passed to the extraction layer.

This improves label/value alignment for financial statements.

### 5.5 OCR Confidence

Tesseract word confidence is retained and contributes to the optional explainable confidence score. Each page also records whether OCR was used.

---

## 6. AI / LLM Extraction Approach

`providers/extraction_providers.py` defines an `ExtractionProvider` abstraction with two implementations:

- `LLMExtractionProvider`
- `RuleBasedExtractionProvider`

### 6.1 LLMExtractionProvider

The implementation uses **Google Gemini through Google's OpenAI-compatible API endpoint**:

```text
https://generativelanguage.googleapis.com/v1beta/openai/
```

The Python `openai` package is used only as a generic protocol-compatible REST client. It is configured with Google's Gemini endpoint and a Gemini API key.

The application does **not** use OpenAI's API service.

The provider:

1. Selects the document-type-specific prompt.
2. Builds the extraction prompt from OCR/native text.
3. Requests structured JSON output.
4. Parses and validates the response using the shared Pydantic model.
5. Retries transient failures using bounded retry/backoff logic.
6. Converts persistent provider errors into controlled application errors.

Document-specific prompts are stored under `backend/app/prompts/`.

### 6.2 RuleBasedExtractionProvider

The rule-based provider is a deterministic fallback that operates over native/OCR text using regular expressions and layout heuristics.

It is automatically selected when:

- `LLM_API_KEY` is empty
- `LLM_PROVIDER=rule_based`
- the LLM client is unavailable
- the provider cannot safely initialize the Gemini path

Every fallback response contains an explicit `extraction_warnings` message indicating reduced-coverage fallback logic.

### 6.3 Provider Selection

| `LLM_PROVIDER` | `LLM_API_KEY` | Effective Provider |
|---|---|---|
| `gemini` | set | Gemini |
| `gemini` | empty | Rule-based fallback |
| `rule_based` | irrelevant | Rule-based |
| unsupported/unset | irrelevant | Safe rule-based fallback |

The health endpoint reports both `llm_provider` and `llm_provider_effective`.

### 6.4 Current Public Deployment

The public assessment deployment is configured with:

```text
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
```

but no Gemini API key is stored in the deployment environment.

Therefore the live deployment currently reports:

```text
llm_provider=gemini
llm_provider_effective=rule_based
```

This is intentional so that the public deployment does not require or expose a personal API key.

The Gemini extraction implementation remains available and can be activated by supplying `LLM_API_KEY` through the environment.

---

## 7. Extraction Schema Design

`schemas/extraction.py` uses a hybrid structure supporting canonical fields and document-specific visible line items.

```text
ExtractionResult
├── invoice_fields | statement_fields
├── invoice_line_items[] | statement_line_items[]
├── additional_fields{}
├── periods[]
└── extraction_warnings[]
```

Every scalar value is represented through an evidence-aware structure containing fields such as:

```text
value
raw_text
source_text
page_number
currency
unit_scale
is_percentage
confidence
```

Missing values are represented as `null` when they cannot be extracted.

The system intentionally does not invent values that are not present in the source document.

---

## 8. Financial Validation Approach

The LLM/OCR layer extracts information only. It does not determine financial correctness.

Every validation check returns:

- `formula`
- `operands`
- `calculated_value`
- `reported_value`
- `variance`
- `tolerance`
- `status`
- `period_label`

Possible statuses are:

```text
PASS
FAIL
NOT_APPLICABLE
```

### 8.1 Invoice

```text
quantity × unit price ≈ line total
sum(line totals) ≈ subtotal
subtotal + tax - discount + shipping ≈ total
cash received - total ≈ change
```

Checks are applied when the required fields are available. Tax-inclusive invoices are handled without forcing an incorrect tax/subtotal relationship.

### 8.2 Balance Sheet

```text
Total Capital & Liabilities ≈ Total Assets
sum(asset line items) ≈ Total Assets
sum(capital & liability line items) ≈ Total Capital & Liabilities
```

Checks are performed independently for each comparative period.

### 8.3 Profit & Loss

```text
Total Income - Total Expenditure
    ≈ Net Profit before Minority Interest
```

```text
Net Profit before Minority Interest - Minority Interest
    ≈ Net Profit attributable to the Group
```

### 8.4 Cash Flow

```text
Operating CF + Investing CF + Financing CF
    ≈ Net Increase in Cash
```

```text
Opening Cash + Net Increase in Cash
    ≈ Closing Cash
```

### 8.5 Processing Status vs Validation Status

`processing_status` and `validation.overall_status` intentionally represent different concepts.

For example:

```text
processing_status = PASS
validation.overall_status = FAIL
```

means the document was successfully processed and structured data was produced, but the extracted numbers did not reconcile.

### 8.6 Tolerance Strategy

Defaults:

```text
VALIDATION_ABS_TOLERANCE=0.01
VALIDATION_REL_TOLERANCE=0.001
```

A validation check passes when the difference is within either the configured absolute tolerance or the configured relative tolerance.

---

## 9. Evidence & Confidence Strategy

Every important extracted value can retain:

- `source_text`
- `raw_text`
- `page_number`
- `currency`
- `unit_scale`

Confidence is optional and explainable rather than being an arbitrary LLM-reported value.

The confidence calculation can incorporate:

1. OCR quality
2. fraction of extracted values with source-text grounding
3. extraction completeness
4. validation consistency

The resulting score is a heuristic indicator and not a statistically calibrated probability.

---

## 10. Database Design

The application uses a single `documents` table for the assessment.

The model stores:

```text
id
document_name
document_type
processing_status
file metadata
extracted_data_json
validation_json
processing_metadata_json
```

| Environment | Database |
|---|---|
| Local development | SQLite |
| Production deployment | PostgreSQL |

The database connection is controlled through `DATABASE_URL`.

`DocumentRepository` isolates direct ORM/database access from the rest of the application.

When a document is processed multiple times, the API returns the latest created result for that document name.

---

## 11. API Documentation

Interactive Swagger UI is automatically generated by FastAPI.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Liveness and configuration summary |
| `POST` | `/api/v1/documents/process` | Process an uploaded document |
| `GET` | `/api/v1/documents/{document_name}` | Retrieve the latest result for a document |
| `GET` | `/api/v1/documents` | List all processed documents |

The processing endpoint accepts `multipart/form-data` with:

- `file`
- `document_type`

### curl Examples

**Health**

```bash
curl http://localhost:8000/api/v1/health
```

**Process a document**

```bash
curl -X POST   http://localhost:8000/api/v1/documents/process   -F "file=@path/to/document.pdf"   -F "document_type=balance_sheet"
```

**Retrieve a document**

```bash
curl http://localhost:8000/api/v1/documents/<document_name>
```

**List processed documents**

```bash
curl http://localhost:8000/api/v1/documents
```

### Example Controlled Error Response

```json
{
  "error": {
    "code": "UNSUPPORTED_FILE_TYPE",
    "message": "Only PDF / JPG / PNG documents are supported."
  }
}
```

---

## 12. Local Setup

### Prerequisites

- Python 3.11+
- Tesseract OCR
- Poppler utilities
- Git

### System Dependencies

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils
```

### Backend

```bash
cd backend

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp ../.env.example .env
```

Edit `.env` as required.

Start the API:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger: `http://localhost:8000/docs`

Health: `http://localhost:8000/api/v1/health`

### Frontend

The frontend is static and requires no build step.

```bash
cd frontend
python3 -m http.server 5500
```

Open: `http://localhost:5500`

### Docker Compose

The repository also includes `docker-compose.yml`.

```bash
docker compose up --build
```

Expected local services:

```text
Backend  -> http://localhost:8000
Frontend -> http://localhost:5500
Postgres -> localhost:5432
```

---

## 13. Environment Variables

The complete environment configuration is documented in `.env.example`.

| Variable | Purpose |
|---|---|
| `ENV` | Runtime environment |
| `LOG_LEVEL` | Application logging level |
| `DATABASE_URL` | SQLite locally or PostgreSQL in production |
| `OCR_PROVIDER` | OCR provider |
| `OCR_DPI` | PDF rendering resolution for OCR |
| `TESSERACT_CMD` | Tesseract executable |
| `MAX_PAGE_COUNT` | Maximum accepted pages |
| `MAX_UPLOAD_SIZE_MB` | Maximum uploaded file size |
| `LLM_PROVIDER` | `gemini` or `rule_based` |
| `LLM_API_KEY` | Gemini API key; never commit this |
| `LLM_MODEL` | Gemini model name |
| `GEMINI_BASE_URL` | Google's OpenAI-compatible Gemini endpoint |
| `LLM_TIMEOUT_SECONDS` | LLM request timeout |
| `LLM_MAX_RETRIES` | Maximum LLM retries |
| `VALIDATION_ABS_TOLERANCE` | Absolute validation tolerance |
| `VALIDATION_REL_TOLERANCE` | Relative validation tolerance |
| `CORS_ORIGINS` | Allowed frontend origins |
| `UPLOAD_DIR` | Temporary upload directory |
| `API_BASE_URL` | Frontend API base URL when configured separately |

### Real Gemini Extraction

```text
LLM_PROVIDER=gemini
LLM_API_KEY=<your Gemini API key>
LLM_MODEL=gemini-2.5-flash
```

Never place the key in source code, GitHub, frontend JavaScript, tests, README, or logs.

If `LLM_API_KEY` is empty, the application automatically falls back to the deterministic rule-based provider.

---

## 14. Running Tests

Run:

```bash
cd backend
pytest -v
```

Current automated test result:

```text
57 passed
```

The tests cover:

- number parsing
- negative values
- bracketed values
- file validation
- supported and unsupported formats
- empty and corrupted files
- page-count limits
- rule-based extraction
- provider selection
- Gemini provider behavior
- mocked Gemini responses
- malformed JSON
- retry/backoff behavior
- transient failures
- all four document types
- invoice validation
- balance-sheet validation
- P&L validation
- cash-flow validation
- `NOT_APPLICABLE` paths
- health API
- document processing API
- document retrieval API
- document listing API
- SQLite-backed API tests

No test requires a real Gemini API key or network access.

---

## 15. Dataset Usage & Real Results

The `sample_outputs/` directory contains JSON results generated by running the extraction and validation logic against files from the supplied assessment dataset.

| File | Source Document | Result |
|---|---|---|
| `invoice.json` | Malaysian GST receipt | Successful processing with applicable invoice validation checks |
| `invoice_noisy_photographed.json` | Deliberately noisy phone-photographed Indian tax invoice | Pipeline completes honestly; fallback reports insufficient coverage rather than inventing values |
| `balance_sheet.json` | HDFC Consolidated Balance Sheet, FY2026 | Successful sample validation; Total Assets and Total Capital & Liabilities reconcile |
| `profit_and_loss.json` | HDFC Consolidated P&L, FY2026 | Successful validation of income/expenditure and minority-interest calculations |
| `cash_flow_statement.json` | HDFC Consolidated Cash Flow Statement, FY2026 | Contains a documented limitation related to OCR period-label alignment |

### Real Deployment Verification

A real HDFC Consolidated Balance Sheet PDF was processed through the public deployment after deployment fixes.

The complete pipeline successfully reached:

```text
File validation
      ↓
Native text detection
      ↓
OCR
      ↓
Extraction
      ↓
Financial validation
      ↓
Persistence
      ↓
API response
```

The live response returned:

```text
processing_status = PASS
pipeline_stage_reached = completed
error = null
```

One OCR row (`Advances`) was incorrectly reconstructed, which caused the asset-component reconciliation check to return `FAIL`.

The system correctly surfaced that discrepancy instead of changing the result to `PASS` or inventing a value.

---

## 16. Known Limitations

### 16.1 Rule-Based Extraction Coverage

The deterministic fallback has lower semantic coverage than the Gemini provider.

It can have difficulty with:

- unusual statement layouts
- complex invoice tables
- some invoice line items
- address/reference fields
- GST sub-component breakdowns
- unusual OCR column alignment

### 16.2 Invoice Line-Item Extraction

General multi-column invoice table extraction is primarily intended for the LLM path.

The deterministic fallback deliberately avoids implementing a fragile general-purpose invoice table parser.

### 16.3 Difficult Photographs

Very noisy, rotated, blurred, or partially unreadable phone photographs can still produce OCR errors.

### 16.4 Gemini Live Integration

The Gemini provider has been tested with mocked client responses covering successful JSON parsing, malformed JSON, markdown-fenced JSON, retries, transient failures, persistent failures, and all four supported document types.

The current public deployment does not use a live Gemini API key.

### 16.5 Confidence Calibration

Confidence is heuristic and explainable, but has not been statistically calibrated against a large labeled ground-truth dataset.

### 16.6 Free-Tier Deployment

The public assessment deployment uses free-tier resources. Limited CPU/RAM can make OCR slower than production infrastructure.

The PostgreSQL instance is also subject to the provider's free-tier lifecycle and expiration policy.

---

## 17. Production Improvements

### OCR and Document Processing

- Managed document-AI/OCR services such as Google Document AI or AWS Textract behind the existing `OCRProvider` interface.
- Layout-aware document understanding models.
- Stronger table detection and extraction.
- Better multilingual OCR.
- Automatic document quality assessment.

### Asynchronous Processing

The current assessment version processes the document through the API request lifecycle.

For production, document processing should be moved to a background job system such as Celery/RQ or an equivalent managed queue.

```text
API
 |
 v
Job Queue
 |
 +--> OCR Worker
 |
 +--> Extraction Worker
 |
 +--> Validation Worker
 |
 v
Database
```

The API could return a job ID immediately and provide a status endpoint.

### Storage

Uploaded documents should be stored in object storage such as an S3-compatible service instead of relying on container-local storage.

### Security

Production should add:

- authentication
- authorization
- API rate limiting
- stronger file-content validation
- malware scanning
- secrets manager integration
- audit logging
- monitoring
- distributed tracing

### Data Management

- Alembic migrations
- document versioning
- immutable audit history
- retention policies

### LLM Reliability

- token/cost monitoring
- structured-output validation
- provider fallback policies
- dead-letter handling
- request tracing
- field-level confidence calibration

### Human-in-the-Loop

A verification UI would be useful for:

- low-confidence fields
- failed financial validations
- ambiguous OCR
- missing mandatory fields

These improvements are intentionally not implemented in the assessment version to avoid unnecessary enterprise complexity.

---

## 18. Deployment

The current public deployment is hosted on Render as a Dockerized FastAPI Web Service.

The FastAPI application serves both the REST API and the static frontend, so the current assessment deployment uses a single public service.

### Live URLs

| Resource | URL |
|---|---|
| **Frontend** | https://document-intelligence-platform-71sf.onrender.com |
| **Backend** | https://document-intelligence-platform-71sf.onrender.com |
| **Swagger / OpenAPI** | https://document-intelligence-platform-71sf.onrender.com/docs |
| **Health Check** | https://document-intelligence-platform-71sf.onrender.com/api/v1/health |
| **GitHub Repository** | https://github.com/snehaaa011/document-intelligence-platform |

### Production Configuration

```text
ENV=production
OCR_PROVIDER=tesseract
OCR_DPI=300
MAX_PAGE_COUNT=3
MAX_UPLOAD_SIZE_MB=20
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
VALIDATION_ABS_TOLERANCE=0.01
VALIDATION_REL_TOLERANCE=0.001
```

No Gemini API key is stored in the public deployment.

```text
Configured provider: Gemini
Effective provider:  Rule-based fallback
```

### Deployment Verification

Verified public endpoints:

```text
GET  /api/v1/health
GET  /docs
POST /api/v1/documents/process
GET  /api/v1/documents/{document_name}
GET  /api/v1/documents
```

Public health response:

```json
{
  "status": "ok",
  "app_name": "Document Intelligence Platform",
  "env": "production",
  "llm_provider": "gemini",
  "llm_provider_effective": "rule_based",
  "ocr_provider": "tesseract",
  "database_connected": true
}
```

A real Balance Sheet PDF was successfully processed through the public deployment after resolving the synchronous OCR/event-loop issue.

### CORS

The current assessment deployment uses a permissive CORS configuration for the single-service public demonstration.

For a production deployment, `CORS_ORIGINS` should be restricted to the exact frontend origin rather than using a wildcard.

### Free-Tier Limitation

The current deployment uses free-tier Render infrastructure for assessment/demo purposes.

The production version should use:

- persistent paid PostgreSQL
- more capable CPU/RAM
- background processing workers
- object storage
- monitoring and alerting
- proper secrets management

---

## 19. Security Considerations

### Secrets

No API keys, passwords, or other production secrets are committed to the repository.

Sensitive configuration is supplied through environment variables.

`.gitignore` excludes:

```text
.env
*.env
```

`.env.example` documents configuration without containing real secrets.

### Uploaded Files

Uploaded files are validated before OCR/LLM processing.

Validation includes:

- supported file type
- readability
- maximum file size
- maximum page count

Current assessment limits:

```text
Maximum pages: 3
Maximum file size: 20 MB
```

Uploaded files are processed through temporary paths and removed after processing.

### Exception Handling

Application exceptions are converted into controlled JSON responses.

Raw Python stack traces are not returned to API clients. Detailed errors are logged server-side.

### CORS

CORS is configurable using `CORS_ORIGINS`.

The public assessment deployment currently uses a permissive setting to support the single-service demonstration.

A production deployment should use an explicit allow-list.

### Production Security Improvements

- authentication
- authorization
- rate limiting
- malware scanning
- stronger file-content validation
- secrets manager
- audit logs
- monitoring and alerting
- request tracing

---

## 20. AI / Tool Usage Declaration

This project was built with assistance from an AI coding assistant (**Claude, Anthropic**), as permitted by the assessment.

The coding assistant was used for:

- architecture and design exploration
- implementation assistance
- debugging
- OCR troubleshooting
- provider abstraction design
- extraction prompt design
- financial validation logic
- documentation drafting
- code iteration during testing

The code was reviewed, executed, and iterated against the actual supplied dataset rather than being accepted without testing.

The development-time coding assistant and the application's runtime document-extraction provider are separate:

```text
Development assistance
        |
        v
Claude / Anthropic
        |
        v
Code development, debugging and documentation


Application runtime
        |
        v
Gemini / Rule-based provider
        |
        v
Document extraction
```

The application does not use OpenAI's API service.

The `openai` Python package is used only as a generic protocol-compatible client for Google's Gemini OpenAI-compatible endpoint.

The public deployment currently uses the deterministic rule-based fallback because no Gemini API key is stored in the deployment.

---

## 21. Assessment Coverage Checklist

### Document Processing

- [x] Invoice
- [x] Balance sheet
- [x] Profit & loss
- [x] Cash flow statement
- [x] PDF input
- [x] JPG input
- [x] PNG input
- [x] Native PDF text detection
- [x] OCR for scanned/flattened documents
- [x] Maximum 3-page validation
- [x] File-size validation
- [x] Unsupported-file validation
- [x] Empty/corrupt-file handling

### Extraction

- [x] Structured JSON
- [x] Canonical fields
- [x] Dynamic line items
- [x] Comparative periods
- [x] Source evidence
- [x] Page information
- [x] Currency/unit information
- [x] Missing-value handling
- [x] Gemini extraction provider
- [x] Rule-based fallback

### Financial Validation

- [x] Invoice calculations
- [x] Balance-sheet reconciliation
- [x] P&L calculations
- [x] Cash-flow calculations
- [x] PASS
- [x] FAIL
- [x] NOT_APPLICABLE
- [x] Absolute tolerance
- [x] Relative tolerance
- [x] Explainable formulas
- [x] Explainable operands
- [x] Comparative-period validation

### API

- [x] POST document processing
- [x] GET document by name
- [x] GET document list
- [x] GET health
- [x] OpenAPI
- [x] Swagger UI
- [x] Controlled error responses

### Frontend

- [x] Document type selection
- [x] File upload
- [x] Processing
- [x] Results display
- [x] Extracted data
- [x] Validation results
- [x] Raw JSON
- [x] API integration

### Database

- [x] SQLite local development
- [x] PostgreSQL production
- [x] SQLAlchemy
- [x] Persistent processing results

### Testing

- [x] Automated tests
- [x] 57 tests passing
- [x] All four document types covered
- [x] Scanned/image OCR coverage
- [x] Validation failure paths
- [x] Invalid/unsupported file paths
- [x] Sample JSON outputs
- [x] Mocked Gemini provider tests

### Documentation

- [x] README
- [x] Architecture diagram
- [x] Sample outputs
- [x] `.env.example`
- [x] `.gitignore`
- [x] API documentation
- [x] Deployment URLs
- [x] AI/tool usage declaration
- [x] Known limitations
- [x] Production improvements

### Deployment

- [x] Public frontend
- [x] Public backend
- [x] Public Swagger
- [x] Public health endpoint
- [x] Public GitHub repository
- [x] PostgreSQL persistence
- [x] No secrets committed
- [x] Real document processing verified after deployment

---

## 22. Quick Demo Flow

For the assessment demonstration:

1. Open the deployed frontend:
   `https://document-intelligence-platform-71sf.onrender.com`
2. Select a document type.
3. Upload a supported PDF/JPG/PNG document.
4. Click **Process**.
5. Review:
   - processing status
   - extracted fields
   - evidence/source text
   - confidence
   - validation checks
   - raw JSON
6. Open Swagger:
   `https://document-intelligence-platform-71sf.onrender.com/docs`
7. Demonstrate the health endpoint:
   `https://document-intelligence-platform-71sf.onrender.com/api/v1/health`
8. Show the GitHub repository:
   `https://github.com/snehaaa011/document-intelligence-platform`
9. Explain the separation between extraction and validation:

```text
OCR / LLM
    |
    v
Extract what is actually present
    |
    v
Deterministic Python validation
    |
    v
Explainable PASS / FAIL / NOT_APPLICABLE
```

The key design principle is that an LLM is not trusted to decide financial correctness. It extracts information, while deterministic Python calculations independently verify the financial relationships.

This makes the output more auditable and prevents the extraction layer from silently changing financial calculations simply to make a document appear valid.
