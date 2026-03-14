FROM python:3.11-slim

# System deps: OpenCV needs libGL + libglib, imagededup needs some extras
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY reddit_downloader.py .

# Output folder lives here — mount a host volume to this path
VOLUME ["/app/output"]

ENTRYPOINT ["python", "reddit_downloader.py"]
