"""
CustomerAI theme.

Serif typography (Cormorant Garamond for display and figures, Source Serif 4
for body text), animated backgrounds (black and blue for the dark theme,
white and gray with a green tint for the light theme), glass panels and a
compact single-row KPI strip with hover tooltips. No emoji or pictograph
characters anywhere.
"""

FONT_DISPLAY = "'Cormorant Garamond', 'Playfair Display', Georgia, 'Times New Roman', serif"
FONT_BODY = "'Source Serif 4', 'Source Serif Pro', Georgia, 'Times New Roman', serif"
FONT_PLOTLY = "Source Serif 4, Source Serif Pro, Georgia, Times New Roman, serif"

LIGHT = {
    "name": "light",
    "text": "#12201A",
    "muted": "#56655D",
    "border": "rgba(18, 32, 26, 0.13)",
    "panel_bg": "rgba(255, 255, 255, 0.82)",
    "solid": "#FFFFFF",
    "sidebar_bg": "rgba(250, 252, 250, 0.80)",
    "accent": "#0E6B4D",
    "accent_soft": "rgba(14, 107, 77, 0.10)",
    "accent2": "#6F8F82",
    "gold": "#9A6B1B",
    "red": "#A23B3B",
    "green": "#1E7F4F",
    "slate": "#7A8780",
    "grid": "rgba(18, 32, 26, 0.08)",
    "tip_bg": "#12201A",
    "tip_fg": "#F2F6F3",
    "shadow": "0 1px 2px rgba(18, 32, 26, 0.05), 0 10px 28px rgba(18, 32, 26, 0.06)",
    "series": ["#0E6B4D", "#6F8F82", "#9A6B1B", "#3F6E8C", "#A23B3B", "#7A8780"],
}

DARK = {
    "name": "dark",
    "text": "#E9EEF8",
    "muted": "#93A0BC",
    "border": "rgba(120, 156, 230, 0.20)",
    "panel_bg": "rgba(7, 11, 22, 0.74)",
    "solid": "#0A0F1C",
    "sidebar_bg": "rgba(4, 7, 14, 0.82)",
    "accent": "#5B9DFF",
    "accent_soft": "rgba(91, 157, 255, 0.16)",
    "accent2": "#38BDF8",
    "gold": "#E8B55B",
    "red": "#F27A7A",
    "green": "#3DDC97",
    "slate": "#7C89A6",
    "grid": "rgba(147, 160, 188, 0.14)",
    "tip_bg": "#0B1324",
    "tip_fg": "#E9EEF8",
    "shadow": "0 1px 2px rgba(0, 0, 0, 0.5), 0 14px 34px rgba(0, 0, 0, 0.35)",
    "series": ["#5B9DFF", "#38BDF8", "#E8B55B", "#7C89A6", "#F27A7A", "#3DDC97"],
}


def tokens(dark: bool) -> dict:
    return DARK if dark else LIGHT


def tier_colors(dark: bool) -> dict:
    t = tokens(dark)
    return {"High": t["accent"], "Medium": t["gold"], "Low": t["slate"]}


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


_BACKGROUND_LIGHT = """
    .stApp { background: linear-gradient(135deg, #FFFFFF 0%, #F1F4F2 48%, #E3E9E5 100%); }
    .stApp::before {
        background:
            radial-gradient(38% 38% at 16% 20%, rgba(14, 107, 77, 0.15), transparent 70%),
            radial-gradient(34% 34% at 84% 16%, rgba(122, 135, 128, 0.22), transparent 70%),
            radial-gradient(42% 42% at 58% 92%, rgba(14, 107, 77, 0.11), transparent 70%),
            radial-gradient(30% 30% at 4% 86%, rgba(255, 255, 255, 0.95), transparent 70%);
    }
    .stApp::after { background-image: radial-gradient(rgba(18, 32, 26, 0.055) 1px, transparent 1px); }
"""

