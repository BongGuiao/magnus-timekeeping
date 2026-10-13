FROM python:3.11-slim

WORKDIR /app

# 1. Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    g++ \
    make \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Copy requirements (must be its own instruction on its own line)
COPY requirements.txt /app/

# 3. Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 4. Remove build tools and install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 libopenblas0 liblapack3 \
    && apt-get purge -y --auto-remove gcc g++ make cmake libopenblas-dev liblapack-dev libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 5. Copy the rest of the application code
COPY . /app/