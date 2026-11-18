# Authors

Designed and built by Pralhadraj Joshi, AI Engineer Intern, Logituit, Jul-Nov 2026; project commits 2026-08-20 to Nov 2026.

Major components, from the git history of this repository:

- OCR stage with PaddleOCR (Phase 1, `5eb34d0`)
- Fusion, UI graph, matcher, difference engine and reporting, run end to end as the first POC (Phases 3-8, `d4397a9`, `6a69efd`)
- Docker / CUDA sandbox for the Linux GPU machine (`438eead`)
- Detector module for the ui16_v1 YOLO bundle and its integration as the primary element source (`efe0492`, `8878b1f`, `2a0e030`)
- PASS / REVIEW / FAIL verdict layer from the test-case spec (`b285ffb`)
- OCR text accuracy measurement against the APK view hierarchy (`d8989ba`)
- Layout-tree graph, HTML report and the known-defect benchmark (`fddf6b3`)
- Drag-and-drop web UI with progress bar and PDF report (`cbcf9c4`)
- Class refiner experiment (`e2d8393`)
- Rematch script, element-count similarity and group-shift matching (Phase 12, `220e57b`)
- Screen, colour and layout checks with noise reduction (Phase 13, `45b19eb`)
- Match levels and regions, contrast, language, logo / icon / broken-image checks, baselines, batch, run history, ticket export, the web app pages and job queue, and false-alarm fixes (Phases 13.1-16 and 14b, `ae58696`)
- Cached benchmark re-scoring and detector jitter measurement (Phase 17, `c326fa8`, `0d9ffee`)
- Policy v1: spec v1, screen-verdict rule, C1 element-size rule, low-confidence cap, scorecard and tester budget (Phase 18, `71f9423` to `84656b5`)
- Pipeline demo video and gap analysis (`35580e6`, `d33db20`)
- Report side-by-side at one scale (`960eef3`)
