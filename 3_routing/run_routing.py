from routing import route_lateral_units

# Uncalibrated Muskingum parameters applied to every reach (stable for a 1-day step: 2KX <= 1 <= 2K(1-X)).
K_DAYS = 1.0
X = 0.2
M3S_TO_ML_DAY = 86.4

# Lowland corrections for what GR4J on its own cannot see (regulation, irrigation, seepage).
# Delivery: share of a unit's runoff that reaches the river. The semi-arid western plains (SC12) deliver little.
DELIVERY = {"SC12": 0.05}
# Loss: one fractional loss applied at every reach from LOSS_FROM downstream, calibrated so the mean
# outlet flow matches TARGET_OUTLET_M3S (recorded mean at Balranald, ~27 m3/s; Wikipedia, "Murrumbidgee River").
LOSS_FROM = "SC09"
TARGET_OUTLET_M3S = 27.0


def _route(runoff, loss, all_reaches=False):
    names = list(runoff.columns)
    lossy = names.index(LOSS_FROM)
    reaches = [{"name": n, "k_days": K_DAYS, "x": X, "loss": loss if i >= lossy else 0.0}
               for i, n in enumerate(names)]
    lateral = {n: runoff[n] * DELIVERY.get(n, 1.0) for n in names}
    routed = route_lateral_units(lateral, reaches)
    return routed if all_reaches else routed[names[-1]]


def _calibrate_loss(runoff):
    """Bisect the per-reach loss fraction so mean outlet flow hits the target (more loss -> less flow)."""
    lo, hi = 0.0, 0.99
    for _ in range(25):
        mid = (lo + hi) / 2
        if _route(runoff, mid).mean() > TARGET_OUTLET_M3S:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def run_routing(runoff):
    """Route lateral runoff (m3/s) down the river; return (flow, reach_flow) in ML/d.

    flow is the daily series at the outlet; reach_flow has one column per subcatchment reach outlet.
    """
    loss = _calibrate_loss(runoff)
    print(f"3_routing: calibrated per-reach loss from {LOSS_FROM} = {loss:.2f}")
    reach_flow = _route(runoff, loss, all_reaches=True) * M3S_TO_ML_DAY
    return reach_flow[runoff.columns[-1]].rename("flow_ML_d"), reach_flow
