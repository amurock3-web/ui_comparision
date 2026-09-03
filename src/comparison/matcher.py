"""
Element matching between Production and Client (design.md §7).

Will score candidate matches by combining class score, text score, spatial
score, bbox/IoU score, and context score, with weights read from
config/config.yaml rather than hard-coded. Not implemented yet.
"""
