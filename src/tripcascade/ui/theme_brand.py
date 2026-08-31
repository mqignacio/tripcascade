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

# Gradio 6 note: the primary button reads var(--primary-600) — a direct
# .set(button_primary_background_fill=...) loses cascade order to the default,
# so the brand teal goes in as a custom primary SCALE (the pattern the old
# gold/navy theme proved). Neutral scale carries the mist/seafoam/ink family.
TEAL_HUE = gr.themes.Color(
    c50="#E6F4F3", c100="#CCEAE8", c200="#9CD6D2", c300="#5BB8B2",
    c400="#2A9D8F", c500="#0E7C7B", c600="#0E7C7B", c700="#0B6362",
    c800="#094F4F", c900="#073D3D", c950="#052C2C", name="tripcascade-teal",
)
HARBOR_HUE = gr.themes.Color(
    c50="#FBFEFD", c100="#EFF7F6", c200="#DFF0EE", c300="#D4E4E2",
    c400="#A9C4C0", c500="#7FA09B", c600="#5C7A76", c700="#48666E",
    c800="#2E4A50", c900="#14343B", c950="#0B2226", name="tripcascade-harbor",
)

tripcascade_theme = (
    gr.themes.Soft(
        font=FONT_BODY,
        font_mono=FONT_MONO,
        primary_hue=TEAL_HUE,
        neutral_hue=HARBOR_HUE,
    )
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
        # Pin the dark scheme to the same brand values: the brand is light-first
        # and Gradio auto-switches on prefers-color-scheme (headless Chrome and
        # dark-mode macOS alike). Dark tokens would otherwise render neutral_950.
        body_background_fill_dark=MIST,
        background_fill_primary_dark=MIST,       # Soft default: *neutral_950 (the dark page wash)
        background_fill_secondary_dark=SEAFOAM_TINT,
        block_background_fill_dark=SEAFOAM_TINT,
        checkbox_background_color_dark=SEAFOAM_TINT,
        code_background_fill_dark=SEAFOAM_TINT,
        table_even_background_fill_dark=MIST,
        table_odd_background_fill_dark=SEAFOAM_TINT,
        body_text_color_dark=DEEP_INK,
        body_text_color_subdued_dark=HARBOR,
        border_color_primary_dark=SHORELINE,
        border_color_accent_dark=TEAL,
        button_primary_background_fill_dark=TEAL,
        button_primary_text_color_dark=MIST,
        button_primary_background_fill_hover_dark=TEAL_HOVER,
        button_primary_border_color_dark=TEAL,
        button_secondary_background_fill_dark=SEAFOAM_TINT,
        button_secondary_text_color_dark=DEEP_INK,
        button_secondary_border_color_dark=SHORELINE,
        input_background_fill_dark=MIST,
        input_border_color_dark=SHORELINE,
        block_radius="14px",
        # Gradio 6 splits button_radius into per-size vars (generator targets 4/5)
        button_large_radius="999px",
        button_medium_radius="999px",
        button_small_radius="999px",
        input_radius="999px",
    )
)
