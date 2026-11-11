"""Shared colours + helpers for the animated accent theme."""

BLACK = "#0b0b0d"
BG = "#111214"
SIDEBAR = "#141417"
CARD = "#1c1d21"
CARD_DARK = "#151619"
MUTED = "#8b8d94"
TEXT = "#d9dadd"
GREY = "#2a2c31"
GREY_HOVER = "#383b42"

# section accents
LIGHT_BLUE = "#4cc2ff"
LIGHT_BLUE_HOVER = "#2b9fe0"
RED = "#ff2e43"
RED_HOVER = "#c81f32"
TWITCH = "#9146ff"
TWITCH_HOVER = "#6f2fd6"
SETTINGS = "#a0a4ad"


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def mix(a, b, t):
    """Blend colour a -> b by t (0..1)."""
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def tint(accent, amount=0.075, base=BLACK):
    """Very dark background tinted with the accent colour."""
    return mix(base, accent, amount)


def ease(t):
    return 1 - (1 - t) ** 3  # ease-out cubic
