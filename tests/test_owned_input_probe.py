import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest import mock

TOOL = Path(__file__).resolve().parents[1] / 'tools/probe_owned_input.py'
spec = importlib.util.spec_from_file_location('probe', TOOL)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / 'fixture.nsp'
        self.marker = b'NEVER_EMIT_INPUT_CONTENT'
        self.path.write_bytes(b'PFS0' + self.marker * 1000)

    def tearDown(self):
        self.temp.cleanup()

    def child(self, path=None, mode='read', size=None):
        path = path or self.path
        return probe.supervise([sys.executable, str(TOOL), '--child', str(path), mode, str(size)], timeout=2)

    def test_bounded_read_signature_and_no_bytes(self):
        record = self.child(size=self.path.stat().st_size)
        self.assertEqual(record['exit_code'], 0)
        self.assertEqual(record['events'][-1]['count'], 4096)
        self.assertEqual(record['events'][-1]['signature'], 'PFS0')
        self.assertNotIn(self.marker.decode(), json.dumps(record))
        self.assertTrue(record['leader_reaped'])
        self.assertLess(record['elapsed_seconds'], 2.6)

    def test_key_metadata_never_opens_final_file(self):
        key = self.root / 'prod.keys'
        key.write_bytes(self.marker)
        events = []
        real_open = os.open
        def guarded_open(path, *args, **kwargs):
            self.assertNotEqual(path, 'prod.keys')
            return real_open(path, *args, **kwargs)
        with mock.patch.object(probe.os, 'open', guarded_open), mock.patch.object(probe.os, 'read', side_effect=AssertionError('no reads')):
            self.assertEqual(probe.inspect(key, False, None, events.append), 0)
        self.assertEqual(events[-1]['status'], 'metadata_only')
        self.assertNotIn(self.marker.decode(), json.dumps(events))
        self.assertEqual(self.child(key, 'read')['events'][-1]['status'], 'unsafe_read_path')

    def test_wrong_size_prevents_open(self):
        result = self.child(size=1)
        self.assertEqual(result['events'][-1]['status'], 'size_failure')
        self.assertNotIn({'stage': 'open'}, result['events'])

    def test_symlink_final_ancestor_hardlink_fifo_directory(self):
        link = self.root / 'link.nsp'
        link.symlink_to(self.path)
        self.assertEqual(self.child(link)['events'][-1]['status'], 'unsafe_file')
        directory = self.root / 'directory'
        directory.mkdir()
        (directory / 'fixture.nsp').write_bytes(b'abc')
        alias = self.root / 'alias'
        alias.symlink_to(directory, target_is_directory=True)
        self.assertEqual(self.child(alias / 'fixture.nsp')['events'][-1]['status'], 'metadata_failure')
        hardlink = self.root / 'hard.nsp'
        os.link(self.path, hardlink)
        self.assertEqual(self.child(hardlink)['events'][-1]['status'], 'unsafe_file')
        fifo = self.root / 'fifo.nsp'
        os.mkfifo(fifo)
        self.assertEqual(self.child(fifo)['events'][-1]['status'], 'unsafe_file')
        self.assertEqual(self.child(directory)['events'][-1]['status'], 'unsafe_file')

    def test_missing_and_unsafe_paths(self):
        self.assertEqual(self.child(self.root / 'absent.nsp')['events'][-1]['status'], 'metadata_failure')
        with self.assertRaises(ValueError):
            probe.parent_fd('relative.nsp')
        with self.assertRaises(ValueError):
            probe.parent_fd(str(self.root) + '/../x.nsp')

    def test_open_read_and_short_read_failures(self):
        real_open = os.open
        def denied(path, *args, **kwargs):
            if path == self.path.name:
                raise PermissionError(13, 'private detail')
            return real_open(path, *args, **kwargs)
        events = []
        with mock.patch.object(probe.os, 'open', denied):
            self.assertEqual(probe.inspect(self.path, True, None, events.append), 2)
        self.assertEqual(events[-1], {'status': 'open_failure', 'errno': 13})
        events = []
        with mock.patch.object(probe.os, 'read', side_effect=OSError(5, 'private detail')):
            self.assertEqual(probe.inspect(self.path, True, None, events.append), 2)
        self.assertEqual(events[-1]['status'], 'read_failure')
        events = []
        with mock.patch.object(probe.os, 'read', return_value=b'x') as read:
            self.assertEqual(probe.inspect(self.path, True, None, events.append), 2)
            read.assert_called_once()
        self.assertEqual(events[-1]['status'], 'short_read')

    def test_timeout_discards_output_and_kills_owned_descendant(self):
        pidfile = self.root / 'pid'
        # Parent reaps its child during normal test cleanup if needed; supervisor
        # cannot reap a grandchild and must not claim it did.
        fixture = self.root / 'sleep.py'
        fixture.write_text('import os,sys,time\n'
            'pid=os.fork()\n'
            'if pid==0:\n'
            ' print("NEVER_EMIT_INPUT_CONTENT", flush=True)\n'
            ' time.sleep(30)\n'
            'else:\n'
            ' open(sys.argv[1],"w").write(str(pid))\n'
            ' print("NEVER_EMIT_INPUT_CONTENT", file=sys.stderr, flush=True)\n'
            ' time.sleep(30)\n')
        result = probe.supervise([sys.executable, str(fixture), str(pidfile)], timeout=.3)
        self.assertTrue(result['timed_out'])
        self.assertTrue(result['leader_reaped'])
        self.assertEqual(result['exit_code'], -signal.SIGKILL)
        self.assertLess(result['elapsed_seconds'], 1)
        self.assertNotIn(self.marker.decode(), json.dumps(result))
        pid = int(pidfile.read_text())
        # A killed orphan may briefly remain a zombie. ps inspects only our PID.
        import subprocess
        status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True, timeout=1)
        self.assertTrue(status.returncode == 1 or status.stdout.strip().startswith('Z'), status.stdout)

    def test_timeout_stage_and_invalid_protocol(self):
        source = 'import os,time; os.write(int(os.environ["OWNED_PROBE_FD"]), b\'{"stage":"open"}\\n\'); time.sleep(30)'
        record = probe.supervise([sys.executable, '-c', source], timeout=.2)
        self.assertEqual(record['events'], [{'stage': 'open'}])
        self.assertTrue(record['timed_out'])
        # No untrusted protocol text retained.
        record = probe.supervise([sys.executable, '-c', 'import os; os.write(int(os.environ["OWNED_PROBE_FD"]), b"bad private text")'], timeout=1)
        self.assertTrue(record['protocol_failure'])
        self.assertEqual(record['events'], [])

    def test_path_metadata_and_fixed_protocol(self):
        events = []
        with mock.patch.object(probe.os, 'open', side_effect=AssertionError('metadata must not open')):
            self.assertEqual(probe.path_metadata(self.path, events.append), 0)
        self.assertEqual(events[-1]['status'], 'metadata_only')
        self.assertTrue(all(probe.valid_event(e) for e in events))
        self.assertFalse(probe.valid_event({'status': self.marker.decode()}))
        self.assertFalse(probe.valid_event({'metadata': {'raw': self.marker.decode()}}))
        self.assertFalse(probe.valid_event({'count': 4097}))
        self.assertFalse(probe.valid_event({'read_seconds': float('nan')}))
        self.assertEqual(self.child(mode='path-metadata')['exit_code'], 0)

    def test_timeout_bounds_rejected(self):
        for bound in (0, -1, 8.01):
            with self.assertRaises(ValueError):
                probe.supervise([], timeout=bound)


if __name__ == '__main__':
    unittest.main()
