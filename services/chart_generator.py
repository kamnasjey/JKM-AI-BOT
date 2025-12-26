
import io
import matplotlib
matplotlib.use("Agg") # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from typing import List, Dict, Any

def generate_chart_image(
    candles: List[Dict[str, Any]],
    pair_for_title: str,
    timeframe: str,
) -> io.BytesIO:
    """
    Generates a dark-themed candlestick chart.
    Expects candles to have 'time', 'open', 'high', 'low', 'close' keys.
    """
    if not candles:
        return io.BytesIO()

    # Data prep
    try:
        dates = [mdates.date2num(c["time"]) for c in candles]
        opens = [c["open"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]
    except KeyError as e:
        print(f"Chart data error: {e}")
        return io.BytesIO()

    # Styling
    bg_color = "#131722"
    grid_color = "#363c4e"
    text_color = "#d1d4dc"
    up_color = "#26a69a"
    down_color = "#ef5350"

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)

    # Spines
    for spine in ax.spines.values():
        spine.set_color(grid_color)

    # Ticks / Labels
    ax.tick_params(colors=text_color)
    ax.yaxis.label.set_color(text_color)
    ax.xaxis.label.set_color(text_color)

    # Calculate width
    if len(dates) > 1:
        width = (dates[-1] - dates[0]) / len(dates) * 0.6
    else:
        width = 0.0005

    # Plotting
    for x, o, h, l, c in zip(dates, opens, highs, lows, closes):
        color = up_color if c >= o else down_color
        # Wick
        ax.vlines(x, l, h, color=color, linewidth=0.8)
        # Body
        body_lower = min(o, c)
        body_height = abs(c - o)
        if body_height == 0:
            body_height = max((h - l) * 0.05, 0.0001)
            
        rect = Rectangle(
            (x - width / 2, body_lower),
            width,
            body_height,
            facecolor=color,
            edgecolor=color,
            linewidth=0.8,
        )
        ax.add_patch(rect)

    # Formatting axis
    ax.set_xlim(min(dates) - width*2, max(dates) + width*2)
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    plt.xticks(rotation=0)

    ax.set_title(f"{pair_for_title} – {timeframe}", color=text_color, fontsize=12, fontweight='bold')
    ax.grid(True, alpha=0.15, color=grid_color, linestyle='--')

    # Watermark (Optional)
    ax.text(0.5, 0.5, 'JKM TRADING BOT', transform=ax.transAxes,
            fontsize=30, color='gray', alpha=0.1,
            ha='center', va='center', rotation=30)

    # Save to buffer
    buf = io.BytesIO()
    plt.tight_layout()
    fig.savefig(buf, format="png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    
    return buf
