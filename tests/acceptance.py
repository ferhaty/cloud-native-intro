"""Run the README Bash session unchanged, inserting extra CI-only checks.

No cloud account, secrets or deployment outside this disposable kind cluster.
The README is the reader entry point; this script is transparent test machinery.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
os.environ['KIND_EXPERIMENTAL_PROVIDER'] = 'docker'
os.environ['KUBECONFIG'] = str(ROOT / '.intro-kubeconfig')
STATE = Path(os.environ.get('INTRO_TEST_STATE', '.intro-test-state.json'))


def run(*args):
    return subprocess.check_output(args, text=True, timeout=150).strip()


def k(*args):
    return run('kubectl', '--context', 'kind-intro', *args)


def ready(count):
    deadline = time.monotonic() + 120
    pods = []
    while time.monotonic() < deadline:
        pods = json.loads(k('get', 'pods', '-l', 'app=orders', '-o', 'json'))['items']
        if len(pods) == count and all(
            not p['metadata'].get('deletionTimestamp') and
            any(c['type'] == 'Ready' and c['status'] == 'True'
                for c in p['status'].get('conditions', [])) for p in pods
        ):
            dep = json.loads(k('get', 'deployment', 'orders', '-o', 'json'))
            assert dep['spec']['replicas'] == count
            assert dep['status'].get('readyReplicas') == count
            identities = {p['metadata']['name']: p['metadata']['uid'] for p in pods}
            print('READY', count, json.dumps(identities), flush=True)
            return identities
        time.sleep(2)
    raise AssertionError(f'Expected exactly {count} non-terminating Ready pods: {pods}')


def requests(pods):
    print('CLIENT_CURL', k('exec', 'client', '--', 'curl', '--version'), flush=True)
    client = json.loads(k('get', 'pod', 'client', '-o', 'json'))
    print('CLIENT_IMAGE_ID', client['status']['containerStatuses'][0]['imageID'], flush=True)
    endpoints = json.loads(k('get', 'endpointslices', '-l',
                            'kubernetes.io/service-name=orders', '-o', 'json'))
    targets = {e['targetRef']['name'] for s in endpoints['items']
               for e in s['endpoints'] if e['conditions'].get('ready')}
    assert targets == set(pods), (targets, pods)
    body = k('exec', 'client', '--', 'sh', '-ec',
             'for i in $(seq 40); do curl -fsS --max-time 5 http://orders/; echo; done')
    replies = [json.loads(line) for line in body.splitlines()]
    assert len(replies) == 40
    for r in replies:
        assert r['orders'] == [] and r['version'] == '1.0.0'
        assert r['served_by'] in pods, r
    served = sorted({r['served_by'] for r in replies})
    assert len(served) > 1, ('Did not observe multiple replicas', served)
    health = k('exec', 'client', '--', 'curl', '-fsS', '--max-time', '5', '-i',
               'http://orders.default.svc.cluster.local/healthz')
    assert 'Content-Type: text/plain; charset=utf-8' in health
    assert health.endswith('\r\n\r\nok') or health.endswith('\n\nok')
    print('SERVICE_DNS_AND_HTTP 40/40; served_by=' + json.dumps(served), flush=True)
    print('HEALTH_FQDN', repr(health), flush=True)
    print('ACTUAL_REPLY', json.dumps(replies[0]), flush=True)


def checkpoint(stage, victim=None):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if stage == 'one':
        ready(1)
        print('KUBECTL', k('version', '-o', 'json'), flush=True)
        nodes = json.loads(k('get', 'nodes', '-o', 'json'))['items']
        print('NODE_INFO', json.dumps([n['status']['nodeInfo'] for n in nodes]), flush=True)
        print('NODE_IMAGE', run('docker', 'inspect', 'intro-control-plane',
                               '--format', '{{.Config.Image}} {{.Image}}'), flush=True)
        pod = next(iter(ready(1)))
        print('CONTAINER_PYTHON', k('exec', pod, '--', 'python', '--version'), flush=True)
        print('IMAGE', run('docker', 'image', 'inspect', 'orders-api:1.0.0',
                           '--format', '{{json .}}'), flush=True)
        actual = json.loads(k('get', 'pod', pod, '-o', 'json'))
        assert actual['spec']['containers'][0]['imagePullPolicy'] == 'IfNotPresent'
        print('POD_IMAGE_ID', actual['status']['containerStatuses'][0]['imageID'], flush=True)
    elif stage == 'three':
        state['before'] = ready(3)
    elif stage == 'requests':
        requests(state['before'])
    elif stage == 'victim':
        assert victim in state['before']
        state['victim'] = victim
        print('DELETE_TARGET', victim, state['before'][victim], flush=True)
    elif stage == 'replacement':
        after = ready(3)
        before = state['before']
        assert state['victim'] not in after
        assert before[state['victim']] not in after.values()
        assert len(set(after) - set(before)) == 1
        assert len(set(after.values()) - set(before.values())) == 1
        for name in set(after) & set(before):
            assert after[name] == before[name]
        print('NEW_IDENTITY', json.dumps({n: u for n, u in after.items() if n not in before}), flush=True)
        requests(after)
    else:
        raise AssertionError(stage)
    STATE.write_text(json.dumps(state))


def main():
    text = (ROOT / 'README.md').read_text()
    blocks = re.findall(r'^```bash\n(.*?)^```', text, re.M | re.S)
    assert len(blocks) == 1, 'Expected exactly one reader session'
    original = blocks[0]
    print('README_SESSION_SHA256', hashlib.sha256(original.encode()).hexdigest(), flush=True)
    print('DOCKER', run('docker', 'version'), flush=True)
    print('KIND', run('kind', 'version'), flush=True)
    print('HOST', run('uname', '-a'), flush=True)
    print('OS', Path('/etc/os-release').read_text(), flush=True)
    session = original
    anchors = [
        ('k rollout status deployment/orders --timeout=120s\nk scale',
         'k rollout status deployment/orders --timeout=120s\npython3 tests/acceptance.py one\nk scale'),
        ('k get pods -l app=orders\nk run',
         'k get pods -l app=orders\npython3 tests/acceptance.py three\nk run'),
        ('old=$(k get pods', 'python3 tests/acceptance.py requests\nold=$(k get pods'),
        ('k delete pod "$old"', 'python3 tests/acceptance.py victim "$old"\nk delete pod "$old"'),
        ('k get pods -l app=orders\nk exec',
         'k get pods -l app=orders\npython3 tests/acceptance.py replacement\nk exec'),
    ]
    for old, new in anchors:
        assert session.count(old) == 1, ('README changed; review test anchors', old)
        session = session.replace(old, new)
    # Keep the original EXIT trap; collect diagnostics before its cleanup on error.
    session = session.replace('trap cleanup EXIT',
        "trap 'rc=$?; if [ $rc -ne 0 ]; then k get pods -A -o wide || true; "
        "k get events -A --sort-by=.lastTimestamp || true; fi; cleanup' EXIT")
    with tempfile.TemporaryDirectory(prefix='intro-acceptance-') as tmp:
        os.environ['INTRO_TEST_STATE'] = str(Path(tmp) / 'state.json')
        script = Path(tmp) / 'session.sh'
        script.write_text(session)
        subprocess.run(['bash', '-n', str(script)], check=True)
        result = subprocess.run(['bash', '-x', str(script)], check=False)
    assert not run('kind', 'get', 'clusters')
    assert not run('docker', 'ps', '-aq', '--filter', 'label=io.x-k8s.kind.cluster=intro')
    assert not (ROOT / '.intro-kubeconfig').exists()
    print('CLEANUP_CONFIRMED clusters=0 node_containers=0 kubeconfig=absent', flush=True)
    assert result.returncode == 0, result.returncode
    print('ACCEPTANCE_PASS', flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        checkpoint(*sys.argv[1:])
    else:
        main()
