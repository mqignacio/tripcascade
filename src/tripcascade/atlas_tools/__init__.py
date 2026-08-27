"""Atlas tool layer: hybrid CLI + REST substrate (see doc/atlas_surface.md §6).

Discovery (search/offer/price) = read-only, ungated. Commitment/Money/Aftercare
(verify/order/pay/ticketing/change/cancel/refund) route through the FR-006 policy
engine. Booking flow uses the `atlas-flight` CLI (subprocess + --json); webhook/
incident + aftercare use REST with x-atlas-client-id/secret from .env.
"""
