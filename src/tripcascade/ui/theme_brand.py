"""TripCascade brand theme for the Gradio UI (brand package v1, 2026-08-31).

Derived from the brand package tokens
(`pi skills/visualization-and-design/brands/tripcascade/tokens.json`) via
`tokens_to_gui.py`, then adapted in two documented ways:

1. The generator emits Nunito (display stack) as the base font; brand law
   (`rules.md` display-family) puts body text in the Source Sans 3 stack and
   reserves Nunito for display/headings. Body stack here; display stack is
   applied to headings/wordmark via BLOCKS_CSS in app.py.
2. All values are token hexes; the only derived value is the primary-button
   hover shade (Cascade Teal at −20% lightness, per the generator's rule).

Rules honored: teal-signal-only, coral-graphic-only, text-contrast-floor
(token pairs precomputed in DESIGN.md §2), no-gradients, body-min-size.
"""

import gradio as gr

# Brand tokens (brands/tripcascade/tokens.json)
MIST = "#FBFEFD"        # color.background
SEAFOAM_TINT = "#EFF7F6"  # color.surface
DEEP_INK = "#14343B"    # color.foreground
HARBOR = "#48666E"      # color.muted
SHORELINE = "#D4E4E2"   # color.border
TEAL = "#0E7C7B"        # color.accent
TEAL_HOVER = "#0B6362"  # derived: accent −20% lightness
SEAFOAM = "#DFF0EE"     # color.brand.seafoam
CASCADE_MID = "#2A9D8F"  # color.brand.cascadeMid
CORAL_INK = "#B23E24"   # color.brand.coralInk (text-safe warm alert)
ALL_CLEAR = "#257446"   # color.success
WATCH_AMBER = "#8A5F00"  # color.warning
DISRUPTION_RED = "#C0392B"  # color.danger

FONT_DISPLAY = ["Nunito", "Trebuchet MS", "Verdana", "sans-serif"]
FONT_BODY = ["Source Sans 3", "Source Sans Pro", "Helvetica Neue", "Arial", "sans-serif"]
FONT_MONO = ["JetBrains Mono", "Menlo", "Consolas", "monospace"]

tripcascade_theme = (
    gr.themes.Base(font=FONT_BODY, font_mono=FONT_MONO)
    .set(
        body_background_fill=MIST,
        block_background_fill=SEAFOAM_TINT,
        body_text_color=DEEP_INK,
        body_text_color_subdued=HARBOR,
        border_color_primary=SHORELINE,
        border_color_accent=TEAL,
        color_accent=TEAL,
        button_primary_background_fill=TEAL,
        button_primary_text_color=MIST,
        button_primary_background_fill_hover=TEAL_HOVER,
        button_primary_border_color=TEAL,
        button_secondary_background_fill=SEAFOAM_TINT,
        button_secondary_text_color=DEEP_INK,
        button_secondary_border_color=SHORELINE,
        input_background_fill=MIST,
        input_border_color=SHORELINE,
        block_radius="14px",
        # Gradio 6 splits button_radius into per-size vars (generator targets 4/5)
        button_large_radius="999px",
        button_medium_radius="999px",
        button_small_radius="999px",
        input_radius="999px",
    )
)
