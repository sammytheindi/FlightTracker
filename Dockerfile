FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies first (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium + all system libraries it needs (covers matplotlib's freetype/fontconfig too)
RUN playwright install chromium --with-deps

# Copy application source
COPY main.py .
COPY src/ src/

# Persistent data directory (mount a volume here in production)
RUN mkdir -p data

ENTRYPOINT ["python", "main.py"]
# Default: watch all jobs in the mounted jobs/ directory
CMD ["watch", "--jobs-dir", "jobs"]
