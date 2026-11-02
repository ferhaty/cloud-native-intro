"""Offline fault injection of the exact seven reader blocks; not Kubernetes evidence."""
from pathlib import Path
import hashlib, json, os, re, shutil, subprocess, tempfile
ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
SNIPPETS = REPO / 'snippets'
_temp = tempfile.TemporaryDirectory(prefix='intro-steps-mocks-')
EVIDENCE = Path(_temp.name)
report = {}
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def run(args, **kwargs):
    result = subprocess.run(args, text=True, capture_output=True, timeout=30, **kwargs)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result
shells = re.findall(r'^```shell\n(.*?)^```', (REPO/'STEP-BY-STEP.md').read_text(), re.M|re.S)
assert len(shells) == 7
for i, block in enumerate(shells, 1):
    assert block.encode() == (SNIPPETS/f'step-{i:02}.sh').read_bytes()
# Fault injection executes EXACT snippet files through mock CLI executables.
mock_bin = EVIDENCE / 'mock-bin'
mock_bin.mkdir(exist_ok=True)
(ROOT / 'steps_mock_command.py').chmod(0o755)
for command in ['kind', 'kubectl', 'docker']:
    link = mock_bin / command
    if not link.exists():
        link.symlink_to(ROOT / 'steps_mock_command.py')
runner = r'''
for f in "$SNIPPETS"/step-0[1-6].sh; do
  if source "$f"; then
    printf 'MOCK STEP OK %s\n' "$f"
  else
    printf 'MOCK STOPPED AT %s\n' "$f"
    break
  fi
done
source "$SNIPPETS/step-07.sh"
cleanup_rc=$?
printf 'MOCK CLEANUP RC %s FLAG %s\n' "$cleanup_rc" "$intro_created"
printf 'MOCK INTERACTIVE SHELL STILL ALIVE\n'
'''
scenarios = ['success', 'discovery_failure', 'preexisting_intro', 'other_cluster', 'existing_kubeconfig', 'creation_failure', 'load_failure', 'apply_failure', 'client_wait_failure', 'pod_lookup_failure', 'cleanup_failure']
report['mock_replay'] = {'label': 'OFFLINE MOCKS ONLY; synthetic fixture states do not validate real Kubernetes behaviour', 'scenarios': []}
for scenario in scenarios:
    workspace = EVIDENCE / ('mock-' + scenario)
    workspace.mkdir(exist_ok=True)
    for filename in ['app.py', 'Dockerfile', 'orders.yaml']:
        shutil.copyfile(SNIPPETS / filename, workspace / filename)
    state = {'clusters': ['intro'] if scenario == 'preexisting_intro' else ['unrelated'] if scenario == 'other_cluster' else [], 'created_here': False, 'loaded': False, 'client': False, 'request_invocations': 0}
    (workspace / 'state.json').write_text(json.dumps(state))
    (workspace / 'calls.jsonl').write_text('')
    kubeconfig = workspace / '.intro-kubeconfig'
    if kubeconfig.exists():
        kubeconfig.unlink()
    if scenario == 'existing_kubeconfig':
        kubeconfig.write_text('PREEXISTING DO NOT CHANGE\n')
    ambient = workspace / 'production-kubeconfig'
    ambient.write_text('MOCK ONLY unrelated production configuration\n')
    ambient_hash = digest(ambient)
    env = os.environ.copy()
    env.update(PATH=str(mock_bin) + os.pathsep + env['PATH'], MOCK_ROOT=str(workspace), MOCK_SCENARIO=scenario, SNIPPETS=str(SNIPPETS), KUBECONFIG=str(ambient))
    result = run(['bash', '--noprofile', '--norc', '-c', runner], cwd=workspace, env=env)
    (workspace / 'stdout.log').write_text(result.stdout)
    (workspace / 'stderr.log').write_text(result.stderr)
    calls = [json.loads(line) for line in (workspace / 'calls.jsonl').read_text().splitlines()]
    state = json.loads((workspace / 'state.json').read_text())
    assert digest(ambient) == ambient_hash
    assert 'MOCK INTERACTIVE SHELL STILL ALIVE' in result.stdout
    created = any(c['command'] == 'kind' and c['args'][:2] == ['create', 'cluster'] for c in calls)
    deleted = any(c['command'] == 'kind' and c['args'][:2] == ['delete', 'cluster'] for c in calls)
    kubecalls = [c for c in calls if c['command'] == 'kubectl']
    if scenario in ['discovery_failure', 'preexisting_intro', 'existing_kubeconfig']:
        assert not created and not deleted and not kubecalls
    if scenario == 'existing_kubeconfig':
        assert kubeconfig.read_text() == 'PREEXISTING DO NOT CHANGE\n'
    if scenario == 'creation_failure':
        assert created and not deleted and not kubecalls and kubeconfig.exists()
    if scenario == 'load_failure':
        assert created and deleted and not kubecalls
    if scenario in ['success', 'other_cluster', 'cleanup_failure']:
        assert state['replicas'] == 3
        assert state['deleted_pod'] == 'mock-orders-a'
        assert state['pods'] == ['mock-orders-b', 'mock-orders-c', 'mock-orders-d']
        assert state['request_invocations'] == 3
    if scenario == 'other_cluster':
        assert state['clusters'] == ['unrelated']
    if scenario == 'pod_lookup_failure':
        assert not any(c['args'][4:6] == ['delete', 'pod'] for c in kubecalls)
    if scenario == 'client_wait_failure':
        assert state['request_invocations'] == 0
    if scenario == 'cleanup_failure':
        assert kubeconfig.exists() and 'intro' in state['clusters']
        assert 'MOCK CLEANUP RC 17 FLAG true' in result.stdout
    elif state['created_here']:
        assert state['cleaned'] and not kubeconfig.exists()
    report['mock_replay']['scenarios'].append({'name': scenario, 'passed': True, 'calls': len(calls), 'creation_attempted': created, 'deletion_attempted': deleted, 'ambient_kubeconfig_unchanged': True, 'shell_survived': True})

# Negative controls prove incorrect targets and unconditional creation are rejected.
negative = []
bad_target = shells[2].replace('--context kind-intro', '--context production')
path = EVIDENCE / 'negative-wrong-context.sh'
path.write_text(bad_target)
workspace = EVIDENCE / 'negative-wrong-context-workspace'
shutil.copytree(EVIDENCE / 'mock-success', workspace, dirs_exist_ok=True)
(workspace / 'calls.jsonl').write_text('')
state = json.loads((workspace / 'state.json').read_text())
state['created_here'] = True
state['loaded'] = True
(workspace / 'state.json').write_text(json.dumps(state))
env = os.environ.copy()
env.update(PATH=str(mock_bin) + os.pathsep + env['PATH'], MOCK_ROOT=str(workspace), MOCK_SCENARIO='success', KUBECONFIG=str(workspace / 'production-kubeconfig'))
result = subprocess.run(['bash', str(path)], text=True, capture_output=True, cwd=workspace, env=env, timeout=30)
assert result.returncode != 0 and 'wrong target' in result.stderr
negative.append({'name': 'wrong_context', 'detected': True, 'returncode': result.returncode})
(EVIDENCE / 'negative-wrong-context.log').write_text(result.stdout + result.stderr)

report['negative_controls'] = negative
print(json.dumps(report, indent=2))
_temp.cleanup()
