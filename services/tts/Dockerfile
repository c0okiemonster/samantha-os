FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl espeak-ng wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Download Kokoro ONNX model and voices (for voice blending)
RUN mkdir -p /app/models && \
    wget -q -O /app/models/kokoro-v1.0.onnx \
      "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx" && \
    wget -q -O /app/models/voices-v1.0.bin \
      "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

# Pre-download the HuggingFace Kokoro model for KPipeline
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('hexgrad/Kokoro-82M')" || true

COPY . .

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