_BACKGROUND_DARK = """
    .stApp { background: #02040A; }
    .stApp::before {
        background:
            radial-gradient(40% 40% at 14% 18%, rgba(37, 99, 235, 0.42), transparent 70%),
            radial-gradient(34% 34% at 86% 14%, rgba(56, 189, 248, 0.24), transparent 70%),
            radial-gradient(46% 46% at 56% 96%, rgba(29, 78, 216, 0.36), transparent 70%),
            radial-gradient(28% 28% at 2% 90%, rgba(30, 41, 99, 0.55), transparent 70%);
    }
    .stApp::after { background-image: radial-gradient(rgba(160, 190, 255, 0.07) 1px, transparent 1px); }
"""

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600;8..60,700&display=swap');

:root {
    --font-display: __FONT_DISPLAY__;
    --font-body: __FONT_BODY__;
    --text: __TEXT__; --muted: __MUTED__; --border: __BORDER__;
    --accent: __ACCENT__; --accent-soft: __ACCENT_SOFT__;
    --panel-bg: __PANEL_BG__; --solid: __SOLID__;
}

html, body, .stApp, [data-testid="stSidebar"], button, input, textarea, [data-baseweb] {
    font-family: var(--font-body);
}
.stApp { color: var(--text); isolation: isolate; font-size: 15px; }
#MainMenu, footer { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }
/* Keep the header toolbar: it holds the button that reopens a closed sidebar.
   Only the Deploy button and the three-dot menu are hidden. */
[data-testid="stAppDeployButton"], .stDeployButton, [data-testid="stMainMenu"] { display: none !important; }
[data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] {
    visibility: visible !important; opacity: 1 !important; z-index: 1000001;
}
[data-testid="stExpandSidebarButton"] {
    background: var(--solid); border: 1px solid var(--border); border-radius: 8px;
}

/* ---- Animated background ---- */
.stApp::before, .stApp::after {
    content: ""; position: fixed; z-index: -1; pointer-events: none;
}
.stApp::before { inset: -25%; animation: caiDrift 30s ease-in-out infinite alternate; will-change: transform; }
.stApp::after { inset: 0; background-size: 26px 26px; opacity: 1; }
@keyframes caiDrift {
    0%   { transform: translate3d(0, 0, 0) scale(1); }
    50%  { transform: translate3d(3.5%, -2.5%, 0) scale(1.08); }
    100% { transform: translate3d(-3.5%, 3%, 0) scale(1.03); }
}
@media (prefers-reduced-motion: reduce) { .stApp::before { animation: none; } }
__BACKGROUND__

/* ---- Loading bar (Streamlit's native running indicator) ---- */
div[data-testid="stDecoration"] {
    background: linear-gradient(90deg, __ACCENT__, __ACCENT2__, __ACCENT__) !important;
    background-size: 200% 100% !important; height: 3px !important;
    animation: caiLoadingBar 1.1s linear infinite;
}
@keyframes caiLoadingBar { 0% { background-position: 0% 0; } 100% { background-position: -200% 0; } }

.block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1600px; }

/* ---- Text colours (set explicitly so both themes stay readable) ---- */
[data-testid="stMarkdownContainer"] :is(p, li, span, strong, em, td, th) { color: var(--text); }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * { color: var(--muted) !important; }
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] * { color: var(--text) !important; font-size: 13px; }
h1, h2, h3, h4 { font-family: var(--font-display); color: var(--text) !important; letter-spacing: 0.005em; }
h1, div[data-testid="stAppViewContainer"] h1 {
    font-size: 40px !important; font-weight: 600 !important; line-height: 1.05 !important;
    margin: 0 0 2px 0 !important; padding: 0 !important;
}
.subtitle { color: var(--muted); font-size: 14px; letter-spacing: 0.02em; margin: 0 0 18px 0; }
.eyebrow {
    font-size: 10.5px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--accent);
    font-weight: 600; margin-bottom: 4px;
}
[data-testid="stAlert"] * { color: inherit; }

/* ---- File uploader (keeps the drop zone on-theme in dark mode) ---- */
[data-testid="stFileUploaderDropzone"] { background: var(--accent-soft); border: 1px dashed var(--border); border-radius: 10px; }
[data-testid="stFileUploaderDropzone"] * { color: var(--text); }

