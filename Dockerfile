FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run, Fly.io, Render etc. all set $PORT; uvicorn reads it via the
# shell expansion below rather than config.py so the container adapts to
# whatever the platform assigns without a rebuild.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
