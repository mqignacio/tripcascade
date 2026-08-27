"""Disruption forecast: XGBoost classifier on historical on-time data.

Exports predict_disruption(leg_features) -> float P(disruption) in [0, 1].
Trained artifact + inference fn are produced in tasks/03-data_ml.md.
See doc/SPECS.md S-002 and doc/atlas_surface.md §1.2 (feature availability).
"""
