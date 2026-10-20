"""Minimal text-only access checks; provider credentials are never printed."""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request,build_opener
from manage import NoRedirect,atomic
from project_registry import SERVICE_ROOT
from provider_runtime import runtime_environment


def probe():
    config=json.loads((SERVICE_ROOT/'configs/ov.conf').read_text());env=runtime_environment();report={}
    for name,spec in [('embedding',config['embedding']['dense']),('vlm',config['vlm'])]:
        provider=spec['provider'];base=spec['api_base'].rstrip('/');headers={'Content-Type':'application/json'}
        key=spec.get('api_key','')
        if key.startswith('${') and key.endswith('}'):key=env[key[2:-1]]
        if key:headers['Authorization']='Bearer '+key
        if provider in {'openai','volcengine'}:
            suffix='/embeddings' if name=='embedding' else '/chat/completions'
            body={'model':spec['model'],'input':['connectivity probe'],'encoding_format':'float'} if name=='embedding' else {'model':spec['model'],'messages':[{'role':'user','content':'Reply OK.'}],'max_tokens':32}
        elif provider=='ollama':
            # api_base is the Ollama service origin for this adapter.
            base=base.removesuffix('/v1').removesuffix('/api')
            suffix='/api/embed' if name=='embedding' else '/api/chat'
            body={'model':spec['model'],'input':['connectivity probe']} if name=='embedding' else {'model':spec['model'],'messages':[{'role':'user','content':'Reply OK.'}],'stream':False,'options':{'num_predict':32}}
        else:raise ValueError('Minimal probe does not implement this provider; use the provider-specific official doctor flow.')
        try:
            with build_opener(NoRedirect).open(Request(base+suffix,data=json.dumps(body).encode(),headers=headers),timeout=45) as response:value=json.load(response)
        except HTTPError as exc:raise RuntimeError(name+' model probe returned HTTP '+str(exc.code)+'. Check model binding and permissions separately; no key was echoed.') from None
        if name=='embedding':
            vector=value['embeddings'][0] if provider=='ollama' else value['data'][0]['embedding']
            dimension=len(vector)
            if spec.get('dimension') and dimension!=spec['dimension']:raise ValueError('Embedding dimension differs from the configured index dimension; reconcile before importing.')
            report[name]={'accessible':True,'observed_dimension':dimension,'configured_dimension':spec.get('dimension')}
        else:
            assert value.get('message') is not None if provider=='ollama' else bool(value.get('choices'))
            report[name]={'accessible':True}
    report['passed']=True;atomic(SERVICE_ROOT/'evidence/model-probe.json',report);return report


if __name__=='__main__':
    try:print(json.dumps(probe(),ensure_ascii=False,indent=2))
    except Exception as exc:
        print(json.dumps({'passed':False,'error_type':type(exc).__name__,'message':str(exc) if isinstance(exc,(ValueError,RuntimeError)) else 'Model probe failed; check endpoints, model permissions and vector shape. No credential values were logged.'}))
        raise SystemExit(1)
