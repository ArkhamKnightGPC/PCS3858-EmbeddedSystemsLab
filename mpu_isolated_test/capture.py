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
parser.add_argument('--label', default='mpu_full_assembly_software_isolation')
parser.add_argument('--commands', type=Path)
args = parser.parse_args()
if not 1 <= args.duration <= 600:
    parser.error('duration must be between 1 and 600 seconds')
root = Path(__file__).resolve().parent / 'logs' / datetime.now(ZoneInfo('America/Belem')).strftime('%Y%m%dT%H%M%S_%f')
root.mkdir(parents=True)
def now(): return datetime.now(ZoneInfo('America/Belem')).isoformat()
meta = dict(label=args.label, started_at=now(), requested_duration_s=args.duration, port=args.port,
            baudrate=230400, note='Host timestamps mark receipt. Orientation and motion are not inferred as ground truth.')
(root/'metadata.json').write_text(json.dumps(meta, indent=2)+'\n')
port = serial.Serial(port=None, baudrate=230400, timeout=0.05, exclusive=True)
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
control_path = args.commands or root/'commands.jsonl'
control_path.touch(exist_ok=True)
control = control_path.open('r')
control.seek(0, 2)  # Never replay commands from an earlier capture.
control_pending = ''
print(json.dumps(dict(type='capture_start', time=now(), directory=str(root), commands=str(control_path))), flush=True)
started = time.monotonic()
last_report = started
try:
    with (root/'serial.bin').open('wb') as raw, (root/'events.jsonl').open('w') as events:
        port.open()
        while not stop_signal and time.monotonic()-started < args.duration and total < 8*1024*1024:
            control_pending += control.read()
            if len(control_pending) > 16384:
                raise ValueError('Command queue exceeded bounded input size')
            while '\n' in control_pending:
                command_line, control_pending = control_pending.split('\n', 1)
                if not command_line.strip(): continue
                entry = dict(received_at=now())
                try:
                    command_data = json.loads(command_line)
                    command_text = command_data.get('command')
                    if command_text is not None:
                        if not isinstance(command_text, str) or not command_text.isascii() or len(command_text)>30 or any(c in command_text for c in '\r\n'):
                            raise ValueError('Invalid command text')
                        port.write((command_text+'\n').encode('ascii'))
                        port.flush()
                    entry['host_control'] = command_data
                except (ValueError, AttributeError) as error:
                    entry['control_error'] = str(error)
                events.write(json.dumps(entry)+'\n'); events.flush()
                print(json.dumps(entry), flush=True)
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
                        if not isinstance(data, dict): raise json.JSONDecodeError('Expected object', text, 0)
                        entry['device'] = data
                        kind = data.get('type', 'unknown')
                        counts[kind] += 1
                        if kind == 'status': last_status = data
                        if kind in ('boot', 'config', 'identity', 'command_result', 'config_mismatch', 'range_changed'):
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
    control.close()
    raw_path = root/'serial.bin'
    raw_data = raw_path.read_bytes() if raw_path.exists() else b''
    (root/'serial.txt').write_text(raw_data.decode('utf-8', errors='replace'))
    meta.update(ended_at=now(), duration_s=time.monotonic()-started, bytes=len(raw_data),
                sha256=hashlib.sha256(raw_data).hexdigest(), counts=dict(counts), error=failure,
                trailing_partial_bytes=len(pending), stop_signal=stop_signal)
    (root/'metadata.json').write_text(json.dumps(meta, indent=2)+'\n')
    print(json.dumps(dict(type='capture_end', directory=str(root), **meta)), flush=True)
if failure: raise SystemExit(failure)
