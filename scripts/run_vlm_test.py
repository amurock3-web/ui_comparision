import sys
from collections import Counter
from pathlib import Path

from scripts._test_utils import next_test_number
from src.ocr.engine import OCREngine
from src.vlm.engine import VLMEngine
from src.vlm.visualize import draw_vlm_result

# "classify": default path used by fusion in production - class/text/
#     description/approximate_location, no bbox.
# "grounded_all": experimental analyze_grounded_experimental() - asks the
#     VLM for a [x,y,w,h] pixel bbox per element, ALL classes at once. Known
#     flaky (duplicate/oversized boxes) - for eyeballing VLM behavior only.
# "grounded_cards": experimental ground_content_cards_experimental() -
#     narrow, content_card-only grounding using Qwen2.5-VL's native
#     bbox_2d/[x1,y1,x2,y2] format. Not wired into fusion/main.py.
MODE = "grounded_cards"

IMAGE_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "input/production/ss012.png")
SCREEN_ID = IMAGE_PATH.stem
OUTPUT_DIR = Path("output/vlm")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TEST_NUM = next_test_number(OUTPUT_DIR)

ocr_result = OCREngine(lang="en").run(IMAGE_PATH, screen_id=SCREEN_ID)

if MODE == "grounded_all":
    PREFIX = f"test{TEST_NUM}_{SCREEN_ID}_vlm_grounded"
    vlm_result = VLMEngine().analyze_grounded_experimental(IMAGE_PATH, ocr_result, screen_id=SCREEN_ID)
    vlm_result.save_json(OUTPUT_DIR / f"{PREFIX}.json")
    draw_vlm_result(IMAGE_PATH, vlm_result, OUTPUT_DIR / f"{PREFIX}_visualization.png")

    class_counts = Counter(e.class_ for e in vlm_result.elements)
    print(f"Elements: {len(vlm_result.elements)}")
    print(f"Inference time: {vlm_result.inference_time_seconds:.2f}s")
    print(f"done_reason: {vlm_result.done_reason}")
    print(f"Class breakdown: {dict(class_counts)}")

    print("\nPer-element detail:")
    for e in vlm_result.elements:
        print(f"  {e.id:10s} class={e.class_:16s} bbox={e.bbox} confidence={e.confidence:.2f} text={e.text!r}")

    print(f"\nJSON saved to: {OUTPUT_DIR / f'{PREFIX}.json'}")
    print(f"Visualization saved to: {OUTPUT_DIR / f'{PREFIX}_visualization.png'}")

elif MODE == "grounded_cards":
    PREFIX = f"test{TEST_NUM}_{SCREEN_ID}_vlm_grounded_cards"
    vlm_result = VLMEngine().ground_content_cards_experimental(IMAGE_PATH, screen_id=SCREEN_ID)
    vlm_result.save_json(OUTPUT_DIR / f"{PREFIX}.json")
    draw_vlm_result(IMAGE_PATH, vlm_result, OUTPUT_DIR / f"{PREFIX}_visualization.png")

    print(f"content_card elements: {len(vlm_result.elements)}")
    print(f"Inference time: {vlm_result.inference_time_seconds:.2f}s")
    print(f"done_reason: {vlm_result.done_reason}")

    print("\nPer-element detail:")
    for e in vlm_result.elements:
        print(f"  {e.id:10s} bbox={e.bbox}")

    print(f"\nJSON saved to: {OUTPUT_DIR / f'{PREFIX}.json'}")
    print(f"Visualization saved to: {OUTPUT_DIR / f'{PREFIX}_visualization.png'}")

else:
    PREFIX = f"test{TEST_NUM}_{SCREEN_ID}_vlm"
    vlm_result = VLMEngine().analyze(IMAGE_PATH, ocr_result, screen_id=SCREEN_ID)
    vlm_result.save_json(OUTPUT_DIR / f"{PREFIX}.json")

    class_counts = Counter(e.class_ for e in vlm_result.elements)
    null_text_count = sum(1 for e in vlm_result.elements if e.text is None)

    print(f"Elements: {len(vlm_result.elements)}")
    print(f"Inference time: {vlm_result.inference_time_seconds:.2f}s")
    print(f"done_reason: {vlm_result.done_reason}")
    print(f"parse_error: {vlm_result.parse_error}")
    print(f"Class breakdown: {dict(class_counts)}")
    print(f"Elements with text=null: {null_text_count}/{len(vlm_result.elements)}")

    print("\nPer-element detail:")
    for e in vlm_result.elements:
        print(f"  {e.id:10s} class={e.class_:16s} location={e.approximate_location:12s} "
              f"text={e.text!r} description={e.description!r}")

    print(f"\nJSON saved to: {OUTPUT_DIR / f'{PREFIX}.json'}")