/* ---- Sidebar ---- */
section[data-testid="stSidebar"] {
    background: __SIDEBAR_BG__; border-right: 1px solid var(--border);
    -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px);
    min-width: 250px !important; max-width: 260px !important;
}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] :is(p, span, strong) { color: var(--text); }
.brand-name { font-family: var(--font-display); font-size: 30px; font-weight: 700; line-height: 1; color: var(--text); }
.brand-tag { font-size: 10px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--muted); margin: 4px 0 14px; }
.status-pill {
    display: inline-block; font-size: 11.5px; padding: 4px 10px; border-radius: 999px;
    border: 1px solid var(--border); color: var(--muted); background: var(--accent-soft);
}
.status-pill b { color: var(--text); font-weight: 600; }
.status-bad { border-color: __RED__; color: __RED__; background: transparent; }

section[data-testid="stSidebar"] [role="radiogroup"] { gap: 2px; }
section[data-testid="stSidebar"] [role="radiogroup"] label {
    padding: 9px 12px; border-radius: 8px; border-left: 2px solid transparent; width: 100%;
    transition: background 0.15s ease, border-color 0.15s ease;
}
section[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child { display: none; }
section[data-testid="stSidebar"] [role="radiogroup"] label p { font-size: 14.5px; letter-spacing: 0.01em; }
section[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: var(--accent-soft); }
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
    background: var(--accent-soft); border-left-color: var(--accent);
}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p { font-weight: 700; color: var(--accent); }

/* ---- Panels (keyed containers: st.container(key="panel_x")) ---- */
div[class*="st-key-panel_"] {
    background: var(--panel-bg); border: 1px solid var(--border); border-radius: 14px;
    padding: 16px 18px 12px 18px; box-shadow: __SHADOW__;
    -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
    position: relative; margin-bottom: 4px;
}
div[class*="st-key-panel_"]::before {
    content: ""; position: absolute; left: 18px; top: -1px; width: 44px; height: 2px;
    background: var(--accent); border-radius: 2px;
}
.panel-title { font-family: var(--font-display); font-size: 21px; font-weight: 700; color: var(--text); line-height: 1.15; }
.panel-caption { font-size: 12.5px; color: var(--muted); margin: 3px 0 6px 0; line-height: 1.45; }
.insight {
    font-size: 12.5px; color: var(--muted); line-height: 1.5; margin-top: 4px; padding: 6px 0 2px 10px;
    border-left: 2px solid var(--accent);
}
.insight b { color: var(--text); font-weight: 600; }

/* ---- Compact KPI strip with hover tooltips ---- */
.kpi-strip {
    display: flex; background: var(--panel-bg); border: 1px solid var(--border); border-radius: 12px;
    box-shadow: __SHADOW__; margin: 2px 0 14px 0; position: relative; z-index: 20;
    -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
}
.kpi-seg { flex: 1 1 0; padding: 9px 16px 10px 16px; border-right: 1px solid var(--border); position: relative; cursor: help; min-width: 0; }
.kpi-seg:first-child { border-radius: 12px 0 0 12px; }
.kpi-seg:last-child { border-right: none; border-radius: 0 12px 12px 0; }
.kpi-seg::before {
    content: ""; position: absolute; top: -1px; left: 0; right: 0; height: 2px;
    background: var(--kpi-accent, var(--accent));
}
.kpi-seg:first-child::before { border-radius: 12px 0 0 0; }
.kpi-seg:last-child::before { border-radius: 0 12px 0 0; }
.kpi-seg-title { font-size: 9.5px; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase; color: var(--muted); white-space: nowrap; }
.kpi-seg-value {
    font-family: var(--font-display); font-size: 25px; font-weight: 700; color: var(--text);
    line-height: 1.1; margin-top: 1px; font-variant-numeric: lining-nums tabular-nums;
    font-feature-settings: "lnum" 1, "tnum" 1; white-space: nowrap;
}
.kpi-seg-sub { font-size: 11px; color: var(--muted); margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi-tip {
    position: absolute; left: 10px; top: 100%; margin-top: 10px; width: 280px; z-index: 1000;
    background: __TIP_BG__; color: __TIP_FG__; border: 1px solid __ACCENT__; border-radius: 10px;
    padding: 11px 14px; box-shadow: 0 18px 40px rgba(0, 0, 0, 0.35);
    opacity: 0; transform: translateY(-4px); pointer-events: none; transition: opacity 0.16s ease, transform 0.16s ease;
}
.kpi-seg:nth-last-child(-n+2) .kpi-tip { left: auto; right: 10px; }
.kpi-seg:hover .kpi-tip { opacity: 1; transform: none; }
.kpi-tip b { display: block; font-family: var(--font-display); font-size: 17px; font-weight: 700; margin-bottom: 3px; color: __TIP_FG__; }
.kpi-tip span { display: block; font-size: 12.5px; line-height: 1.5; color: __TIP_FG__; opacity: 0.92; }

.mini-label { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); margin: 0 0 -6px 2px; }

