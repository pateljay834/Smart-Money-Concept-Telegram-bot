import os
import tempfile

import matplotlib
matplotlib.use("Agg")  # headless backend — avoids GUI-backend issues on Windows when run non-interactively
import matplotlib.pyplot as plt
import mplfinance as mpf

from smc_engine import compute_indicators


def plot_chart(symbol: str, ohlc, signal, out_dir: str = None) -> str:
    """
    Renders the chart into a temp file (or out_dir if given) and returns
    its path. Caller is responsible for deleting it after use — see
    core.cleanup_file(). Nothing is written into the project folder itself,
    so nothing accumulates on disk run after run.
    """
    swings, structure, order_blocks, fvg, liquidity = compute_indicators(ohlc)

    # smartmoneyconcepts returns dataframes indexed by row POSITION (0..n-1)
    # in `ohlc`, not by date. Map position -> actual date via ohlc.index
    # before comparing against plot_df's date index — this is what makes
    # the overlays actually appear on the chart.
    full_dates = ohlc.index

    plot_df = ohlc.tail(120).copy()

    fig, axlist = mpf.plot(
        plot_df,
        type="candle",
        style="charles",
        title=f"{symbol}  |  {signal.direction}  (score {signal.score})",
        volume=True,
        returnfig=True,
        figsize=(11, 7),
    )
    ax = axlist[0]

    def position_to_date(pos):
        return full_dates[pos] if 0 <= pos < len(full_dates) else None

    unmitigated_fvg = fvg[(fvg["MitigatedIndex"].isna() | (fvg["MitigatedIndex"] == 0))]
    for pos, row in unmitigated_fvg.tail(15).iterrows():
        ts = position_to_date(pos)
        if ts is None or ts not in plot_df.index:
            continue
        x = plot_df.index.get_loc(ts)
        color = "green" if row["FVG"] == 1 else "red"
        ax.axhspan(row["Bottom"], row["Top"], xmin=max(0, (x - 1) / len(plot_df)), xmax=1, color=color, alpha=0.12)

    unmitigated_ob = order_blocks[(order_blocks["MitigatedIndex"].isna() | (order_blocks["MitigatedIndex"] == 0))]
    for pos, row in unmitigated_ob.tail(6).iterrows():
        ts = position_to_date(pos)
        if ts is None or ts not in plot_df.index:
            continue
        x = plot_df.index.get_loc(ts)
        color = "royalblue" if row["OB"] == 1 else "darkorange"
        ax.axhspan(row["Bottom"], row["Top"], xmin=max(0, (x - 1) / len(plot_df)), xmax=1, color=color, alpha=0.15)

    if signal.entry:
        ax.axhline(signal.entry, color="black", linestyle="--", linewidth=1, label="Entry")
        ax.axhline(signal.stop_loss, color="red", linestyle="--", linewidth=1, label="Stop")
        ax.axhline(signal.target, color="green", linestyle="--", linewidth=1, label="Target")
        ax.legend(loc="upper left", fontsize=8)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{symbol.replace('.', '_')}.png")
    else:
        fd, path = tempfile.mkstemp(suffix=f"_{symbol.replace('.', '_')}.png")
        os.close(fd)

    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path
