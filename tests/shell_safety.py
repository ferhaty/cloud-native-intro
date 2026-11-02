"""Offline fault injection of the exact README Bash, NOT Kubernetes acceptance."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOCK = r'''
from pathlib import Path
import json, os, sys
name, args = Path(sys.argv[0]).name, sys.argv[1:]
mode = os.environ['SCENARIO']
with open('trace.jsonl', 'a') as f:
    f.write(json.dumps([name, *args]) + '\n')
if name == 'kind':
    if args == ['get', 'clusters']:
        if mode == 'discovery_failure': sys.exit(23)
        if mode == 'existing': print('intro')
    elif args[:2] == ['create', 'cluster']:
        if mode == 'create_failure': sys.exit(24)
        Path(os.environ['KUBECONFIG']).write_text('owned mock config')
    elif args == ['delete', 'cluster', '--name', 'intro']:
        if mode in ('delete_failure', 'workload_delete_failure'): sys.exit(26)
    elif args != ['load', 'docker-image', 'orders-api:1.0.0', '--name', 'intro']:
        sys.exit(97)
elif name == 'docker':
    if args != ['build', '-t', 'orders-api:1.0.0', '.']: sys.exit(97)
elif name == 'kubectl':
    assert args[:2] == ['--context', 'kind-intro'], args
    args = args[2:]
    if args and args[0].startswith('--request-timeout='):
        print('MOCK_DIAGNOSTICS ' + ' '.join(args))
        if mode == 'diagnostics_failure': sys.exit(27)
    elif args == ['apply', '-f', 'orders.yaml'] and mode in (
            'workload_failure', 'workload_delete_failure', 'diagnostics_failure'):
        sys.exit(25)
    elif args and args[0] == 'get' and any('jsonpath=' in a for a in args):
        print('orders-mock')
else:
    sys.exit(97)
'''


class ShellSafety(unittest.TestCase):
    def session(self, scenario):
        blocks = re.findall(r'^```bash\n(.*?)^```', (ROOT / 'README.md').read_text(), re.M | re.S)
        self.assertEqual(len(blocks), 1)
        with tempfile.TemporaryDirectory(prefix='intro-shell-test-') as tmp:
            cwd = Path(tmp)
            bindir = cwd / 'bin'
            bindir.mkdir()
            for name in ('kind', 'docker', 'kubectl'):
                command = bindir / name
                command.write_text('#!' + sys.executable + '\n' + MOCK)
                command.chmod(0o755)
            script = cwd / 'session.sh'
            script.write_text(blocks[0])
            env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'], SCENARIO=scenario)
            result = subprocess.run(['bash', str(script)], cwd=cwd, env=env,
                                    capture_output=True, text=True, timeout=10)
            trace = [json.loads(line) for line in (cwd / 'trace.jsonl').read_text().splitlines()]
            config_exists = (cwd / '.intro-kubeconfig').exists()
        return result, trace, config_exists

    def test_discovery_failure_never_creates_or_deletes(self):
        result, trace, _ = self.session('discovery_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(trace, [['kind', 'get', 'clusters']])

    def test_existing_intro_is_explicitly_refused_without_deletion(self):
        result, trace, _ = self.session('existing')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(trace, [['kind', 'get', 'clusters']])
        self.assertIn('Refusing existing kind clusters', result.stderr)
        self.assertIn('intro', result.stderr)

    def test_failed_creation_never_deletes_unowned_cluster(self):
        result, trace, _ = self.session('create_failure')
        self.assertEqual(result.returncode, 24)
        self.assertTrue(any(c[:3] == ['kind', 'create', 'cluster'] for c in trace))
        self.assertFalse(any(c[:3] == ['kind', 'delete', 'cluster'] for c in trace))
        self.assertFalse(any(c[0] == 'kubectl' for c in trace))

    def test_workload_error_collects_bounded_diagnostics_before_owned_cleanup(self):
        result, trace, config_exists = self.session('workload_failure')
        self.assertEqual(result.returncode, 25)
        self.assertFalse(config_exists)
        deletion = ['kind', 'delete', 'cluster', '--name', 'intro']
        self.assertEqual([c for c in trace if c[:3] == ['kind', 'delete', 'cluster']], [deletion])
        diagnostics = [c for c in trace if '--request-timeout=10s' in c]
        self.assertEqual(len(diagnostics), 2)
        self.assertTrue(any('pods,deployments' in c for c in diagnostics))
        self.assertTrue(any('events' in c for c in diagnostics))
        for command in diagnostics:
            self.assertLess(trace.index(command), trace.index(deletion))
        self.assertIn('MOCK_DIAGNOSTICS', result.stdout)

    def test_deletion_failure_is_reported_not_masked(self):
        for scenario in ('delete_failure', 'workload_delete_failure'):
            with self.subTest(scenario=scenario):
                result, trace, config_exists = self.session(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Cleanup failed', result.stderr)
                self.assertTrue(config_exists, 'Keep config for manual inspection/retry')
                self.assertEqual(trace.count(['kind', 'delete', 'cluster', '--name', 'intro']), 1)

    def test_diagnostic_errors_do_not_skip_cleanup_or_mask_workload_error(self):
        result, trace, config_exists = self.session('diagnostics_failure')
        self.assertEqual(result.returncode, 25)
        self.assertFalse(config_exists)
        self.assertEqual(trace.count(['kind', 'delete', 'cluster', '--name', 'intro']), 1)

    def test_success_deletes_owned_lab_once_without_error_diagnostics(self):
        result, trace, config_exists = self.session('success')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(config_exists)
        self.assertEqual(trace.count(['kind', 'delete', 'cluster', '--name', 'intro']), 1)
        self.assertFalse(any('--request-timeout=10s' in c for c in trace))

    def test_teaching_session_stays_under_40_lines(self):
        block, = re.findall(r'^```bash\n(.*?)^```', (ROOT / 'README.md').read_text(), re.M | re.S)
        self.assertLess(len(block.splitlines()), 40)


if __name__ == '__main__':
    unittest.main(verbosity=2)
