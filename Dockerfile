FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ src/
COPY frontend/ frontend/
COPY config/ config/

# Expose port
EXPOSE 8000

# Run application
CMD ["python", "src/api/app.py"]
