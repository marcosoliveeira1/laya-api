# Imagem ARM-friendly (oracle-arm é a1-flex ARM; funciona em x86 também)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/data/hf-cache \
    HF_HUB_OFFLINE=0 \
    LAYA_PRELOAD=true \
    LAYA_DEVICE=cpu

WORKDIR /srv

# torch CPU via índice oficial (bem menor que o wheel CUDA)
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch && \
    pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY scripts/ ./scripts/

VOLUME ["/data/hf-cache"]
EXPOSE 8000

# 1 worker: o Router já é pesado (~4-5GB com preload dos 3 checkpoints).
# Não suba workers sem medir RAM.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
