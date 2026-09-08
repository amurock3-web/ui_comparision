# CUDA 12.6 + cuDNN runtime. cuDNN is required by paddlepaddle-gpu — the plain
# `-base` and `-runtime` tags do not include it.
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# python3.11 to match the Windows dev environment (22.04 ships 3.10).
# libgl1/libglib2.0-0 are opencv-contrib-python's runtime deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates curl gnupg && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-dev \
        libgl1 libglib2.0-0 libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# venv at /opt/venv keeps site-packages out of the bind-mounted /workspace.
RUN python3.11 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Only requirements.txt is copied. Source code is NEVER copied into the image —
# it is bind-mounted from the host at runtime (see docker-compose.yml).
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /tmp/requirements.txt && \
    pip uninstall -y paddlepaddle && \
    pip install paddlepaddle-gpu==3.2.0 \
        -i https://www.paddlepaddle.org.cn/packages/stable/cu126/ && \
    rm /tmp/requirements.txt

# Dev tooling. requirements.txt has no pytest even though tests/ exists — it was
# installed ad hoc in the Windows venv. Pinned here so `pytest` works in-container.
RUN pip install pytest==8.3.4

# HOME for the runtime user. PaddleOCR downloads its detection/recognition models
# to ~/.paddlex on first run; huggingface_hub and matplotlib also write under HOME.
# Pre-created and chowned so a named volume mounted here inherits the ownership and
# stays writable for the non-root user under a read-only rootfs.
RUN mkdir -p /cache && chown 1000:1000 /cache
ENV HOME=/cache

WORKDIR /workspace
CMD ["sleep", "infinity"]
