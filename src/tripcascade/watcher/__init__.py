"""Disruption Watcher: scheduled forecast-poll (P0) + Atlas webhook/incident
events (P1 stretch) -> emits `disruption_likely` events to the orchestrator.
Webhook delivery is best-effort (doc/atlas_surface.md §3); poll stays the
guaranteed trigger. Cloud deployment on Alibaba Cloud Function Compute.
"""
