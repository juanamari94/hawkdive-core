"""Test process for the worker protocol. This is not an investigation agent."""

import json
import sys
from pathlib import Path
from time import sleep
from uuid import uuid4

request = json.loads(sys.stdin.readline())
mode = sys.argv[1]
identifiers = {name: str(uuid4()) for name in ('e1', 'o1', 'f1', 'out1')}


def emit(identifier, kind, content):
    output = {'id': identifiers[identifier], 'kind': kind, 'content': content}
    if mode == 'foreign':
        output['attempt_id'] = str(uuid4())
    print(json.dumps(output), flush=True)


if mode == 'failure':
    sys.exit(2)
if mode == 'missing':
    sys.exit(0)
if mode == 'bad_stream':
    print('invalid-json', flush=True)
    for _ in range(512):
        print('x' * 4096, flush=True)
    sys.exit(0)
emit('e1', 'EVIDENCE', {
    'source': 'test', 'query': 'memory_usage', 'starts_at': '2026-10-14T10:00:00Z',
    'ends_at': '2026-10-14T10:05:00Z', 'reasoning': 'Memory reached 512 MiB before the restart.',
    'source_url': 'https://example.test/metrics',
})
if mode == 'wait':
    release = Path(sys.argv[2])
    while not release.exists():
        sleep(0.02)
emit('o1', 'OBSERVATION', {'summary': 'Memory reached its limit.', 'evidence_ids': [identifiers['e1']]})
emit('f1', 'FINDING', {
    'summary': 'Memory exhaustion occurred.',
    'observation_ids': [str(uuid4())] if mode == 'invalid' else [identifiers['o1']],
})
emit('out1', 'OUTCOME', {'conclusion': 'Memory exhaustion caused a restart.', 'finding_ids': [identifiers['f1']]})
if mode == 'failure_after_outcome':
    sys.exit(3)
