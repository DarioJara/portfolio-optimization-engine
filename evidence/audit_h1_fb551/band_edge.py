import sys, numpy as np, random
sys.path.insert(0, sys.argv[1])
from portfolio_engine.candidates.expansion import rank_nodes
from dataclasses import dataclass
@dataclass(frozen=True)
class E: satisfies_constraints: bool=True
@dataclass(frozen=True)
class N:
    gain: float; composition_hash: str; estimate: E=E()
    def ranking_key(self): return (0, -self.gain, self.composition_hash)
tau=1e-9
def order(gs, hs):
    return tuple(n.composition_hash for n in rank_nodes([N(g,h) for g,h in zip(gs,hs)], tau))
# A: dos nodos a distancia justo tau: hash(b) < hash(a), a es mejor por ~tau
a=0.05
b_in = a - tau            # distancia = tau (puede caer a cada lado por redondeo)
res=set()
for k in range(-3,4):
    b=b_in
    for _ in range(abs(k)): b=float(np.nextafter(b, np.inf if k>0 else -np.inf))
    res.add(order([a,b],["z","a"]))
    print("shift %+d ulp: dist-tau=%.3e -> %s"%(k, (a-b)-tau, order([a,b],["z","a"])))
print("orders observed at the edge:", res)
# B: cadena: g1 > g2 > g3 con pasos de 0.6 tau: anclado en g1 -> g3 fuera aunque este a 0.6tau de g2
g=[0.05, 0.05-0.6*tau, 0.05-1.2*tau]
print("chain 0.6tau steps:", order(g, ["c","b","a"]), "(a,b,c = hashes; anchor semantics: g3 not tied with g1)")
# C: invariancia con ruido de 1 ulp lejos del borde (mejoras separadas 0.5 tau)
rng=random.Random(0); flips=0; n=20000
for _ in range(n):
    gs=[0.05, 0.05-0.5*tau, 0.05-3*tau]
    gs=[float(np.nextafter(x, np.inf if rng.random()<.5 else -np.inf)) for x in gs]
    if order(gs,["c","b","a"])!=order([0.05,0.05-0.5*tau,0.05-3*tau],["c","b","a"]): flips+=1
print("flips away from the edge:", flips, "of", n)
# D: frecuencia del borde para gaps ~ U(0, 2tau): P(flip bajo +-1ulp)
flips=0
for _ in range(200000):
    d=rng.uniform(0,2*tau); gs=[0.05,0.05-d]
    base=order(gs,["z","a"])
    gp=[float(np.nextafter(x, np.inf if rng.random()<.5 else -np.inf)) for x in gs]
    if order(gp,["z","a"])!=base: flips+=1
print("random gap in U(0,2tau): fraction of 1-ulp flips = %.2e (expected ~ulp/2tau = %.2e)"%(flips/200000, 7e-18*2/(2*tau)))
