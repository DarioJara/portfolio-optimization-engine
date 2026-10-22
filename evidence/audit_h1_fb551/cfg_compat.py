import sys,tomllib,dataclasses,re
tree=sys.argv[1]; sys.path.insert(0,tree)
from portfolio_engine.config import config_hash
from portfolio_engine.config.loader import load_engine_config
p=tree+"/config/default_engine.toml"
cfg=load_engine_config(p); print("hash",config_hash(cfg)[:16])
txt=open(p,encoding="utf-8").read()
# sin la clave (TOML antiguo)
old=re.sub(r"^retry_equilibrate\s*=.*$","",txt,flags=re.M)
import tempfile,os
f=tempfile.NamedTemporaryFile("w",suffix=".toml",delete=False,encoding="utf-8"); f.write(old); f.close()
try: load_engine_config(f.name); print("OLD TOML: loaded OK (should not)")
except Exception as e: print("OLD TOML ->",type(e).__name__,str(e)[:140])
# hash depende del valor
c2=dataclasses.replace(cfg,conic=dataclasses.replace(cfg.conic,retry_equilibrate=True))
print("hash changes with value:", config_hash(c2)!=config_hash(cfg))
# retry_equilibrate == equilibrate => reintento identico (config peligrosa): se advierte?
c3=dataclasses.replace(cfg,conic=dataclasses.replace(cfg.conic,retry_equilibrate=cfg.conic.equilibrate))
print("config with retry==primary accepted silently:", config_hash(c3) is not None)
# tipo no booleano
try: load_engine_config(open(p,encoding="utf-8").read() and re.sub(r"retry_equilibrate = false","retry_equilibrate = 0",txt) and None) 
except Exception: pass
