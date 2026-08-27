"""Dependency graph: itinerary as a DAG of leg/commitment nodes.

Nodes carry temporal + booking constraints and an evidence-based `actionable`
flag (flights actionable; hotels/activities advisory). Edges are dependencies.
See doc/SPECS.md §4 (Data Model) and doc/atlas_surface.md §4.
"""
