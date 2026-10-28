FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies for OpenCV, FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install torch/torchvision from the PyTorch CPU wheel index first: on Linux
# the default PyPI wheels are the CUDA builds and pull in multiple GB of
# nvidia/* packages. This project runs CPU inference only (see requirements.txt).
RUN pip install --no-cache-dir --timeout 120 --retries 8 \
        torch==2.14.0 torchvision==0.29.0 \
        --index-url https://download.pytorch.org/whl/cpu
# Retry flags keep the build durable on slow/flaky PyPI connections (the
# heavy wheels frequently exceed pip's default 15s read timeout).
RUN pip install --no-cache-dir --timeout 120 --retries 8 -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
