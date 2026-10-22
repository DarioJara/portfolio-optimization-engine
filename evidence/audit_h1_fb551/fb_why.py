import sys, numpy as np, collections
tree=sys.argv[1]; sys.path.insert(0,tree)
from tests.fixtures.candidates import random_problem, search, with_candidates
from tests.fixtures.problems import base_config
from portfolio_engine.candidates import expansion, beam_search, local_search
from portfolio_engine.candidates.expansion import SearchNode
HELD=[0,1,2,3]
stats=collections.defaultdict(lambda: collections.Counter())
cur=[None]
orig=expansion.rank_nodes
def spy(nodes, tau):
    nodes=list(nodes); out=orig(nodes,tau)
    ref=sorted(nodes,key=SearchNode.ranking_key)
    st=stats[cur[0]]; st["calls"]+=1
    if [n.composition_hash for n in out]!=[n.composition_hash for n in ref]:
        st["order_differs"]+=1
        # gaps de las mejoras que cambiaron de sitio
        g=sorted((n.gain for n in nodes),reverse=True)
        gaps=[a-b for a,b in zip(g,g[1:])]
        st["pairs_exact_equal_gain"]+=sum(1 for x in gaps if x==0)
        st["pairs_0<gap<=tau"]+=sum(1 for x in gaps if 0<x<=tau)
        st["pairs_ulp_scale(<1e-14)"]+=sum(1 for x in gaps if 0<x<1e-14)
    return out
for m in (beam_search, local_search): m.rank_nodes=spy
for seed in (1,2,4,5,6,7,9):
    for n in (10,14):
        c2 = with_candidates(base_config(), beam_width=4, max_levels=2, swap_orders=(1,2), local_search_starts=2,
             utility_risk_aversions=(1.0,4.0,16.0), max_candidates=15, shortlist_in=10, shortlist_out=4, max_evaluations=400)
        cur[0]=(n,seed); search(c2, random_problem(n,HELD,seed,c2))
for k,v in sorted(stats.items()): 
    if v["order_differs"]: print(k,dict(v))
print("cases with differing order:", sum(1 for v in stats.values() if v["order_differs"]), "of", len(stats))
