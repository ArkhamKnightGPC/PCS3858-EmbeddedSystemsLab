"""Bounded capture with one serial open; preserve bytes and host receive times."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import signal
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import serial

parser = argparse.ArgumentParser()
parser.add_argument('--duration', type=int, default=120)
parser.add_argument('--port', default='/dev/ttyUSB0')
parser.add_argument('--label', default='full_assembly_software_isolation')
args = parser.parse_args()
if not 1 <= args.duration <= 600:
    parser.error('duration must be between 1 and 600 seconds')
root = Path(__file__).resolve().parent / 'logs' / datetime.now(ZoneInfo('America/Belem')).strftime('%Y%m%dT%H%M%S_%f')
root.mkdir(parents=True)
def now(): return datetime.now(ZoneInfo('America/Belem')).isoformat()
meta = dict(label=args.label, started_at=now(), requested_duration_s=args.duration, port=args.port,
            baudrate=115200, note='Host timestamps mark receipt, not acquisition. Finger placement is not inferred as ground truth.')
(root/'metadata.json').write_text(json.dumps(meta, indent=2)+'\n')
port = serial.Serial(port=None, baudrate=115200, timeout=0.25, exclusive=True)
port.dtr = False
port.rts = False
port.port = args.port
counts = Counter()
pending = b''
total = 0
last_status = None
failure = None
stop_signal = None
def request_stop(signum, frame):
    global stop_signal
    stop_signal = signum
signal.signal(signal.SIGTERM, request_stop)
signal.signal(signal.SIGINT, request_stop)
print(json.dumps(dict(type='capture_start', time=now(), directory=str(root))), flush=True)
started = time.monotonic()
last_report = started
try:
    with (root/'serial.bin').open('wb') as raw, (root/'events.jsonl').open('w') as events:
        port.open()
        while not stop_signal and time.monotonic()-started < args.duration and total < 8*1024*1024:
            chunk = port.read(min(max(port.in_waiting, 1), 8192))
            if chunk:
                raw.write(chunk); raw.flush(); total += len(chunk)
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    text = line.decode('utf-8', errors='replace').strip()
                    if not text: continue
                    entry = dict(received_at=now())
                    try:
                        data = json.loads(text)
                        entry['device'] = data
                        kind = data.get('type', 'unknown')
                        counts[kind] += 1
                        if kind == 'status': last_status = data
                        if kind in ('boot', 'config', 'identity'):
                            print(json.dumps(entry), flush=True)
                    except json.JSONDecodeError:
                        entry['text'] = text
                        counts['non_json'] += 1
                    events.write(json.dumps(entry)+'\n')
                events.flush()
            if time.monotonic()-last_report >= 10:
                print(json.dumps(dict(type='capture_progress', time=now(), counts=dict(counts), status=last_status)), flush=True)
                last_report = time.monotonic()
except Exception as error:
    failure = f'{type(error).__name__}: {error}'
finally:
    if port.is_open: port.close()
    raw_path = root/'serial.bin'
    raw_data = raw_path.read_bytes() if raw_path.exists() else b''
    (root/'serial.txt').write_text(raw_data.decode('utf-8', errors='replace'))
    meta.update(ended_at=now(), duration_s=time.monotonic()-started, bytes=len(raw_data),
                sha256=hashlib.sha256(raw_data).hexdigest(), counts=dict(counts), error=failure,
                trailing_partial_bytes=len(pending), stop_signal=stop_signal)
    (root/'metadata.json').write_text(json.dumps(meta, indent=2)+'\n')
    print(json.dumps(dict(type='capture_end', directory=str(root), **meta)), flush=True)
if failure: raise SystemExit(failure)
