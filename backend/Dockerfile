# Hugging Face Spaces (Docker SDK) serves on port 7860.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Respect $PORT if the platform injects one (Cloud Run sets it; HF/local default 7860).
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
