"""Real kind kubeconfig-collision regression; fixtures are not real credentials.

The negative control uses no existing cluster; kind still edits matching entries.
The positive control runs the exact seven reader blocks against a real cluster.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess

SENTINEL_SERVER = 'https://unrelated-sentinel.invalid:6443'
SENTINEL = b'''# Deliberate name collision, unrelated server; preserve these exact bytes.
apiVersion: v1
kind: Config
preferences: {}
clusters:
- name: kind-intro
  cluster:
    server: https://unrelated-sentinel.invalid:6443
contexts:
- name: kind-intro
  context:
    cluster: kind-intro
    user: kind-intro
current-context: kind-intro
users:
- name: kind-intro
  user:
    token: not-a-real-credential
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def view(path):
    return json.loads(subprocess.check_output(
        ['kubectl', '--kubeconfig', str(path), 'config', 'view', '-o', 'json'], text=True))


def unchanged(path, phase):
    data = path.read_bytes()
    assert data == SENTINEL, f'Ambient kubeconfig changed during {phase}'
    print('AMBIENT_BYTE_IDENTICAL', phase, digest(data), flush=True)


def prepare(directory, checks):
    # Refuse to run the intentionally unsafe negative control around any cluster.
    assert not checks.run('kind', 'get', 'clusters').strip()
    assert not checks.run('docker', 'ps', '-aq', '--filter', 'label=io.x-k8s.kind.cluster=intro')
    negative = directory / 'negative-control-kubeconfig'
    negative.write_bytes(SENTINEL)
    env = dict(os.environ, KUBECONFIG=str(negative))
    # Original reader command, unchanged. Only this disposable fixture is targeted.
    result = subprocess.run(['kind', 'delete', 'cluster', '--name', 'intro'], env=env, check=True)
    assert result.returncode == 0
    data = negative.read_bytes()
    assert data != SENTINEL, 'Negative control did not reproduce ambient mutation'
    after = view(negative)
    for field in ('clusters', 'users', 'contexts'):
        assert not any(item['name'] == 'kind-intro' for item in (after.get(field) or []))
    assert not after.get('current-context')
    print('REAL_COLLISION_NEGATIVE_CONTROL', json.dumps({
        'cluster_present': False, 'original_command_mutates_ambient': True,
        'before_sha256': digest(SENTINEL), 'after_sha256': digest(data),
        'matching_cluster_user_context_removed': True, 'current_context_cleared': True,
    }), flush=True)
    ambient = directory / 'ambient-kubeconfig'
    ambient.write_bytes(SENTINEL)
    config = view(ambient)
    assert config['current-context'] == 'kind-intro'
    assert config['clusters'][0]['cluster']['server'] == SENTINEL_SERVER
    # acceptance.py sets KUBECONFIG at import time. Override it AFTER that import
    # so the reader shell really has the colliding ambient config, not the lab's.
    os.environ['KUBECONFIG'] = str(ambient)
    os.environ['INTRO_AMBIENT_KUBECONFIG'] = str(ambient)
    unchanged(ambient, 'before-reader-session')
    return ambient


def before_cleanup(root, k, checks):
    ambient = Path(os.environ['INTRO_AMBIENT_KUBECONFIG'])
    unchanged(ambient, 'before-cleanup')
    dedicated = root / '.intro-kubeconfig'
    config = view(dedicated)
    context = next(c for c in config['contexts'] if c['name'] == 'kind-intro')
    cluster = next(c for c in config['clusters'] if c['name'] == context['context']['cluster'])
    server = cluster['cluster']['server']
    assert server != SENTINEL_SERVER
    assert 'intro' in checks.run('kind', 'get', 'clusters').splitlines()
    assert checks.run('docker', 'ps', '-aq', '--filter', 'label=io.x-k8s.kind.cluster=intro')
    nodes = json.loads(k('get', 'nodes', '-o', 'json'))
    assert nodes['items']
    print('REAL_COLLISION_PRE_CLEANUP', json.dumps({
        'ambient_server': SENTINEL_SERVER, 'dedicated_server': server,
        'ambient_current_context': 'kind-intro', 'owned_cluster_present': True,
        'node_uids': [n['metadata']['uid'] for n in nodes['items']],
        'ambient_sha256': digest(ambient.read_bytes()),
    }), flush=True)


def after_cleanup(ambient):
    unchanged(ambient, 'after-cleanup')
    print('REAL_COLLISION_POSITIVE_CONTROL_PASS', json.dumps({
        'before_sha256': digest(SENTINEL), 'after_sha256': digest(ambient.read_bytes()),
        'ambient_byte_identical': True,
    }), flush=True)
