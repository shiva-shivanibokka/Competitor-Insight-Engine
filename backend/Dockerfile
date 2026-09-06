# Not used by the deployment — Vercel builds this service from source (see
# ../vercel.json). Kept because the API is a plain container and self-hosting it
# should not require rebuilding the packaging first.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Respect $PORT if the platform injects one; 7860 matches the local default.
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
