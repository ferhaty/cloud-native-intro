#!/usr/bin/env python3
"""Offline CLI replay fixture only: never invokes Docker, kind or Kubernetes."""
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ['MOCK_ROOT'])
scenario = os.environ['MOCK_SCENARIO']
with (root / 'calls.jsonl').open('a') as log:
    log.write(json.dumps({'command': name, 'args': args}) + '\n')
state_path = root / 'state.json'
state = json.loads(state_path.read_text())

def save():
    state_path.write_text(json.dumps(state))

def fail(message):
    print('MOCK ONLY: ' + message, file=sys.stderr)
    sys.exit(17)

if name == 'docker':
    assert args == ['build', '-t', 'orders-api:1.0.0', '.']
    state['built'] = True
elif name == 'kind':
    if args == ['get', 'clusters']:
        if scenario == 'discovery_failure':
            fail('cluster discovery failed')
        print('\n'.join(state['clusters']))
    elif args[:2] == ['create', 'cluster']:
        assert args[args.index('--name') + 1] == 'intro'
        assert 'intro' not in state['clusters']
        config = args[args.index('--kubeconfig') + 1]
        assert config == str(Path.cwd() / '.intro-kubeconfig')
        Path(config).write_text('MOCK ONLY dedicated kubeconfig\n')
        if scenario == 'creation_failure':
            fail('creation failed, partial file retained')
        state['clusters'].append('intro')
        state['created_here'] = True
    elif args[:2] == ['load', 'docker-image']:
        assert args == ['load', 'docker-image', 'orders-api:1.0.0', '--name', 'intro']
        assert state['created_here']
        if scenario == 'load_failure':
            fail('image load failed')
        state['loaded'] = True
    elif args[:2] == ['delete', 'cluster']:
        assert args == ['delete', 'cluster', '--name', 'intro', '--kubeconfig', str(Path.cwd() / '.intro-kubeconfig')], 'cleanup must target dedicated kubeconfig'
        assert state['created_here'], 'must never delete a pre-existing cluster'
        if scenario == 'cleanup_failure':
            fail('cluster deletion failed')
        state['clusters'].remove('intro')
        state['cleaned'] = True
    else:
        fail('unexpected kind command')
elif name == 'kubectl':
    assert args[:4] == ['--kubeconfig', str(Path.cwd() / '.intro-kubeconfig'), '--context', 'kind-intro'], 'wrong target'
    assert os.environ['KUBECONFIG'] != args[1], 'ambient config must be ignored'
    assert state['created_here'] and state['loaded']
    args = args[4:]
    if args == ['apply', '-f', 'orders.yaml']:
        if scenario == 'apply_failure':
            fail('apply failed')
        state['replicas'] = 1
        state['pods'] = ['mock-orders-a']
    elif args[0] == 'rollout':
        assert args == ['rollout', 'status', 'deployment/orders', '--timeout=120s']
    elif args[:2] == ['get', 'pods']:
        assert args[2:4] == ['-l', 'app=orders']
        if '-o' in args:
            if scenario == 'pod_lookup_failure':
                fail('pod lookup failed')
            print(state['pods'][0])
        else:
            print('MOCK ONLY pods:', ', '.join(state['pods']))
    elif args[:2] == ['run', 'client']:
        assert '--restart=Never' in args
        assert args[-4:] == ['--command', '--', 'sleep', '3600']
        state['client'] = True
    elif args[0] == 'wait':
        if 'pod/client' in args and scenario == 'client_wait_failure':
            fail('client did not become ready')
    elif args[:2] == ['exec', 'client']:
        assert state['client']
        assert 'http://orders/' in ' '.join(args)
        state['request_invocations'] += 1
        print('MOCK ONLY: request accepted by fixture; no network request made')
    elif args[:2] == ['scale', 'deployment']:
        assert args == ['scale', 'deployment', 'orders', '--replicas=3']
        state['replicas'] = 3
        state['pods'] += ['mock-orders-b', 'mock-orders-c']
    elif args[:2] == ['delete', 'pod']:
        assert args == ['delete', 'pod', 'mock-orders-a', '--wait=true', '--timeout=120s']
        state['pods'] = ['mock-orders-b', 'mock-orders-c', 'mock-orders-d']
        state['deleted_pod'] = 'mock-orders-a'
    else:
        fail('unexpected kubectl command')
else:
    fail('unexpected executable name')
save()
