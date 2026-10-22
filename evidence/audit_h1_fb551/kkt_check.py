import sys, numpy as np, clarabel
sys.argv=[sys.argv[0]]
exec(open(r"C:/Users/dario/AppData/Local/Temp/claude/C--Trabajo-3--Proyectos-3--Proyectos-39--Optimizador-Carteras-Inversion-2--Codigo-3--Optimizador/92a679b9-9774-4a17-b2cf-ad996f3b5e4f/scratchpad/retry_stress.py").read().split("rng = np.random")[0])
rng=np.random.default_rng(5)
tol=1e-9
def kkt(P,q,A,b,r):
    x,s,z=np.array(r.x),np.array(r.s),np.array(r.z)
    pri=np.linalg.norm(A@x+s-b,np.inf)/max(1,np.linalg.norm(b,np.inf)+np.linalg.norm(s,np.inf)) if False else np.linalg.norm(A@x+s-b,np.inf)/max(1.0,max(np.linalg.norm(b,np.inf),np.linalg.norm(A@x,np.inf)))
    dua=np.linalg.norm(P@x+A.T@z+q,np.inf)/max(1.0,max(np.linalg.norm(q,np.inf),np.linalg.norm(A.T@z,np.inf)))
    pobj=0.5*x@(P@x)+q@x; dobj=-0.5*x@(P@x)-b@z
    gap=abs(pobj-dobj); rel=gap/max(1,min(abs(pobj),abs(dobj)))
    return pri,dua,gap,rel
res={True:[],False:[]}
for kind in ("scaled",):
  for i in range(150):
    n=int(rng.integers(5,40)); P,q,A,b,cones=build(rng,n,kind)
    for eq in (True,False):
        r=clarabel.DefaultSolver(P,q,A,b,cones,settings(tol,800,eq)).solve()
        if str(r.status)=="Solved": res[eq].append(kkt(P,q,A,b,r))
for eq in res:
    a=np.array(res[eq]); print("equilibrate",eq,"n Solved",len(a),"max pri/dua/gap_abs/gap_rel",a.max(axis=0))
