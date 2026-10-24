def water_year(index):
    """Water year (Jul-Jun) labelled by the year it ends in."""
    return index.year + (index.month >= 7)


def spells(mask):
    """(start, length) of each run of True in a boolean daily series."""
    run_id = (mask != mask.shift()).cumsum()
    return [(g.index[0], len(g)) for _, g in mask[mask].groupby(run_id[mask])]
