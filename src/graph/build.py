"""
UI graph construction using NetworkX (design.md §6, architecture.md §8).

Will turn a fused element list into a graph: each element becomes a node,
and relationships (CONTAINS, ABOVE, BELOW, LEFT_OF, RIGHT_OF, ALIGNED_WITH,
OVERLAPS, ORDERED_BEFORE) are inferred from semantics and geometry rather
than generating every mathematically possible relation. Not implemented
yet.
"""
