"""GR4J daily rainfall-runoff model (Perrin, Michel & Andreassian 2003, J. Hydrol. 279)."""
import numpy as np

# Median parameter set from Perrin et al. (2003): x1 production store (mm), x2 exchange (mm/d),
# x3 routing store (mm), x4 unit hydrograph time base (days). Not calibrated to the Murrumbidgee.
DEFAULT_PARAMS = (350.0, 0.0, 90.0, 1.7)


def _unit_hydrographs(x4):
    n1, n2 = int(np.ceil(x4)), int(np.ceil(2 * x4))

    def sh1(t):
        return 0.0 if t <= 0 else (t / x4) ** 2.5 if t < x4 else 1.0

    def sh2(t):
        if t <= 0:
            return 0.0
        if t < x4:
            return 0.5 * (t / x4) ** 2.5
        return 1 - 0.5 * (2 - t / x4) ** 2.5 if t < 2 * x4 else 1.0

    uh1 = np.array([sh1(i) - sh1(i - 1) for i in range(1, n1 + 1)])
    uh2 = np.array([sh2(i) - sh2(i - 1) for i in range(1, n2 + 1)])
    return uh1, uh2


def gr4j(precip, pet, params=DEFAULT_PARAMS):
    """Runoff depth (mm/day) from daily precipitation and PET (mm/day) arrays."""
    x1, x2, x3, x4 = params
    uh1, uh2 = _unit_hydrographs(x4)
    q9_buf, q1_buf = np.zeros(len(uh1)), np.zeros(len(uh2))
    s, r = 0.3 * x1, 0.5 * x3
    out = np.empty(len(precip))
    for t, (p, e) in enumerate(zip(precip, pet)):
        pn, en = max(p - e, 0.0), max(e - p, 0.0)
        ps = es = 0.0
        if pn > 0:
            th = np.tanh(pn / x1)
            ps = x1 * (1 - (s / x1) ** 2) * th / (1 + (s / x1) * th)
        if en > 0:
            th = np.tanh(en / x1)
            es = s * (2 - s / x1) * th / (1 + (1 - s / x1) * th)
        s += ps - es
        perc = s * (1 - (1 + (s / (4 / 9 * x1)) ** 4) ** -0.25)
        s -= perc
        pr = pn - ps + perc

        q9_buf[:-1], q9_buf[-1] = q9_buf[1:], 0.0
        q1_buf[:-1], q1_buf[-1] = q1_buf[1:], 0.0
        q9_buf += 0.9 * pr * uh1
        q1_buf += 0.1 * pr * uh2

        f = x2 * (r / x3) ** 3.5
        r = max(r + q9_buf[0] + f, 0.0)
        qr = r * (1 - (1 + (r / x3) ** 4) ** -0.25)
        r -= qr
        out[t] = qr + max(q1_buf[0] + f, 0.0)
    return out
