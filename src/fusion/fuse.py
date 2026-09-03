"""
OCR + VLM fusion (design.md §4, architecture.md §6).

Will associate OCR and VLM observations using bbox overlap, center
distance, text similarity, and spatial proximity, producing fused
UIElement objects while preserving the raw sources. Not implemented yet.
"""
