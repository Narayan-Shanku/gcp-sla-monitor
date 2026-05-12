FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY main.py .

# Cloud Run sets PORT at runtime; default to 8080 for local testing
ENV PORT=8080

# Start gunicorn bound to the Cloud Run-provided port
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