/* ---- Inputs ---- */
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
.stTextInput input, .stNumberInput input {
    background-color: var(--solid) !important; color: var(--text) !important; border-color: var(--border) !important;
}
[data-baseweb="select"] *, .stTextInput input { color: var(--text) !important; }
[data-baseweb="tag"] { background-color: var(--accent-soft) !important; }
[data-baseweb="tag"] * { color: var(--text) !important; }
[data-baseweb="popover"], [data-baseweb="menu"], ul[role="listbox"] { background-color: var(--solid) !important; }
ul[role="listbox"] li, ul[role="listbox"] li * { color: var(--text) !important; }

/* ---- Form controls in current Streamlit (react-aria based; the rules above cover older versions) ---- */
[data-testid="stMultiSelect"] div[role="group"][data-rac],
[data-testid="stSelectbox"] div[role="group"][data-rac],
[data-testid="stTextInputRootElement"],
[data-testid="stNumberInputContainer"] {
    background: var(--solid) !important; border: 1px solid var(--border) !important; border-radius: 8px !important;
}
[data-testid="stMultiSelect"] div[role="group"][data-rac]:focus-within,
[data-testid="stSelectbox"] div[role="group"][data-rac]:focus-within,
[data-testid="stTextInputRootElement"]:focus-within { border-color: var(--accent) !important; }
[data-testid="stMultiSelect"] input, [data-testid="stSelectbox"] input,
[data-testid="stTextInputRootElement"] input {
    color: var(--text) !important; -webkit-text-fill-color: var(--text) !important; background: transparent !important;
}
[data-testid="stMultiSelect"] input::placeholder, [data-testid="stSelectbox"] input::placeholder,
[data-testid="stTextInputRootElement"] input::placeholder { color: var(--muted) !important; -webkit-text-fill-color: var(--muted) !important; opacity: 1; }
[data-testid="stMultiSelect"] svg, [data-testid="stSelectbox"] svg { fill: var(--muted); color: var(--muted); }
div[data-testid$="VirtualDropdown"], div[role="listbox"] {
    background: var(--solid) !important; border: 1px solid var(--border); border-radius: 8px;
}
div[role="listbox"] [role="option"], div[role="listbox"] [role="option"] * { color: var(--text) !important; }
div[role="listbox"] [role="option"]:hover, div[role="listbox"] [role="option"][aria-selected="true"] { background: var(--accent-soft) !important; }

/* ---- Help (?) icons beside widget labels ---- */
[data-testid="stTooltipIcon"] button, [data-testid="stTooltipHoverTarget"] button { background: transparent !important; border: none !important; color: var(--muted) !important; }
[data-testid="stTooltipIcon"] svg { fill: none !important; stroke: var(--muted) !important; }

/* ---- Buttons ---- */
.stButton button, .stDownloadButton button {
    border-radius: 8px !important; font-weight: 600; letter-spacing: 0.02em;
    border: 1px solid var(--accent) !important; background: transparent !important; color: var(--accent) !important;
}
.stButton button p, .stDownloadButton button p { color: var(--accent) !important; }
.stButton button:hover, .stDownloadButton button:hover { background: var(--accent) !important; }
.stButton button:hover p, .stDownloadButton button:hover p { color: __BTN_HOVER_TEXT__ !important; }

/* ---- Tabs and expanders ---- */
.stTabs [data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid var(--border); }
.stTabs [data-baseweb="tab"] { height: 38px; font-size: 14px; color: var(--muted); }
.stTabs [aria-selected="true"] { color: var(--accent) !important; }
[data-testid="stExpander"] { border: 1px solid var(--border) !important; border-radius: 10px; background: var(--panel-bg); }
[data-testid="stExpander"] summary * { color: var(--text) !important; }

