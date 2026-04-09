FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (curl for healthcheck, build-essential for tiktoken)
RUN apt-get update && apt-get install -y --no-install-recommends curl gcc g++ && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

EXPOSE 5003

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5003"]