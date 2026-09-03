Environment Spec — UI Comparison (GPU / Linux / Docker)

Replaces: the "Hardware" section in memory.md and rules.md §13 (old CPU-only Windows spec is now obsolete).

1. Platform

Running inside a Docker container, not a bare Linux install.

text
Base image : nvidia/cuda:12.6.3-base
Started via: sudo docker run -it --gpus all --name ui_compare nvidia/cuda:12.6.3-base

Critical implication: containers are disposable. Anything installed or written inside the container (Python, packages, code, outputs) is lost if the container is removed, unless you either:

mount a host volume for the project folder, or
capture the setup in a Dockerfile so it's rebuildable.

See §7 for the recommended approach — do not skip this.

2. GPU
text
GPU            : NVIDIA GeForce GTX 1070
Architecture   : Pascal (compute capability 6.1)
VRAM           : 8192 MiB (8 GB)
Driver         : 580.173.02
Max CUDA (driver): 13.0
Container CUDA toolkit: 12.6.3

8GB VRAM is sufficient for qwen3-vl:4b — no need to change the model choice from Phase 2. Pascal-era GPUs are still supported by current CUDA/cuDNN/Ollama builds, but PaddlePaddle GPU wheel selection must match the container's CUDA 12.6 toolkit (not the driver's max of 13.0) — see §4.

3. Python

Not present in the base image. Must install manually.

bash
apt update && apt install -y python3.11 python3.11-venv python3-pip git curl build-essential
4. PaddlePaddle — GPU build

Match to container CUDA (12.6), not driver max (13.0):

bash
pip uninstall -y paddlepaddle
pip install paddlepaddle-gpu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/

Verify this URL/tag still exists at install time — PaddlePaddle's available CUDA tags change between releases. If cu126 isn't listed, fall back to the closest older tag (e.g. cu123) rather than the driver's cu130, since the container toolkit is 12.6.

5. Ollama

Containers typically have no init system, so ollama serve must be started manually (not as a systemd service):

bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
ollama pull qwen3-vl:4b
6. Model choice — confirmed

qwen3-vl:4b remains the right call:

Fits well within 8GB VRAM at typical quantization
GPU inference should be a large speedup over the CPU run on the old Windows laptop
No need to downgrade to a smaller VLM unless benchmarking on this GPU still shows unacceptable latency
7. Recommended: Dockerfile instead of ad-hoc installs

To avoid losing setup work if the container is removed, capture everything in a Dockerfile rather than installing by hand each time:

dockerfile
FROM nvidia/cuda:12.6.3-base
RUN apt update && apt install -y python3.11 python3.11-venv python3-pip git curl build-essential
WORKDIR /workspace
COPY requirements.txt .
RUN python3.11 -m pip install --upgrade pip && pip install -r requirements.txt
RUN pip uninstall -y paddlepaddle && \
    pip install paddlepaddle-gpu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
RUN curl -fsSL https://ollama.com/install.sh | sh

Build and run with the project folder mounted as a volume, so code and outputs persist on the host even if the container is deleted:

bash
docker build -t ui_compare_img .
docker run -it --gpus all --name ui_compare_v2 -v ~/projects/ui_comparison:/workspace ui_compare_img
8. Verification checklist (run after setup)
bash
nvidia-smi                     # GPU visible
python3.11 -c "import paddle; paddle.utils.run_check()"   # Paddle sees GPU
ollama run qwen3-vl:4b "describe this in one word: test"   # Ollama responds
9. Reproducibility note (rules.md §15)

Update memory.md and rules.md §13 hardware sections to point to this file instead of the old Windows/Intel Iris Xe spec once this environment is confirmed working end-to-end.