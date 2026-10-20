"""Local credential injection; no user/provider-specific paths are bundled."""
import json
import os
import sys
from project_registry import SERVICE_ROOT


def secret_values():
    path=SERVICE_ROOT/'configs/provider-keys.json'
    values=list(json.loads(path.read_text()).values()) if path.exists() else []
    root=SERVICE_ROOT/'configs/root.key'
    if root.exists():values.append(root.read_text().strip())
    return [v for v in values if isinstance(v,str) and len(v)>=8]


def runtime_environment():
    values=json.loads((SERVICE_ROOT/'configs/provider-keys.json').read_text())
    env={**os.environ,**values}
    env['OVK_ROOT_KEY']=(SERVICE_ROOT/'configs/root.key').read_text().strip()
    env['OPENVIKING_CONFIG_FILE']=str(SERVICE_ROOT/'configs/ov.conf')
    env['LITELLM_LOCAL_MODEL_COST_MAP']='True'
    env['TIKTOKEN_CACHE_DIR']=str(SERVICE_ROOT/'cache/tiktoken')
    return env


if __name__=='__main__':
    binary=SERVICE_ROOT/'venv/bin/openviking-server'
    action=sys.argv[1]
    service=json.loads((SERVICE_ROOT/'configs/service.json').read_text())
    if action=='serve':args=[str(binary),'--config',str(SERVICE_ROOT/'configs/ov.conf'),'--host',service['host'],'--port',str(service['port'])]
    elif action=='doctor':args=[str(binary),'doctor','--config',str(SERVICE_ROOT/'configs/ov.conf')]
    else:raise SystemExit('Use serve or doctor.')
    os.execve(str(binary),args,runtime_environment())
