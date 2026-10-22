import sys, json, dataclasses, numpy as np
tree, out = sys.argv[1], sys.argv[2]; NS=int(sys.argv[3]) if len(sys.argv)>3 else 40
sys.path.insert(0, tree)
from tests.fixtures.candidates import random_problem, search, with_candidates
from tests.fixtures.problems import base_config, make_problem
import portfolio_engine; assert tree.replace("\\","/") in portfolio_engine.__file__.replace("\\","/")
HELD=[0,1,2,3]
cfg = with_candidates(base_config(), beam_width=3, max_levels=2, swap_orders=(1,), local_search_starts=1,
    utility_risk_aversions=(1.0,4.0,16.0), max_candidates=12, shortlist_in=10, shortlist_out=4, max_evaluations=300)
def clone_problem(config):
    base = random_problem(8, HELD, 7, config)
    mu = base.risk_model.expected_returns.values; sigma = base.risk_model.covariance.matrix
    src=[0,1,2,3,4,5,6,7,4,5]
    return make_problem(mu[src], sigma[np.ix_(src,src)].copy(), [0.25]*4+[0.0]*6, config, universe_overrides={"MaxWeight":[0.6]*10})
def perturb(problem, seed, mode, eps):
    rng=np.random.default_rng(seed); risk=problem.risk_model
    S=risk.covariance.matrix; m=risk.expected_returns.values
    if mode=="ulp":
        n=S.shape[0]; sg=np.where(rng.random((n,n))<0.5,-np.inf,np.inf); sg=np.triu(sg)+np.triu(sg,1).T
        S2=np.nextafter(S,sg); m2=np.nextafter(m,np.where(rng.random(m.shape)<0.5,-np.inf,np.inf))
    else:
        noise=rng.standard_normal(S.shape); noise=(noise+noise.T)/2
        S2=S*(1+eps*noise); m2=m*(1+eps*rng.standard_normal(m.shape))
    return dataclasses.replace(problem, risk_model=dataclasses.replace(risk,
        covariance=dataclasses.replace(risk.covariance,matrix=S2),
        expected_returns=dataclasses.replace(risk.expected_returns,values=m2)))
def summarize(res):
    return {c.composition_id: float(c.estimated_utility_gain) if c.estimated_utility_gain is not None else None for c in res.compositions}
R={}
clone=clone_problem(cfg)
R["clone|ref"]=summarize(search(cfg,clone))
for mode,eps in (("ulp",0),("rel",1e-16),("rel",1e-14),("rel",1e-12)):
    sets=[]
    for s in range(NS):
        sets.append(summarize(search(cfg,perturb(clone,s,mode,eps))))
    R[f"clone|{mode}|{eps}"]=sets
# sin empates: problemas aleatorios, referencia (sin ruido)
for seed in range(1,13):
    for n in (10,14):
        c2 = with_candidates(base_config(), beam_width=4, max_levels=2, swap_orders=(1,2), local_search_starts=2,
             utility_risk_aversions=(1.0,4.0,16.0), max_candidates=15, shortlist_in=10, shortlist_out=4, max_evaluations=400)
        p=random_problem(n,HELD,seed,c2)
        R[f"rand|{n}|{seed}"]=summarize(search(c2,p))
json.dump(R,open(out,"w"))
print("ok")
