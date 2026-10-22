import pandas as pd


def load_flow(path):
    """Daily flow series (ML/day) from a CSV with columns date, flow_ML_d."""
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    return df["flow_ML_d"].asfreq("D")


def water_year(index):
    """Water year (Jul-Jun) labelled by the year it ends in."""
    return index.year + (index.month >= 7)


def spells(mask):
    """(start, length) of each run of True in a boolean daily series."""
    run_id = (mask != mask.shift()).cumsum()
    return [(g.index[0], len(g)) for _, g in mask[mask].groupby(run_id[mask])]
