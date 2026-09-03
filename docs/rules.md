Project Rules --- UI Comparison
1. Project separation

This is a new project. Do not confuse it with the previous SunNXT annotation/GT audit project.

Old annotations, GT rules and XML may later be used as reference/evaluation data, but they are not the center of this architecture.

2. Data privacy --- CRITICAL

Production and Client screenshots must remain local.

Do not use: - cloud VLM inference - cloud OCR - screenshot uploads - third-party image-processing APIs

Use: - local screenshots - local OCR - local VLM - local JSON - local graph - local comparison - local reports

3. Local VLM

The VLM must be locally hosted.

Current setup:

text
Ollama (installed via ollama.com/install.sh inside the GPU container;
        started manually with `ollama serve &`, no systemd)
qwen3-vl:4b

The model may change after further benchmarking on the GPU. The application must use a replaceable VLM interface.

4. OCR

Current OCR stack:

text
PaddleOCR
paddlepaddle-gpu 3.2.0 (cu126 build)
PP-OCRv6 family

OCR provides text, coordinates and confidence. It is not responsible for full semantic UI understanding.

5. JSON + Graph

Both are required.

JSON = canonical structured data/interchange layer.
Graph = UI relationships/structure layer.

Never replace one with the other.

6. Graph

Use NetworkX for the POC. Do not introduce Neo4j unless demonstrated necessary.

Initial edges: CONTAINS, CHILD_OF, BELONGS_TO, ABOVE, BELOW, LEFT_OF, RIGHT_OF, ALIGNED_WITH, OVERLAPS, ORDERED_BEFORE.

7. Comparison

Never rely only on pixel difference.

Use: - class - text - position - size - bbox - IoU - normalized coordinates - spatial relationships - parent/child relationships - ordering - confidence

8. Difference types

Initial: MATCH, MISSING_IN_CLIENT, EXTRA_IN_CLIENT, CLASS_DIFFERENCE, TEXT_DIFFERENCE, POSITION_DIFFERENCE, SIZE_DIFFERENCE, GEOMETRY_DIFFERENCE, STRUCTURAL_DIFFERENCE, ORDER_DIFFERENCE, UNCERTAIN.

9. Coordinates

Store: [x, y, width, height] and normalized: [x/W, y/H, width/W, height/H].

10. Confidence

Do not turn uncertain AI output into ground truth silently. Preserve confidence and uncertainty.

Implemented in the OCR engine as confidence_tier ("high" >= 0.85, "medium" >= 0.60, "low" < 0.60) — low-tier detections are kept as evidence, not discarded, and are visually flagged (red) in the OCR visualization output.

11. Existing GT

Do not automatically remap/delete/change old annotations for this new POC. Use them only as explicitly identified reference/evaluation material.

12. POC scope

Do: - a few screenshot pairs - OCR - local VLM - JSON - graph - comparison - report

Do not initially: - clean all old annotations - process all 103 screens - train a VLM - train a detector - build Neo4j - build a large frontend

13. Hardware

Current (migrated from Windows laptop to GPU Linux sandbox):

text
Platform : Docker container (nvidia/cuda:12.6.3-base-ubuntu22.04)
Container: ui_compare_v2 (volume-mounted at /workspace,
           backed by ~/ui_comparison_workspace on the host)
GPU      : NVIDIA GeForce GTX 1070 (Pascal, compute capability 6.1)
VRAM     : 8 GB
Driver   : 580.173.02
CUDA (container toolkit): 12.6.3

GPU access has been obtained (previously "may become available"). Rebenchmark VLM latency now that GPU is available, per the original rule below.

Full details: see environment.md.

Superseded (previous Windows laptop spec, kept for history):

text
Intel Core i5-1335U
10 cores / 12 threads
~34 GB RAM
Intel Iris Xe
No NVIDIA CUDA

Rebenchmark before changing model (still applies going forward).

14. Development

Build vertically: one screenshot → OCR → VLM → JSON → Graph → comparison → report Then scale to pairs and batch.

15. Reproducibility

Record model, model tag/version, OCR config, VLM prompt version, image resolution, inference time and comparison thresholds.

16. Current state
Environment (Windows, CPU): DONE (superseded)
Environment (GPU Linux/Docker, ui_compare_v2): DONE
Ollama: DONE (reinstalled on GPU container)
qwen3-vl:4b: DOWNLOADED (Windows); re-pull on GPU container in progress
PaddlePaddle: DONE (CPU on Windows); GPU build (cu126) in progress on new container
PaddleOCR: INSTALLED (both environments)
SS012 OCR test: DONE (Windows/CPU, 39 detections, ~41-59s)
OCR JSON/visualization: DONE, includes center/normalized_bbox/ confidence_tier
OCR engine refactor (src/ocr/engine.py, visualize.py): DONE
SS012 OCR test on GPU: NOT YET RUN
VLM benchmark: PAUSED on Windows (CPU too slow); to resume on GPU
Fusion/graph/comparison/report: NOT STARTED
17. Container discipline (new)

Only work inside ui_compare_v2 (the volume-mounted container). The original ui_compare container was created without a volume mount, was confirmed empty, and should not be used further — anything installed in a container without a volume mount to the host is lost if that container is removed.