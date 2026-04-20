FROM python:3.13-slim

WORKDIR /app

# Copy only requirements first to leverage Docker layer cache.
COPY requirements.txt .

# Install Python dependencies only.
# This avoids transient apt mirror failures during build.
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code.
COPY . .

CMD ["python", "main.py"]
