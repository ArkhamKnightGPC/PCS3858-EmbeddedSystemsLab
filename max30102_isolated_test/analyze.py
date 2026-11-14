"""Summarize one bounded capture without assigning finger labels automatically."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from statistics import median

parser = argparse.ArgumentParser()
parser.add_argument('capture', type=Path)
args = parser.parse_args()
source = args.capture / 'events.jsonl'
if source.stat().st_size > 32 * 1024 * 1024:
    raise SystemExit('Capture exceeds the bounded analysis size (32 MiB).')
entries = [json.loads(line) for line in source.read_text().splitlines() if line]
devices = [e['device'] for e in entries if isinstance(e.get('device'), dict)]
counts = Counter(d.get('type', 'unknown') for d in devices)
samples = [e for e in entries if e.get('device', {}).get('type') == 'sample']
errors = [e for e in entries if e.get('device', {}).get('type') == 'i2c_error']
configs = [e for e in entries if e.get('device', {}).get('type') == 'config']

def channel_stats(records, channel):
    values = [e['device'][channel] for e in records]
    return dict(min=min(values), max=max(values), median=median(values),
                zero_count=values.count(0), saturation_count=values.count(262143))

summary = dict(source=str(source.resolve()), sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
               event_counts=dict(counts), configurations=configs,
               i2c_errors=errors, sample_count=len(samples),
               limitations=['No timestamped ground truth for finger placement.',
                            'Device ms marks FIFO read time, not optical conversion.',
                            'gap indicates a reported overflow, not a proven lost-sample count.',
                            'Hardware remained connected to the full assembly.'])
if samples:
    first, last = samples[0], samples[-1]
    first_ms, last_ms = first['device']['ms'], last['device']['ms']
    summary.update(first_sample_at=first['received_at'], last_sample_at=last['received_at'],
                   sample_span_s=(last_ms-first_ms)/1000,
                   reported_gap_samples=sum(bool(e['device'].get('gap')) for e in samples),
                   red=channel_stats(samples, 'red'), ir=channel_stats(samples, 'ir'),
                   i2c_errors_after_first_sample=[e for e in errors if e['received_at'] > first['received_at']])
    segments = []
    current = []
    for e in samples:
        if current and (e['device']['seq'] <= current[-1]['device']['seq'] or
                        e['device']['ms'] < current[-1]['device']['ms']):
            segments.append(current)
            current = []
        current.append(e)
    if current: segments.append(current)
    summary['segments'] = []
    for segment in segments:
        start, end = segment[0]['device'], segment[-1]['device']
        elapsed = (end['ms'] - start['ms'])/1000
        summary['segments'].append(dict(samples=len(segment), span_s=elapsed,
            records_per_s=(len(segment)-1)/elapsed if elapsed > 0 else None,
            sequence_gaps=sum(max(0,b['device']['seq']-a['device']['seq']-1)
                              for a,b in zip(segment,segment[1:]))))
    windows = defaultdict(list)
    for e in samples:
        windows[(e['device']['ms']-first_ms)//10000].append(e)
    summary['ten_second_windows'] = [dict(offset_s=key*10, samples=len(rows),
        red=channel_stats(rows,'red'), ir=channel_stats(rows,'ir'),
        reported_gap_samples=sum(bool(e['device'].get('gap')) for e in rows))
        for key, rows in sorted(windows.items())]
out = args.capture / 'analysis.json'
out.write_text(json.dumps(summary, indent=2)+'\n')
if samples:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    t = [(e['device']['ms']-first_ms)/1000 for e in samples]
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for ax, key, title in zip(axes, ('red','ir'), ('Vermelho', 'Infravermelho')):
        ax.plot(t, [e['device'][key] for e in samples], color='black', linewidth=0.6)
        ax.set_ylabel(f'{title}\n(contagens)')
        ax.grid(True, color='0.85', linewidth=0.5)
    axes[1].axhline(50000, color='0.4', linestyle='--', linewidth=0.8,
                    label='Limiar de dedo do código original (50.000)')
    axes[1].legend(loc='upper right', fontsize=8)
    axes[1].set_xlabel('Tempo desde a primeira amostra recebida (s; relógio da ESP32)')
    fig.suptitle('MAX30102: resposta óptica bruta na montagem completa')
    fig.text(0.5, 0.015, 'Há indicações de overflow. Os intervalos com dedo não foram rotulados individualmente.',
             ha='center', fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(args.capture/'optical_response.png', dpi=160)
    plt.close(fig)
print(json.dumps({k:v for k,v in summary.items() if k not in ('configurations','i2c_errors')}, indent=2))
