"""Exercise the real capture process against a PTY, never the physical ESP32."""
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import time

root=Path(__file__).resolve().parents[1]
master, slave=pty.openpty()
with tempfile.TemporaryDirectory() as tmp:
    commands=Path(tmp)/'commands.jsonl'
    commands.write_text('{"command":"old command"}\n')
    proc=subprocess.Popen([sys.executable,str(root/'capture.py'),'--duration','3',
        '--port',os.ttyname(slave),'--commands',str(commands),'--label','PTY_TEST_NOT_HARDWARE'],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        if not select.select([proc.stdout],[],[],5)[0]: raise AssertionError('Capture did not start')
        start=json.loads(proc.stdout.readline())
        time.sleep(0.2)
        os.write(master,b'{"type":"boot","test":"pty"}\n{"type":"sample","raw":[1,2,3]}\n')
        with commands.open('a') as stream: stream.write('{"command":"range 8"}\n')
        assert select.select([master],[],[],2)[0], 'Command not transmitted'
        sent=os.read(master,1024)
        assert sent==b'range 8\n', sent
        os.write(master,b'{"type":"command_result","accepted":true}\n')
        stdout,stderr=proc.communicate(timeout=6)
        assert proc.returncode==0,stderr
        saved=Path(start['directory'])
        meta=json.loads((saved/'metadata.json').read_text())
        rows=[json.loads(x) for x in (saved/'events.jsonl').read_text().splitlines()]
        assert meta['counts']['sample']==1 and meta['counts']['command_result']==1
        assert any(r.get('host_control',{}).get('command')=='range 8' for r in rows)
        assert meta['error'] is None
        print('PASS capture bytes, JSON, metadata, command delivery without reopening and no replay of old commands')
        print(saved)
    finally:
        if proc.poll() is None: proc.kill();proc.wait()
        os.close(master);os.close(slave)
