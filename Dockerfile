FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY . .

# Generate the synthetic catalogue + demo bundle at build time (offline engine).
RUN python catalog/generate_catalog.py && \
    python generator/export_bundle.py && \
    python frontend/build.py

EXPOSE 8000
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
