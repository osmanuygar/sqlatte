FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN addgroup --system sqlatte && adduser --system --ingroup sqlatte sqlatte

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (no config — mounted via volume at runtime)
COPY src/ src/
COPY frontend/ frontend/

# Config directory placeholder; real config.yaml is supplied via volume mount.
# Never bake credentials into the image.
RUN mkdir -p config && chown -R sqlatte:sqlatte /app

USER sqlatte

# Expose port
EXPOSE 8000

# Run application
CMD ["python", "src/api/app.py"]
