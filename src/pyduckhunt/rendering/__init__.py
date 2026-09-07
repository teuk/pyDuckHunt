"""Pure, byte-budgeted player-facing response rendering."""

from pyduckhunt.rendering.flight_appearance import (
    FLIGHT_BEAKS,
    FLIGHT_CALLS,
    FLIGHT_EYES,
    FLIGHT_LINES,
    FLIGHT_TRAILS,
    FLIGHT_WINGS,
    FlightAppearance,
    RandomizedFlightAppearanceSource,
)

from pyduckhunt.rendering.responses import (
    MAX_RESPONSE_LINES,
    render_detector_notice,
    render_inventory,
    render_last_flight,
    render_outcome,
    render_outcomes,
    render_profile,
    render_query,
    render_ranking,
    render_shop,
    render_wire_notice,
    render_wire_response,
)

__all__ = (
    "FLIGHT_BEAKS",
    "FLIGHT_CALLS",
    "FLIGHT_EYES",
    "FLIGHT_LINES",
    "FLIGHT_TRAILS",
    "FLIGHT_WINGS",
    "FlightAppearance",
    "MAX_RESPONSE_LINES",
    "RandomizedFlightAppearanceSource",
    "render_detector_notice",
    "render_inventory",
    "render_last_flight",
    "render_outcome",
    "render_outcomes",
    "render_profile",
    "render_query",
    "render_ranking",
    "render_shop",
    "render_wire_notice",
    "render_wire_response",
)
