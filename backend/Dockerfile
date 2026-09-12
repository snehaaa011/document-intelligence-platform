FROM python:3.11-slim

# System dependencies: tesseract for OCR, poppler-utils for PDF->image
# and native text extraction.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application
COPY backend/app ./app

# Copy frontend so FastAPI can serve the frontend assets
COPY frontend /frontend

# Create upload directory
RUN mkdir -p /app/uploads

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]