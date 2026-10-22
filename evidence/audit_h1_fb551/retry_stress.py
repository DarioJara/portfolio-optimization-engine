"""Estres directo de Clarabel: reintento con equilibrado (base) vs sin equilibrado (PR) tras un primer intento no resuelto."""
import collections
import json
import sys

import clarabel
import numpy as np
from scipy import sparse

RANK = {"Solved": 0, "AlmostSolved": 1}


def rank(s):
    return RANK.get(s, 2)


def build(rng, n, degenerate):
    scale = 10 ** rng.uniform(-3, 3, n) if degenerate == "scaled" else np.ones(n)
    F = rng.standard_normal((n, n)) * 0.1
    if degenerate == "lowrank":
        F = F[:, : max(2, n // 4)]
    L = (F * scale[:, None]) if degenerate != "lowrank" else F
    mu = rng.standard_normal(n) * 0.05 * (scale if degenerate == "scaled" else 1)
    lam = 0.5
    ub = np.full(n, 0.4 if degenerate != "scaled" else 1.0)
    m = L.shape[1]
    nv = n + 1
    q = np.concatenate([-mu, [lam]])
    P = sparse.csc_matrix((nv, nv))
    # filas: sum w = 1 (Zero); w>=0, w<=ub (Nonneg); SOC (t, L'w)
    A_eq = sparse.csc_matrix(np.concatenate([np.ones(n), [0.0]])[None, :])
    A_lo = sparse.hstack([-sparse.identity(n), sparse.csc_matrix((n, 1))])
    A_hi = sparse.hstack([sparse.identity(n), sparse.csc_matrix((n, 1))])
    A_soc = sparse.vstack([sparse.csc_matrix(np.concatenate([np.zeros(n), [-1.0]])[None, :]),
                           sparse.hstack([-sparse.csc_matrix(L.T), sparse.csc_matrix((m, 1))])])
    A = sparse.vstack([A_eq, A_lo, A_hi, A_soc]).tocsc()
    b = np.concatenate([[1.0], np.zeros(n), ub, np.zeros(1 + m)])
    cones = [clarabel.ZeroConeT(1), clarabel.NonnegativeConeT(2 * n), clarabel.SecondOrderConeT(1 + m)]
    return P, q, A, b, cones


def settings(tol, it, eq):
    s = clarabel.DefaultSettings()
    s.verbose = False
    s.max_iter = it
    for k in ("tol_gap_abs", "tol_gap_rel", "tol_feas", "tol_infeas_abs", "tol_infeas_rel"):
        setattr(s, k, tol)
    s.equilibrate_enable = eq
    return s


def run(P, q, A, b, cones, tol, it, eq):
    r = clarabel.DefaultSolver(P, q, A, b, cones, settings(tol, it, eq)).solve()
    return str(r.status), np.array(r.x), float(r.obj_val), int(r.iterations)


rng = np.random.default_rng(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
out = collections.Counter()
worse, better, changed = [], [], []
for kind in ("plain", "scaled", "lowrank"):
    for tol in (1e-9, 1e-11, 1e-12):
        for i in range(N):
            n = int(rng.integers(5, 40))
            P, q, A, b, cones = build(rng, n, kind)
            st1, x1, o1, _ = run(P, q, A, b, cones, tol, 200, True)
            if st1 == "Solved":
                out[(kind, tol, "first_solved")] += 1
                continue
            out[(kind, tol, "first_not_solved:" + st1)] += 1
            sb, xb, ob, _ = run(P, q, A, b, cones, tol, 800, True)   # base: mismo equilibrado
            sp, xp, op, _ = run(P, q, A, b, cones, tol, 800, False)  # PR: sin equilibrado
            out[(kind, tol, f"retry base={sb} pr={sp}")] += 1
            if rank(sp) > rank(sb):
                worse.append((kind, tol, i, st1, sb, sp))
            if rank(sp) < rank(sb):
                better.append((kind, tol, i, st1, sb, sp))
            if sb in ("Solved", "AlmostSolved") and sp in ("Solved", "AlmostSolved"):
                d = float(np.max(np.abs(xb[:-1] - xp[:-1])))
                if d > 1e-6:
                    changed.append((kind, tol, i, sb, sp, d, abs(ob - op)))
for k in sorted(out, key=str):
    print(k, out[k])
print("PR WORSE than base retry:", len(worse), worse[:10])
print("PR BETTER than base retry:", len(better))
print("both usable but x differs >1e-6:", len(changed), changed[:10])
