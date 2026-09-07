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
Ollama 0.33.3
qwen2.5vl:7b (classify-only calls + a separate content_card-grounding call)

qwen3-vl:4b was the original candidate; rejected after benchmarking (thinking mode can't be
disabled, exhausts the token budget on screens with many repeated elements). See `memory.md`'s
VLM benchmarking history for the full record. The application must use a replaceable VLM
interface (`VLMEngine` in `src/vlm/engine.py`) — the model may change again after further
benchmarking.

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
As implemented in `src/graph/build.py`: CONTAINS, ABOVE, BELOW, LEFT_OF, RIGHT_OF, ALIGNED_WITH,
OVERLAPS, ORDERED_BEFORE. CHILD_OF is not a separate materialized edge — it's derivable via
`graph.reverse()` on CONTAINS; BELONGS_TO was not needed once CONTAINS covered parent/child.

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

Two environments are documented for this project and are not interchangeable — see
`environment.md` for the full Docker/Linux/GPU spec and `memory.md` for which one is actually
checked out and being worked in right now. Do not assume the GPU container is current without
checking; do not assume Windows/CPU is current without checking either.

Rebenchmark model latency before changing the VLM model — do not carry a benchmark number from
one environment over to a claim about the other.

14. Development

Build vertically: one screenshot → OCR → VLM → JSON → Graph → comparison → report. Then scale to pairs and batch.

15. Reproducibility

Record model, model tag/version, OCR config, VLM prompt version, image resolution, inference time and comparison thresholds.

16. Current state

See `memory.md` — it is the single source of truth for phase status, environment, and the next
task. Do not duplicate that table here; a second copy is how this section went stale before.

17. Container discipline

If working in the Docker/GPU environment: only work inside `ui_compare_v2` (the volume-mounted
container). An earlier `ui_compare` container had no volume mount, was confirmed empty, and
should not be used — anything installed in a container without a host volume mount is lost if
that container is removed.