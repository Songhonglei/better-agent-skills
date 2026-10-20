"""Real STDIO checks; never claim a whole-task accuracy/token improvement."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from project_registry import SERVICE_ROOT,project_entry,load_registry


async def verify(code,query,contains):
    entry=project_entry(code);root=Path(entry['data_root']);workspace=entry['workspace_roots'][0]
    os.environ['OVK_PROJECT']=code
    import readonly_mcp as legacy
    from pilot_state import fresh_state,atomic_json
    manifest,receipt=fresh_state(root)
    report={'project_code':code,'passed':False,'checks':{},'scope':entry['scope'],
        'snapshot_id':receipt['snapshot_id'],'native_codex_tool_call_verified':False,
        'whole_task_accuracy_or_token_AB_run':False}
    params=StdioServerParameters(command=sys.executable,args=[str(SERVICE_ROOT/'scripts/unified_mcp.py')],env={**os.environ,'OVK_HOME':str(SERVICE_ROOT)})
    async with stdio_client(params) as (reader,writer):
      async with ClientSession(reader,writer) as session:
        await session.initialize();tools=(await session.list_tools()).tools
        assert {t.name for t in tools}=={'resolve_project','find','read','list','tree'}
        assert all(t.annotations.readOnlyHint for t in tools)
        args={'project_code':code,'workspace_path':workspace}
        async def call(name,arguments,budget):
            response=await session.call_tool(name,arguments)
            assert not response.isError,str(response.content)
            text=response.content[0].text;assert len(legacy.text_tokens(text))<=budget
            return json.loads(text)
        resolved=await call('resolve_project',{'workspace_path':workspace},1000);assert resolved['project_code']==code
        found=await call('find',{**args,'query':query},3000)
        assert found['requested_limit']==3 and 0<len(found['sources'])<=3
        chunks=[];read_uris=[]
        for hit in found['sources']:
            page=await call('read',{**args,'uri':hit['uri'],'expected_snapshot':hit['snapshot_id'],'token_budget':15000,'limit':1000},15000)
            chunks.append(page['content']);read_uris.append(hit['uri'])
        text='\n'.join(chunks);assert all(term in text for term in contains),'Expected evidence was not retrieved.'
        expanded=await call('find',{**args,'query':query,'limit':8},3000);assert len(expanded['sources'])<=8 and expanded['requested_limit']==8
        report['query']={'text':query,'read_uris':read_uris,'expected_facts_verified':bool(contains)}
        uri=found['sources'][0]['uri'];name=uri.rsplit('/',1)[-1]
        canonical=(Path(manifest['curated_directory'])/name).read_text()
        offset=char_offset=0;snapshot='';parts=[];pages=0
        while True:
            page=await call('read',{**args,'uri':uri,'offset':offset,'char_offset':char_offset,'expected_snapshot':snapshot,'token_budget':512},512)
            parts.append(page['content']);pages+=1
            if not page['has_more']:break
            next_position=(page['next_offset'],page['next_char_offset']);assert next_position>(offset,char_offset)
            offset,char_offset=next_position;snapshot=page['snapshot_id'];assert pages<200
        assert ''.join(parts)==canonical
        report['lossless_read_pages']=pages
        for name in ['list','tree']:
            offset=0;snapshot='';uris=[]
            while True:
                page=await call(name,{**args,'limit':3,'offset':offset,'expected_snapshot':snapshot},3000)
                uris.extend(item['uri'] for item in page['entries'])
                if not page['has_more']:break
                assert page['next_offset']>offset
                offset,snapshot=page['next_offset'],page['snapshot_id'];assert offset<10000
            assert len(uris)==len(set(uris))
            assert all(any(uri.endswith('/'+file) for uri in uris) for file in receipt['fingerprints']) if name=='tree' else len(uris)==len(receipt['fingerprints'])
        for bad in [{'uri':entry['scope']+'/../other'},{'uri':'viking://memories'},
                    {'uri':uri,'offset':1},{'uri':uri,'expected_snapshot':'0'*64}]:
            assert (await session.call_tool('read',{**args,**bad})).isError
        foreign_uri='viking://resources/projects/another-project/current/file.md'
        assert (await session.call_tool('read',{**args,'uri':foreign_uri})).isError
        report['checks'].update(readonly_tools=True,explicit_project_route=True,find_then_read=True,source_hashes=True,
            token_budgets=True,lossless_pages=True,invalid_snapshot_rejected=True,foreign_scope_rejected=True)
        for other,other_entry in load_registry().items():
            if other==code:continue
            assert (await session.call_tool('list',{'project_code':code,'workspace_path':other_entry['workspace_roots'][0]})).isError
            if other_entry['account']==entry['account']:
                report['shared_account_native_isolation']='not_provided; MCP routing is the boundary for this mode'
    report['native_account_denials']=[]
    config=json.loads((root/'configs/ovcli-reader.conf').read_text())
    for other,other_entry in load_registry().items():
        if other==code or other_entry['account']==entry['account']:continue
        path=Path(other_entry['data_root'])/'evidence/import-receipt.json'
        if not path.exists():continue
        other_receipt=json.loads(path.read_text());file=next(iter(other_receipt['fingerprints']))
        uri=other_entry['scope']+'/'+file[:-3]+'/'+file
        request=Request(config['url']+'/api/v1/content/read?'+urlencode({'uri':uri}),headers={'Authorization':'Bearer '+config['api_key']})
        try:urlopen(request,timeout=5).close()
        except HTTPError as exc:assert exc.code in {403,404}
        else:raise AssertionError('Native reader accessed another account.')
        report['native_account_denials'].append(code+' -> '+other)
    report['passed']=True
    atomic_json(root/'evidence/mcp-check.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('code');parser.add_argument('--query',required=True);parser.add_argument('--contains',action='append',default=[]);args=parser.parse_args()
    asyncio.run(verify(args.code,args.query,args.contains))
