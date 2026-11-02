"""Accept the seven reader blocks, byte-for-byte, in one Bash session.

Assertions are separate from reader output. No traps, command substitutions or
rewrites strengthen the reader guards. Step 7 is explicitly sourced even after
a failed step; its original successful-creation flag alone authorizes deletion.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

import acceptance as checks
import cleanup_isolation

ROOT = Path(__file__).resolve().parents[1]


def k(*args):
    return checks.run('kubectl', '--kubeconfig', str(ROOT / '.intro-kubeconfig'),
                      '--context', 'kind-intro', *args)


checks.k = k  # Explicit targeting for CI assertions, not a reader command override.


def prepare(directory):
    text = (ROOT / 'STEP-BY-STEP.md').read_text()
    blocks = re.findall(r'^```shell\n(.*?)^```', text, re.M | re.S)
    assert len(blocks) == 7, 'Expected exactly seven reader blocks'
    sources = dict(re.findall(r'^```(python|dockerfile|yaml)\n(.*?)^```', text, re.M | re.S))
    for lang, name in [('python', 'app.py'), ('dockerfile', 'Dockerfile'), ('yaml', 'orders.yaml')]:
        assert sources[lang].encode() == (ROOT / name).read_bytes() == (ROOT / 'snippets' / name).read_bytes()
        print('SOURCE_SHA256', name, hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), flush=True)
    for i, block in enumerate(blocks, 1):
        assert block.encode() == (ROOT / 'snippets' / f'step-{i:02}.sh').read_bytes()
        path = directory / f'step-{i:02}.sh'
        path.write_bytes(block.encode())
        subprocess.run(['bash', '-n', str(path)], check=True)
        print('READER_STEP_SHA256', i, hashlib.sha256(block.encode()).hexdigest(), flush=True)
    # `source` retains intro_created and pod across all seven blocks. Explicit
    # status handling models the guide's instruction to stop on any error.
    # No set -e or trap is imposed on the reader's interactive commands.
    prefix = 'reader_dir=' + shlex.quote(str(directory)) + '\n'
    script = prefix + '''rc=0
intro_created=false
for i in 01 02 03 04 05 06; do
  printf '\\nREADER_STEP_%s_BEGIN\\n' "$i"
  if source "$reader_dir/step-$i.sh"; then
    printf '\\nREADER_STEP_%s_END\\n' "$i"
  else
    rc=$?
    printf 'READER_STEP_%s_FAILED rc=%s\\n' "$i" "$rc" >&2
    break
  fi
  case "$i" in
    02) [[ "$intro_created" == true ]] ;;
    03) python3 tests/steps_acceptance.py one ;;
    04) python3 tests/steps_acceptance.py single-http ;;
    05) python3 tests/steps_acceptance.py three && python3 tests/steps_acceptance.py requests ;;
    06) python3 tests/steps_acceptance.py victim "$pod" && python3 tests/steps_acceptance.py replacement ;;
  esac
  check_rc=$?
  if (( check_rc != 0 )); then rc=$check_rc; break; fi
done
if [[ "$intro_created" == true ]]; then
  python3 tests/steps_acceptance.py cleanup-preflight || rc=$?
fi
printf '\\nREADER_STEP_07_BEGIN ownership=%s\\n' "$intro_created"
if source "$reader_dir/step-07.sh"; then
  printf 'READER_STEP_07_END ownership=%s\\n' "$intro_created"
else
  cleanup_rc=$?
  printf 'READER_CLEANUP_FAILED rc=%s ownership=%s\\n' "$cleanup_rc" "$intro_created" >&2
  rc=$cleanup_rc
fi
[[ "$intro_created" == false ]] || rc=1
exit "$rc"
'''
    path = directory / 'session.sh'
    path.write_text(script)
    subprocess.run(['bash', '-n', str(path)], check=True)
    return path


def single_http():
    pods = checks.ready(1)
    reply = json.loads(k('exec', 'client', '--', 'curl', '-fsS', '--max-time', '5', 'http://orders/'))
    assert reply['orders'] == [] and reply['version'] == '1.0.0' and reply['served_by'] in pods
    health = k('exec', 'client', '--', 'curl', '-fsS', '--max-time', '5', '-i',
               'http://orders.default.svc.cluster.local/healthz')
    assert '200 OK' in health and 'Content-Type: text/plain; charset=utf-8' in health and health.endswith('\n\nok')
    print('SINGLE_SERVICE_JSON', json.dumps(reply), flush=True)
    print('SINGLE_SERVICE_HEALTH_FQDN', repr(health), flush=True)


def main():
    os.chdir(ROOT)
    print('DOCKER', checks.run('docker', 'version'), flush=True)
    print('KIND', checks.run('kind', 'version'), flush=True)
    print('HOST', checks.run('uname', '-a'), flush=True)
    print('OS', Path('/etc/os-release').read_text(), flush=True)
    with tempfile.TemporaryDirectory(prefix='intro-seven-steps-') as tmp:
        directory = Path(tmp)
        os.environ['INTRO_TEST_STATE'] = str(directory / 'state.json')
        ambient = cleanup_isolation.prepare(directory, checks)
        path = prepare(directory)
        result = subprocess.run(['bash', '--noprofile', '--norc', str(path)], check=False)
        cleanup_isolation.after_cleanup(ambient)
    clusters = checks.run('kind', 'get', 'clusters').splitlines()
    assert 'intro' not in clusters
    assert not checks.run('docker', 'ps', '-aq', '--filter', 'label=io.x-k8s.kind.cluster=intro')
    assert not (ROOT / '.intro-kubeconfig').exists() and not (ROOT / '.intro-kubeconfig').is_symlink()
    print('CLEANUP_CONFIRMED intro_absent node_containers=0 dedicated_kubeconfig=absent', flush=True)
    assert result.returncode == 0, result.returncode
    print('SEVEN_STEPS_ACCEPTANCE_PASS', flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == 'cleanup-preflight':
            cleanup_isolation.before_cleanup(ROOT, k, checks)
        elif sys.argv[1] == 'single-http':
            single_http()
        else:
            checks.checkpoint(*sys.argv[1:])
    else:
        main()
