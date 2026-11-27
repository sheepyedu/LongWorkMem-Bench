"""Independent business ledger and stage-local scoring for the C1 settlement series."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
import tempfile

from . import settlement
from .grade_evidence import Probes, content
from .runstate import freeze


def ledger(inp, plan):
    alias={}
    if (inp/"aliases.csv").exists():
        with (inp/"aliases.csv").open() as source:
            for row in csv.DictReader(source):
                for day in range(int(row['start']),int(row['end'])+1):
                    alias[row['tenant'],row['raw'],day]=row['canon']
    def account(r):
        return r['tenant'],alias.get((r['tenant'],r['ticket'],r['day']),r['ticket'])
    rows={}
    for file in (inp/'packets').glob('*.jsonl'):
        for line in file.read_text().splitlines():
            r=json.loads(line)
            if r['seq']<=plan['lanes'][r['lane']] and r['day']<=plan['day']:
                rows[r['eid']]=r
    audit={}; groups=defaultdict(list); appeals=defaultdict(list); schedule=[]
    for r in rows.values():
        k=r['kind']
        if k=='leg':groups[r['tenant'],r['ref']].append(r)
        elif k=='recall':appeals[r['tenant'],r['ref']].append(r)
        else:schedule.append((r['day'],r['order'],[r]))
    auth=None
    if (inp/'handover.txt').exists():
        auth=(inp/'handover.txt').read_text().split('由 ')[1].split(' 单独')[0]
    for key in groups.keys()|appeals.keys():
        legs=groups[key]; valid=(len(legs)==2 and legs[0]['units']!=0 and sum(r['units'] for r in legs)==0 and account(legs[0])!=account(legs[1]))
        void=False
        day=max((r['day'] for r in legs),default=0); order=max((r['order'] for r in legs),default=0)
        for r in sorted(appeals[key],key=lambda x:(x['day'],x['order'])):
            eligible=valid and r.get('signer')==auth and r['day']>=day and r['order']>order
            audit[r['eid']]=('duplicate' if void else 'posted') if eligible else 'denied'
            void |= eligible
        if valid and not void: schedule.append((day,order,legs))
        else:
            for r in legs:audit[r['eid']]='void' if void else ('pending' if len(legs)==1 else 'invalid')
    balance={}; inventory=defaultdict(list); usage=defaultdict(lambda:[0,0]); travel=defaultdict(lambda:[0,0])
    financial=(inp/'finance.txt').is_file()
    for day,order,items in sorted(schedule,key=lambda e:e[:2]):
        changes=[(account(r),-r['units'] if r['kind']=='use' else r['units']) for r in items]
        ok=all(balance.get(k,0)+delta>=0 for k,delta in changes)
        if ok and financial:
            if len(items)==1 and items[0]['kind']=='credit':
                r=items[0]; n=r['units']
                inventory[account(r)].extend((r['day'],r['order'],i,r['eid'],
                    (i+1)*r['cents']//n-i*r['cents']//n) for i in range(n))
            else:
                index=next(i for i,c in enumerate(changes) if c[1]<0)
                k,neg=changes[index]; tokens=sorted(inventory[k]); selected=tokens[:-neg]; inventory[k]=tokens[-neg:]
                target=travel if len(items)==2 else usage
                for _,_,_,origin,cents in selected:
                    part=target[items[index]['eid'],origin]; part[0]+=1; part[1]+=cents
                if len(items)==2: inventory[changes[1-index][0]].extend(selected)
        for r,(k,delta) in zip(items,changes):
            audit[r['eid']]='posted' if ok else 'denied'
            if ok:balance[k]=balance.get(k,0)+delta
    totals=Counter()
    for (t,_),b in balance.items():totals[t]+=b
    result=dict(accounts=[[*k,b] for k,b in sorted(balance.items())],
                audit=[[k,d] for k,d in sorted(audit.items())],totals=[list(x) for x in sorted(totals.items())])
    if financial:
        lots=defaultdict(lambda:[0,0])
        for key,tokens in inventory.items():
            for _,_,_,origin,cents in tokens:
                part=lots[*key,origin];part[0]+=1;part[1]+=cents
        for name,store in [('lots',lots),('usage',usage),('travel',travel)]:
            if name!='travel' or (inp/'transfer.txt').exists():
                result[name]=[[*key,*value] for key,value in sorted(store.items())]
    return result


def load_output(work,name):
    try:return json.loads(content(work,'out/'+name+'.json'))
    except (ValueError,OSError,RecursionError):return None


def matches(got,expected,field=None):
    if field is not None:
        if not isinstance(got,dict):return False
        got=got.get(field); expected=expected[field]
    if not isinstance(got,list):return False
    def canonical(rows):
        return Counter(json.dumps(row,ensure_ascii=False,separators=(',',':')) for row in rows)
    return canonical(got)==canonical(expected)


def grade_snapshot(run, backend, snapshot_dir):
    run=Path(run).resolve()
    m=json.loads((run/'manifest.json').read_text())
    advanced=m["level"]==2
    details={}; checks={}; missing=[]; probes=Probes(backend,run)
    def record(label,max_points,ok):
        checks[label]=[max_points if ok else 0,max_points]
    with tempfile.TemporaryDirectory(dir=run.parent) as tmp:
        base=Path(tmp)/'oracle'; (base/'input').mkdir(parents=True)
        for turn,name,weights in [(1,'intake',(3,3,2)),(2,'routing',(4,4,2)),(3,'cutover',(6,7,3)),(4,'incident',()),(5,'corrections',(8,12,4)),(6,'close',(3,3,2))]:
            settlement.release(base,turn,m['variant'],m['seed'],m['level'])
            snap=run/snapshot_dir/str(turn)
            if not snap.exists():missing.append(turn)
            got=load_output(snap,name)
            inp=base/'input'
            if turn==4:
                ranks={}
                for line in (inp/'incident.jsonl').read_text().splitlines():
                    r=json.loads(line); k=(r['site'],r['job']);rank=(r['attempt'],r['stamp'])
                    if k not in ranks or ranks[k][0]<rank:ranks[k]=(rank,r['result'])
                expected=[[*k,v[0][0]] for k,v in ranks.items() if v[1]=='failed']
                record('incident.latest',6,matches(got,expected));continue
            exp=ledger(inp,json.loads((inp/'jobs'/f'{name}.json').read_text()))
            if advanced:
                for field in ('lots','usage','travel'):
                    if field in exp: details[name+'.'+field]=matches(got,exp,field)
            for f,w in zip(('accounts','audit','totals'),weights):record(name+'.'+f,w,matches(got,exp,f))
        archives=sorted((inp/'jobs').glob('archive-*.json'))
        outcomes=[]
        for p in archives:
            expected=ledger(inp,json.loads(p.read_text())); got=load_output(snap,p.stem)
            outcomes.append(all(matches(got,expected,f) for f in ('accounts','audit','totals')))
            if advanced: details[p.stem]=all(matches(got,expected,f) for f in ('lots','usage','travel'))
        checks['archive.cuts']=[8*sum(outcomes)/len(outcomes),8]
        # Each deadline's signed file must survive the later backfill unchanged in meaning.
        closed=all(load_output(snap,n) is not None and load_output(snap,n)==load_output(run/snapshot_dir/str(t),n)
                   for t,n in enumerate(settlement.NAMES[:3],1))
        record('archive.preserved',4,closed)
        # A fresh caller supplies an arbitrary input directory and output path. New
        # arrivals and new identifiers distinguish executable work from canned exports.
        for trial in range(4):
            with probes.workspace(snap) as work:
                hidden=Path(tmp)/f'hold-{trial}'; (hidden/'input').mkdir(parents=True)
                for t in range(1,7):settlement.release(hidden,t,m['variant'],m['seed']+9023+trial,m['level'])
                # The contract is the same one issued in this session; vary business data only.
                old=(inp/'handover.txt').read_text(); new=(hidden/'input/handover.txt').read_text()
                orig=old.split('由 ')[1].split(' 单独')[0]; issued=new.split('由 ')[1].split(' 单独')[0]
                (hidden/'input/handover.txt').write_text(old)
                for packet in (hidden/'input/packets').glob('corrections-*.jsonl'):
                    rows=[json.loads(line) for line in packet.read_text().splitlines()]
                    for row in rows:
                        if 'signer' in row: row['signer']=orig if row['signer']==issued else 'visitor'
                    packet.write_text(''.join(json.dumps(row)+'\n' for row in rows))
                import shutil
                with tempfile.TemporaryDirectory(dir=work/'scratch') as unique:
                    remote=Path(unique)/'desk-input'
                    shutil.copytree(hidden/'input',remote)
                    relative=remote.relative_to(work)
                    if m.get('dispatch_window'):
                        (remote/'handover.txt').unlink()
                    # Compute expectations from the host's signed copy.
                    expected_input=hidden/'input'
                    plan=json.loads((remote/'jobs'/('close.json' if trial%2==0 else 'archive-2.json')).read_text())
                    (remote/'plan.json').write_text(json.dumps(plan))
                    expected=ledger(expected_input,plan)
                    dest=probes.output_path(work)
                    err=probes.command(work,f'python3 project/settle.py {relative} {relative}/plan.json {dest}')
                    try: got=json.loads(content(work,dest))
                    except (ValueError,OSError,RecursionError): got=None
                    record(f'rerun.{trial}',4,not err and all(matches(got,expected,f) for f in expected))
    if advanced:
        checks={name:[v*.6,w*.6] for name,(v,w) in checks.items()}
        checks.update({'lineage.'+name:[40*int(ok)/len(details),40/len(details)] for name,ok in details.items()})
    total=sum(x[0] for x in checks.values())
    valid=not probes.infrastructure and ((m.get('status')=='complete' and not missing) or m.get('status')=='budget_exhausted')
    return dict(total=round(total,2) if valid else None,observed_points=round(total,2),max=round(sum(x[1] for x in checks.values())),checks=checks,valid=valid,missing=missing,infrastructure=probes.infrastructure)


def grade(run, backend='docker'):
    latest = grade_snapshot(run, backend, 'snapshots')
    manifest = json.loads((Path(run)/'manifest.json').read_text())
    if not manifest.get('dispatch_window'):
        return latest
    dispatch = grade_snapshot(run, backend, 'dispatch')
    valid = latest['valid'] and dispatch['valid']
    return dict(total=round((2 * dispatch['total'] + latest['total']) / 3, 2) if valid else None,
                max=100, valid=valid, dispatch=dispatch, repaired=latest, version='dispatch-v1')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--backend',default='docker');a=p.parse_args()
    print(json.dumps(grade(a.run,a.backend),ensure_ascii=False,indent=2))