/* ---- Tables ---- */
div[data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; __DATAFRAME_FILTER__ }

/* ---- Plotly (hover labels are styled in the figure itself) ---- */
.js-plotly-plot .plotly .main-svg { border-radius: 8px; }
</style>
"""


def get_css(dark: bool = False) -> str:
    t = tokens(dark)
    replacements = {
        "__FONT_DISPLAY__": FONT_DISPLAY,
        "__FONT_BODY__": FONT_BODY,
        "__TEXT__": t["text"],
        "__MUTED__": t["muted"],
        "__BORDER__": t["border"],
        "__ACCENT__": t["accent"],
        "__ACCENT2__": t["accent2"],
        "__ACCENT_SOFT__": t["accent_soft"],
        "__PANEL_BG__": t["panel_bg"],
        "__SOLID__": t["solid"],
        "__SIDEBAR_BG__": t["sidebar_bg"],
        "__SHADOW__": t["shadow"],
        "__TIP_BG__": t["tip_bg"],
        "__TIP_FG__": t["tip_fg"],
        "__RED__": t["red"],
        "__BTN_HOVER_TEXT__": "#02040A" if dark else "#FFFFFF",
        "__BACKGROUND__": _BACKGROUND_DARK if dark else _BACKGROUND_LIGHT,
        # Streamlit's data grid is drawn on a canvas that follows Streamlit's own
        # (light) theme, so the dark theme inverts it to match.
        "__DATAFRAME_FILTER__": "filter: invert(0.92) hue-rotate(180deg);" if dark else "",
    }
    css = _CSS
    for token, value in replacements.items():
        css = css.replace(token, value)
    return css


def kpi_strip(segments: list) -> str:
    """Single-row KPI strip. Each segment is a dict with title, value and
    optional sub (small note), tip_title, tip (hover tooltip) and accent."""
    parts = ['<div class="kpi-strip">']
    for seg in segments:
        style = f' style="--kpi-accent:{seg["accent"]}"' if seg.get("accent") else ""
        sub = f'<div class="kpi-seg-sub">{seg["sub"]}</div>' if seg.get("sub") else ""
        tip = ""
        if seg.get("tip"):
            tip = f'<div class="kpi-tip"><b>{seg.get("tip_title", seg["title"])}</b><span>{seg["tip"]}</span></div>'
        parts.append(
            f'<div class="kpi-seg"{style}><div class="kpi-seg-title">{seg["title"]}</div>'
            f'<div class="kpi-seg-value">{seg["value"]}</div>{sub}{tip}</div>'
        )
    parts.append("</div>")
    return "".join(parts)


def panel_header(title: str, caption: str = None) -> str:
    cap = f'<div class="panel-caption">{caption}</div>' if caption else ""
    return f'<div class="panel-title">{title}</div>{cap}'


def insight_html(text: str) -> str:
    return f'<div class="insight">{text}</div>'


def plotly_layout(dark: bool, height: int) -> dict:
    t = tokens(dark)
    return dict(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_PLOTLY, color=t["text"], size=12.5),
        margin=dict(l=6, r=22, t=18, b=6),
        colorway=t["series"],
        showlegend=False,
        hoverlabel=dict(
            bgcolor=t["tip_bg"], bordercolor=t["accent"], align="left",
            font=dict(family=FONT_PLOTLY, size=13, color=t["tip_fg"]),
        ),
    )


def style_axes(fig, dark: bool, x_title: str = None, y_title: str = None, grid_x: bool = True, grid_y: bool = True):
    t = tokens(dark)
    # automargin lets Plotly grow the margin to fit tick labels and axis titles;
    # without it, long category names (products, personas) are clipped away.
    axis = dict(linecolor=t["border"], zeroline=False, tickfont=dict(size=11.5, color=t["muted"]),
                title_font=dict(size=12, color=t["muted"]), ticks="", automargin=True, title_standoff=10)
    fig.update_xaxes(gridcolor=t["grid"], showgrid=grid_x, title_text=x_title, **axis)
    fig.update_yaxes(gridcolor=t["grid"], showgrid=grid_y, title_text=y_title, **axis)
    return fig
