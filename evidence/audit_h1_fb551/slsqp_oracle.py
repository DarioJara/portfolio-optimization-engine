import sys, numpy as np, cvxpy as cp
sys.path.insert(0, sys.argv[1])
from scipy.optimize import minimize
from portfolio_engine.models.enums import CostTreatment
from portfolio_engine.scenarios import MultiScenarioOptimizer
from tests.fixtures.block4 import four_asset_problem
from tests.unit.scenarios.test_multi_scenario import CONFIG, LAMBDA, _scenarios, _arrays, _utility
problem = four_asset_problem(CONFIG, max_weight=0.6); scenarios=_scenarios(problem); data=_arrays(scenarios)
sol = MultiScenarioOptimizer(CONFIG).solve_worst_case(problem, scenarios, CostTreatment.GROSS, LAMBDA).single_solution
w_eng=np.array(sol.weights); u_eng=min(_utility(w_eng,mu,s) for _,_,mu,s in data)
print("engine utility",u_eng)
# referencia independiente: busqueda exhaustiva fina con SLSQP multi-arranque a ftol 1e-15 exito (best) y CVXPY si es posible
def run(ftol, x0):
    return minimize(lambda x:-x[4], x0, bounds=[(0,0.6)]*4+[(None,None)],
        constraints=[{"type":"eq","fun":lambda x: float(np.sum(x[:4])-1)}]+[{"type":"ineq","fun":lambda x,m=mu,c=s:_utility(x[:4],m,c)-x[4]} for _,_,mu,s in data],
        method="SLSQP", options={"ftol":ftol,"maxiter":2000})
rng=np.random.default_rng(0)
base=np.concatenate([np.full(4,0.25),[-1.0]])
for ftol in (1e-15,1e-13,1e-12,1e-10,1e-8):
    ok=0; dx=[]; dv=[]; viol=[]; its=[]
    for k in range(200):
        x0=base*(1+ (0 if k==0 else 1e-12*rng.standard_normal(5)))
        r=run(ftol,x0); its.append(r.nit)
        if r.success:
            ok+=1; dx.append(np.max(np.abs(r.x[:4]-w_eng))); dv.append(abs(-r.fun-u_eng))
            viol.append(max(0,-min(r.x[:4].min(),0), abs(r.x[:4].sum()-1), max(0, r.x[4]-min(_utility(r.x[:4],m,s) for _,_,m,s in data))))
    print(f"ftol={ftol:g}: success {ok}/200 max|x-x_eng| {max(dx):.2e} max|f-f_eng| {max(dv):.2e} max viol {max(viol):.1e} median nit {int(np.median(its))}")
# asserts del test: atol 1e-4 sobre pesos, abs 1e-7 en valor
