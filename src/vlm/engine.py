"""
VLM abstraction (architecture.md §5): VLMEngine.analyze(image, ocr_result).

Everything else in the app should call this instead of touching Ollama
directly, so the underlying model stays swappable. Not implemented yet.
"""
