"""Palette and size constants for the prettygraph renderer."""

from __future__ import annotations

NODE_KINDS: dict[str, tuple[str, str]] = {
    "source": ("#e6ecff", "#4C78A8"),
    "io": ("#e6ecff", "#4C78A8"),
    "network": ("#f2e6ff", "#8E6FB6"),
    "compute": ("#e6ffee", "#82b366"),
    "process": ("#e6ffee", "#82b366"),
    "messaging": ("#ffe6e6", "#b85450"),
    "data": ("#e6ecff", "#3b5b92"),
    "monitoring": ("#fff5e6", "#d79b00"),
    "aux": ("#fff5e6", "#d79b00"),
    "security": ("#ffe6e6", "#c0504d"),
    "neutral": ("#f5f5f5", "#999999"),
    "ml_input": ("#d5e8d4", "#82b366"),
    "ml_output": ("#d5e8d4", "#5a9148"),
    "ml_conv": ("#dae8fc", "#6c8ebf"),
    "ml_pool": ("#dae8fc", "#5a7aad"),
    "ml_attention": ("#e1d5e7", "#9673a6"),
    "ml_transformer": ("#e1d5e7", "#7b5ea7"),
    "ml_rnn": ("#fff2cc", "#d6b656"),
    "ml_lstm": ("#fff2cc", "#c8a838"),
    "ml_fc": ("#ffe6cc", "#d79b00"),
    "ml_dense": ("#ffe6cc", "#c88c00"),
    "ml_loss": ("#f8cecc", "#b85450"),
    "ml_norm": ("#f5f5f5", "#888888"),
    "ml_embed": ("#fff0d6", "#c87000"),
}

CLUSTER_KINDS: dict[str, tuple[str, str]] = {
    "Compute": ("#fff5e6", "#e0b878"),
    "Database": ("#e6ecff", "#9db0d6"),
    "IoT": ("#e6ffee", "#9cc99c"),
    "Management": ("#ffe6f2", "#d9a6c2"),
    "Network": ("#f2e6ff", "#c3aede"),
    "Security": ("#ffe6e6", "#d9a3a3"),
    "Storage": ("#e6ffe6", "#a3cca3"),
    "Neutral": ("#fafafa", "#cfcfcf"),
    "ML_Input": ("#edf7ed", "#82b366"),
    "ML_Embedding": ("#fff8e6", "#d6a030"),
    "ML_Encoder": ("#e8eeff", "#6c8ebf"),
    "ML_Attention": ("#f0eaf8", "#9673a6"),
    "ML_Decoder": ("#e8f4ff", "#5a89b4"),
    "ML_Output": ("#edf7ed", "#4f9147"),
    "ML_Training": ("#fff5e6", "#d0903a"),
    "ML_Inference": ("#e6f2ff", "#4a7bb5"),
    "ML_Pipeline": ("#fafafa", "#aaaaaa"),
}

PRO_ACCENTS: dict[str, tuple[str, str, str]] = {
    "blue": ("#E3EDFD", "#2563EB", "#F4F8FE"),
    "cyan": ("#DEF3F9", "#0891B2", "#F2FBFD"),
    "teal": ("#DEF3EF", "#0D9488", "#F2FBF9"),
    "violet": ("#ECE4FD", "#7C3AED", "#F8F5FE"),
    "indigo": ("#E5E8FD", "#4F46E5", "#F5F6FE"),
    "green": ("#E0F4E9", "#059669", "#F2FBF6"),
    "amber": ("#FCEFD7", "#D97706", "#FEF9EF"),
    "rose": ("#FBE3E8", "#E11D48", "#FEF4F6"),
    "slate": ("#E7EBF0", "#475569", "#F5F7F9"),
}
PRO_ORDER = ["blue", "cyan", "teal", "violet", "indigo", "green"]
PRO_EDGE = "#334155"
PRO_TITLE = "#0F172A"
PRO_MUTED = "#64748B"

EDGE_COLOR = "#5A6573"
EDGE_FONTCOLOR = "#3f4a57"
FONT = "Helvetica"

FLOW_COLORS: dict[str, tuple[str, str]] = {
    "data": ("#2563EB", "solid"),
    "control": ("#64748B", "dashed"),
    "serving": ("#0D9488", "solid"),
    "registry": ("#7C3AED", "solid"),
    "monitoring": ("#D97706", "dashed"),
    "security": ("#E11D48", "dashed"),
}

# ---- draw.io theme tokens (ported from drawio-ai-kit/src/theme.mjs) ---------- #
# A small, cohesive set of PALE, theme-aware ``light-dark(light,dark)`` tints so a
# native .drawio looks correct in BOTH draw.io light and dark mode. AWS icons carry
# the strong category colour; frames/bands stay pale. Consumed by the native-stencil
# export path (icons keep their catalog style; containers/bands use these tokens).
DRAWIO_THEME: dict[str, object] = {
    # per-stage pipeline frame tints (stages[i % len]) + matching strokes
    "stages": [
        "light-dark(#eaf3ec,#16241b)",  # green  (ingest)
        "light-dark(#fff3e9,#2a1d12)",  # orange (process)
        "light-dark(#fff8e6,#2a2410)",  # amber  (store)
        "light-dark(#f3eef8,#241b2e)",  # purple (serve)
        "light-dark(#e9eef4,#19222e)",  # blue-grey
    ],
    "stage_stroke": ["#82B366", "#D79B00", "#D6B656", "#9673A6", "#6C8EBF"],
    "base": "light-dark(#ffffff,#0f1620)",
    "base_stroke": "#5A6B7B",
    "endpoint": "light-dark(#eaf3ff,#10202e)",
    "endpoint_stroke": "#6C8EBF",
    "band": "light-dark(#eef1f5,#1b2430)",
    "band_stroke": "#8593A3",
    # AWS-convention container colours
    "subnet_public": "light-dark(#eef5e6,#1a2410)",
    "subnet_public_stroke": "#7AA116",
    "subnet_private": "light-dark(#e6f4f4,#0f2424)",
    "subnet_private_stroke": "#00A4A6",
    "region_stroke": "#147EBA",
    "vpc_stroke": "#8C4FFF",
    "account_stroke": "#C2487A",
    "az_stroke": "#2F9491",
    "note": "light-dark(#fbe7d4,#3a2a16)",
    "note_stroke": "#D79B00",
    "onprem": "light-dark(#eef1f5,#181f29)",
    "onprem_stroke": "#666666",
    "font_color": "light-dark(#1B2733,#CFE0F0)",
    "edge_stroke": "light-dark(#2D6A9F,#5B9BD5)",
    "edge_stroke_width": 2,
    "edge_label_bg": "light-dark(#FFFFFF,#0B0F14)",
}


def drawio_stage_fill(i: int) -> str:
    stages = DRAWIO_THEME["stages"]
    return stages[i % len(stages)]


def drawio_stage_stroke(i: int) -> str:
    strokes = DRAWIO_THEME["stage_stroke"]
    return strokes[i % len(strokes)]


PAGE_SIZE = "20,13"
SLIDE_SIZE = 2048
SLIDE_HERO_H = 620
SLIDE_MARGIN = 38
SLIDE_PANEL_PAD = 26
SLIDE_PAGE_RATIO = 16 / 9
FLOW_GRID_MIN = 3
