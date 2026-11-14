"""Bounded summary of one physical or simulated capture, without imputing data."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from statistics import median

p=argparse.ArgumentParser()
p.add_argument('directory',type=Path)
a=p.parse_args()
source=a.directory/'events.jsonl'
if source.stat().st_size>32*1024*1024: raise SystemExit('Input exceeds 32 MiB limit')
entries=[json.loads(line) for line in source.read_text().splitlines() if line]
device=[e for e in entries if isinstance(e.get('device'),dict)]
counts=Counter(e['device'].get('type','unknown') for e in device)
groups=defaultdict(list)
for e in device:
    d=e['device']
    if d.get('type')=='sample': groups[d['epoch']].append(e)
summary=dict(source=str(source.resolve()),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    event_counts=dict(counts),
    identities=[e for e in device if e['device'].get('type')=='identity'],
    configurations=[e for e in device if e['device'].get('type')=='config'],
    commands=[e for e in entries if 'host_control' in e],
    errors_by_register=dict(Counter(str(e['device']['reg']) for e in device if e['device'].get('type')=='i2c_error')),
    error_timeline=[e for e in device if e['device'].get('type') in ('i2c_error','config_mismatch','range_changed')],
    epochs=[])
for epoch,rows in sorted(groups.items()):
    values=[e['device'] for e in rows]
    summary['epochs'].append(dict(epoch=epoch,samples=len(values),
        first_at=rows[0]['received_at'],last_at=rows[-1]['received_at'],
        range_g=values[0]['range_g'],axis_reads=values[0]['axis_reads'],
        raw_min=[min(d['raw'][i] for d in values) for i in range(3)],
        raw_max=[max(d['raw'][i] for d in values) for i in range(3)],
        raw_median=[median(d['raw'][i] for d in values) for i in range(3)],
        rails=[sum(d['raw'][i] in (-32768,32767) for d in values) for i in range(3)],
        norm_min=min(d['norm'] for d in values),norm_max=max(d['norm'] for d in values),
        norm_median=median(d['norm'] for d in values),stale=sum(not d['fresh'] for d in values)))
summary['conclusion_scope']='No valid acceleration samples' if not groups else 'Acceleration acquired; orientation labels require user observations'
(a.directory/'analysis.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='error_timeline'},indent=2))
