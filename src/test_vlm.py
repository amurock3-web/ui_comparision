import json
import time
from pathlib import Path

import ollama
from ollama import ResponseError


IMAGE_PATH = Path("input/production/ss012.png")
MODEL = "qwen3-vl:4b"


PROMPT = """
You are analyzing an OTT streaming application screenshot.

Identify the visible UI elements in the screenshot.

For each element, provide:
1. semantic UI type
2. visible text, if any
3. approximate bounding box as [x, y, width, height]
4. confidence from 0 to 1

Use these UI types when applicable:
content_card
nav_item
badge
section_title
button
cast_card
icon
metadata_text
category_tab
navigation_bar
celebrity_card
detail_tab
duration
carousel_filter
movie_title
description
search_bar
episode_badge
logo
rank_number
text_input
series_title

Important:
- Do not invent elements that are not visible.
- Treat each visible UI instance separately.
- Include repeated elements separately.
- Focus on actual UI components, not arbitrary regions of the screenshot.
- Return ONLY valid JSON.
"""


def main():
    if not IMAGE_PATH.exists():
        raise FileNotFoundError(f"Image not found: {IMAGE_PATH}")

    print(f"Image : {IMAGE_PATH}")
    print(f"Model : {MODEL}")
    print("Sending image to local VLM...")
    print("This may take some time on CPU, especially while the model reasons before answering.\n")

    start = time.time()

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": PROMPT,
                    "images": [str(IMAGE_PATH.resolve())],
                }
            ],
            format="json",  # JSON-grammar masking applies once the model closes its </think> block
            options={
                "temperature": 0,
                "num_ctx": 16384,  # give it real room to finish thinking before hitting the context wall
            },
            # NOTE: deliberately not passing think=False here — for qwen3-vl on Ollama that flag is
            # currently ignored for vision inputs AND causes the JSON grammar masking to never engage
            # (see ollama/ollama#14645). Leaving thinking on and letting format="json" mask the
            # post-</think> content is the combination that's actually supposed to work.
        )
    except ResponseError as e:
        print(f"Ollama API Error: {e}")
        return
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return

    elapsed = time.time() - start

    done_reason = response.get("done_reason")
    if done_reason != "stop":
        print(f"[warn] Generation did not finish normally (done_reason={done_reason!r}).")
        print("       This usually means it hit num_ctx before finishing its reasoning —")
        print("       the JSON below is likely incomplete or missing entirely.\n")

    message = response["message"]
    raw_result = message.get("content", "")
    thinking = message.get("thinking", "")

    if not raw_result.strip() and thinking.strip():
        print("[warn] 'content' is empty but 'thinking' has text — masking likely never engaged")
        print("       (model probably never emitted a closing </think>). Saving thinking as fallback.\n")
        raw_result = thinking

    # Parse and format JSON for clean saving
    try:
        parsed_json = json.loads(raw_result)
        formatted_result = json.dumps(parsed_json, indent=2)
        parsed_ok = True
    except json.JSONDecodeError:
        print("Warning: Response is not valid JSON. Saving raw output instead.")
        formatted_result = raw_result
        parsed_ok = False

    output_dir = Path("output/json")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Always keep the raw text too, for debugging when parsing fails
    raw_file = output_dir / "ss012_vlm_raw.txt"
    raw_file.write_text(raw_result, encoding="utf-8")

    json_file = output_dir / "ss012_vlm.json"
    json_file.write_text(formatted_result, encoding="utf-8")

    print("=" * 70)
    print("VLM RESPONSE" + ("" if parsed_ok else " (unparsed / raw)"))
    print("=" * 70)
    print(formatted_result)
    print("=" * 70)
    print(f"Inference time: {elapsed:.2f} seconds")
    print(f"done_reason   : {done_reason}")
    print(f"Raw text saved to : {raw_file}")
    print(f"JSON saved to     : {json_file}")


if __name__ == "__main__":
    main()