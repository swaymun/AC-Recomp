"""Offline prerequisite regressions; synthetic fixtures do not extract metadata."""
import importlib.util
import json
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('control', ROOT / 'tools/extract_control_metadata.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def npdm(program=0x1234000000000000):
    raw = bytearray(0xC0)
    raw[:4] = b'META'
    struct.pack_into('<II', raw, 0x70, 0x80, 0x40)
    raw[0x80:0x84] = b'ACI0'
    struct.pack_into('<Q', raw, 0x90, program)
    return raw


class Contracts(unittest.TestCase):
    def test_observed_program_comes_from_aci0_not_filename(self):
        self.assertEqual(m.npdm_program(npdm()), '1234000000000000')

    def test_npdm_truncation_and_conflicting_extents_fail(self):
        for length in (0, 4, 0x70, 0x80, 0x90, 0xBF):
            with self.subTest(length=length), self.assertRaises(m.Failure):
                m.npdm_program(npdm()[:length])
        for offset, size in ((0, 0x40), (0x80, 0x100), (0x80, 0x10), (0xFFFFFFFF, 0x40)):
            raw = npdm()
            struct.pack_into('<II', raw, 0x70, offset, size)
            with self.subTest(offset=offset, size=size), self.assertRaises(m.Failure):
                m.npdm_program(raw)

    def test_missing_or_zero_program_is_not_policy(self):
        for raw in (npdm(0), b'WRONG' + npdm()[5:]):
            with self.assertRaises(m.Failure):
                m.npdm_program(raw)

    def test_hash_helper_subprocess_binary_and_non_nsp_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td).resolve() / 'synthetic.nsp'
            p.write_bytes(b'PFS0\x00\xff' * 4096)
            r = subprocess.run([sys.executable, str(ROOT / 'tools/extract_control_metadata.py'), '--_hash-dump', str(p)],
                               capture_output=True, timeout=10)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(json.loads(r.stdout), m.identity(p.read_bytes()))
            p.rename(p.with_suffix('.keys'))
            r = subprocess.run([sys.executable, str(ROOT / 'tools/extract_control_metadata.py'), '--_hash-dump', str(p.with_suffix('.keys'))],
                               capture_output=True, timeout=10)
            self.assertEqual(r.returncode, 2)
            self.assertEqual(r.stdout + r.stderr, b'')

    def test_child_diagnostics_discarded_with_exact_receipt(self):
        argv = [sys.executable, '-c', 'import sys; print("SYNTHETIC_SECRET"); print("SYNTHETIC_SECRET",file=sys.stderr); sys.exit(7)']
        record, raw = m.child(argv, ROOT, 3, time.monotonic() + 5)
        self.assertEqual((record['exit_code'], raw), (7, b''))
        self.assertFalse(record['timed_out'])
        self.assertTrue(record['start_utc'].endswith('Z'))
        self.assertTrue(record['end_utc'].endswith('Z'))
        self.assertEqual(record['argv'], argv)

    def test_timeout_kills_owned_descendant_before_its_write(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'must-not-exist'
            descendant = 'import time,pathlib; time.sleep(0.8); pathlib.Path(' + repr(str(target)) + ').write_text("alive")'
            parent = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",' + repr(descendant) + ']); time.sleep(30)'
            record, raw = m.child([sys.executable, '-c', parent], ROOT, .15, time.monotonic() + 3)
            self.assertTrue(record['timed_out'])
            self.assertEqual(record['exit_code'], -signal.SIGKILL)
            time.sleep(1)
            self.assertFalse(target.exists())
            self.assertEqual(raw, b'')

    def test_total_deadline_prevents_start(self):
        with self.assertRaisesRegex(m.Failure, 'total_deadline'):
            m.child(['/nonexistent'], ROOT, 2, time.monotonic() - 1)


class GitFixtures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name).resolve()
        owner = patch.object(m, 'OWNER', self.repo)
        owner.start()
        self.addCleanup(owner.stop)
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.repo / '.gitignore').write_text('.local/\n')
        for name in m.SOURCES:
            path = self.repo / (m.BASE + name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('// synthetic source ' + name + '\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'synthetic pinned importer')
        self.pin = self.git('rev-parse', 'HEAD').decode().strip()
        self.manifest = {'importer': {'revision': self.pin, 'sources_sha256': {
            n: m.identity((self.repo / (m.BASE + n)).read_bytes())['sha256'] for n in m.SOURCES}}}

    def git(self, *argv):
        return subprocess.check_output(['git', '-C', str(self.repo), *argv], stderr=subprocess.DEVNULL)

    def test_source_bytes_must_match_git_and_receipt(self):
        with patch.object(m, 'PIN', self.pin):
            self.assertEqual(len(m.verify_sources(self.repo, self.manifest, time.monotonic() + 10, [])), 5)
            (self.repo / (m.BASE + m.SOURCES[0])).write_text('// local drift')
            with self.assertRaisesRegex(m.Failure, 'reference_modified'):
                m.verify_sources(self.repo, self.manifest, time.monotonic() + 10, [])

    def test_wrong_source_receipt_is_rejected(self):
        self.manifest['importer']['sources_sha256'][m.SOURCES[0]] = '0' * 64
        with patch.object(m, 'PIN', self.pin), self.assertRaisesRegex(m.Failure, 'source_receipt_mismatch'):
            m.verify_sources(self.repo, self.manifest, time.monotonic() + 10, [])

    def test_private_output_requires_ignored_untracked_nonsymlink(self):
        root = m.private_output(self.repo, time.monotonic() + 10, [])
        self.assertEqual(root, self.repo / m.UNIT_DIR)
        p = root / 'tracked'
        p.write_text('synthetic')
        self.git('add', '-f', str(p))
        with self.assertRaisesRegex(m.Failure, 'output_tracked'):
            m.private_output(self.repo, time.monotonic() + 10, [])

    def test_other_worktree_output_rejected(self):
        with self.assertRaisesRegex(m.Failure, 'output_not_owning_worktree'):
            m.private_output(self.repo / 'other', time.monotonic() + 10, [])

    def test_output_symlink_rejected(self):
        (self.repo / '.local').symlink_to(self.repo / 'elsewhere')
        with self.assertRaisesRegex(m.Failure, 'output_symlink'):
            m.private_output(self.repo, time.monotonic() + 10, [])

    def test_cli_wrong_pin_returns_blocked_receipt_no_policy(self):
        imported = self.repo / 'import'
        (imported / '.wrapper').mkdir(parents=True)
        (imported / '.wrapper/manifest.json').write_text(json.dumps(self.manifest))
        tool = self.repo / 'tools/extract_control_metadata.py'
        tool.parent.mkdir()
        tool.write_bytes((ROOT / 'tools/extract_control_metadata.py').read_bytes())
        r = subprocess.run([sys.executable, str(tool), '--repo', str(self.repo),
                            '--reference', str(self.repo), '--import-dir', str(imported)], capture_output=True, timeout=10)
        self.assertEqual(r.returncode, 2)
        printed = json.loads(r.stdout)
        report = json.loads(Path(printed['receipt']).read_text())
        self.assertFalse(report['metadata_produced'])
        self.assertFalse(report['linkage_verified'])
        for name in ('ratings', 'parental_flags', 'application_id', 'control_content_id'):
            self.assertIsNone(report[name])
        self.assertEqual(report['diagnostic'], 'reference_revision')
        self.assertEqual(r.stderr, b'')
        self.assertEqual(Path(printed['receipt']).stat().st_mode & 0o777, 0o600)

    def test_retained_program_and_dump_receipts_must_agree(self):
        imported = self.repo / 'import'
        (imported / 'analysis').mkdir(parents=True)
        (imported / '.wrapper').mkdir()
        raw = npdm()
        (imported / 'analysis/main.npdm').write_bytes(raw)
        manifest = {'npdm': {**m.identity(raw), 'title_id': m.npdm_program(raw)},
                    'title_id': m.npdm_program(raw), 'dump': {'size': 12, 'sha256': 'a' * 64}}
        (imported / '.wrapper/input.json').write_text(json.dumps(manifest['dump']))
        self.assertEqual(m.retained_inputs(imported, manifest)['program_id'], manifest['title_id'])
        manifest['title_id'] = '0' * 16
        with self.assertRaisesRegex(m.Failure, 'program_mismatch'):
            m.retained_inputs(imported, manifest)
        manifest['title_id'] = m.npdm_program(raw)
        manifest['dump']['size'] += 1
        with self.assertRaisesRegex(m.Failure, 'dump_receipt_mismatch'):
            m.retained_inputs(imported, manifest)

class AssociationTests(unittest.TestCase):
    def setUp(self):
        from tools.cnmt_metadata import APPLICATION_PRE15
        self.layout = APPLICATION_PRE15
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.app = 0x1234000000000000
        self.program = bytes(range(32))
        self.control = bytes(range(32, 64))
        self.p = bytes(npdm(self.app))
        self.n = bytes(0x4000)
        self.manifest = {'title_id': f'{self.app:016X}', 'npdm': m.identity(self.p)}
        self.cnmt = self.package()
        self.native = {'schema': 1, 'contents': [
            {'type': 0, 'program_id': self.manifest['title_id'], 'size': 1234,
             'sha256': self.program.hex(), 'raw': '0.npdm'},
            {'type': 1, 'program_id': self.manifest['title_id'], 'size': 567,
             'sha256': 'a' * 64, 'raw': '1.cnmt'},
            {'type': 2, 'program_id': self.manifest['title_id'], 'size': 4321,
             'sha256': self.control.hex(), 'raw': '2.nacp'}]}
        self.save()

    def package(self, extra=b''):
        h = bytearray(0x30)
        struct.pack_into('<Q', h, 0, self.app)
        h[12] = 0x80
        struct.pack_into('<HH', h, 14, 16, 2 + bool(extra))
        def entry(digest, size, kind):
            return digest + digest[:16] + size.to_bytes(6, 'little') + bytes((kind, 0))
        return bytes(h) + entry(self.program, 1234, 1) + entry(self.control, 4321, 3) + extra + bytes(32)

    def save(self):
        (self.root / '0.npdm').write_bytes(self.p)
        (self.root / '1.cnmt').write_bytes(self.cnmt)
        (self.root / '2.nacp').write_bytes(self.n)
        (self.root / 'native.json').write_text(json.dumps(self.native))

    def link(self):
        return m.link_metadata(self.root, self.manifest, layout=self.layout)

    def test_unique_pair_actual_hash_size_npdm_and_raw_identities(self):
        r = self.link()
        self.assertEqual(r['application_id'], self.manifest['title_id'])
        self.assertEqual(r['parental_flags'], 0)
        self.assertEqual(r['contents']['program']['sha256'], self.program.hex())
        self.assertEqual(r['contents']['control']['size'], 4321)
        self.assertEqual(r['raw']['2'], {'path': '2.nacp', **m.identity(self.n)})
        self.assertNotEqual(r['contents']['control']['sha256'], r['raw']['2']['sha256'])

    def test_content_hash_and_size_mismatch_fail(self):
        for kind, field, value in ((0, 'size', 1235), (2, 'sha256', 'f' * 64)):
            original = self.native['contents'][kind][field]
            self.native['contents'][kind][field] = value
            self.save()
            with self.assertRaisesRegex(m.Failure, 'content_identity_mismatch'):
                self.link()
            self.native['contents'][kind][field] = original

    def test_mixed_program_title_or_npdm_fail(self):
        self.native['contents'][2]['program_id'] = 'A' * 16
        self.save()
        with self.assertRaisesRegex(m.Failure, 'content_program_mismatch'):
            self.link()
        self.native['contents'][2]['program_id'] = self.manifest['title_id']
        self.p = bytes(npdm(self.app + 1))
        self.save()
        with self.assertRaisesRegex(m.Failure, 'program_mismatch'):
            self.link()

    def test_npdm_same_program_different_bytes_fail(self):
        self.p = self.p[:-1] + b'X'
        self.save()
        with self.assertRaisesRegex(m.Failure, 'npdm_identity_mismatch'):
            self.link()

    def test_duplicate_missing_native_types_and_path_escape_fail(self):
        self.native['contents'][1]['type'] = 0
        self.save()
        with self.assertRaisesRegex(m.Failure, 'ambiguous_native_contents'):
            self.link()
        self.native['contents'][1]['type'] = 1
        self.native['contents'][1]['raw'] = '../1.cnmt'
        self.save()
        with self.assertRaisesRegex(m.Failure, 'unsafe_native_member'):
            self.link()

    def test_multiple_control_offsets_rejected_instead_of_selection(self):
        digest = b'q' * 32
        extra = digest + digest[:16] + (4321).to_bytes(6, 'little') + bytes((3, 1))
        self.cnmt = self.package(extra)
        self.save()
        with self.assertRaisesRegex(m.Failure, 'ambiguous_program_control'):
            self.link()

    def test_unsupported_nacp_and_cnmt_fail(self):
        raw = bytearray(self.n)
        struct.pack_into('<I', raw, 0x3030, 2)
        self.n = bytes(raw)
        self.save()
        with self.assertRaises(ValueError):
            self.link()
        self.n = bytes(0x4000)
        self.cnmt += b'X'
        self.save()
        with self.assertRaises(ValueError):
            self.link()

    def test_raw_symlink_refused(self):
        target = self.root / '2.nacp'
        target.rename(self.root / 'data')
        target.symlink_to(self.root / 'data')
        with self.assertRaises(m.Failure):
            self.link()


    def test_runtime_reparses_receipt_and_refuses_raw_drift(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import prepare_runtime as runtime
        manifest_hash = 'b' * 64
        self.manifest['dump'] = {'size': 77, 'sha256': 'c' * 64}
        report = {'schema': 1, 'status': 'produced', 'metadata_produced': True,
                  'linkage_verified': True, 'manifest': {'sha256': manifest_hash},
                  'inputs': {'dump_observed': self.manifest['dump']}, 'binding': self.link(),
                  'producer_patch': m.identity((ROOT / 'runtime/patches/astral-control-import.patch').read_bytes())}
        receipt = self.root / 'receipt.json'
        receipt.write_text(json.dumps(report))
        binding, digest = runtime.validate_control(receipt, self.manifest, manifest_hash)
        self.assertEqual(binding, report['binding'])
        header = runtime.control_header(binding, digest)
        self.assertIn('0x1234000000000000ull', header)
        self.assertIn(digest, header)
        with self.assertRaisesRegex(ValueError, 'control import manifest mismatch'):
            runtime.validate_control(receipt, self.manifest, 'd' * 64)
        raw = bytearray(self.n)
        struct.pack_into('<I', raw, 0x3030, 1)
        (self.root / '2.nacp').write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'control metadata binding drift'):
            runtime.validate_control(receipt, self.manifest, manifest_hash)

    def test_runtime_header_refuses_unsupported_or_conflicting_policy(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import prepare_runtime as runtime
        binding = self.link()
        for key, value in (('program_id', '1'), ('parental_flags', 2), ('ratings', [0] * 31)):
            changed = {**binding, key: value}
            with self.assertRaises(ValueError):
                runtime.control_header(changed, 'a' * 64)
        with self.assertRaises(ValueError):
            runtime.control_header(binding, 'not a digest')


class NativeReaderTests(unittest.TestCase):
    def test_actual_pinned_native_targeted_readers(self):
        import shutil
        common = Path(subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', '--git-common-dir'], text=True).strip())
        common = common if common.is_absolute() else ROOT / common
        reference = common.resolve().parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp'
        if not reference.is_dir():
            self.skipTest('pinned private reference unavailable; no network fetch in tests')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / m.BASE
            source.mkdir(parents=True)
            self.assertEqual(subprocess.check_output(['git', '-C', str(reference), 'rev-parse', 'HEAD']).decode().strip(), m.PIN)
            for name in m.SOURCES:
                raw = (reference / m.BASE / name).read_bytes()
                self.assertEqual(raw, subprocess.check_output(['git', '-C', str(reference), 'show', m.PIN + ':' + m.BASE + name]))
                (source / name).write_bytes(raw)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), 'apply', str(ROOT / 'runtime/patches/astral-control-import.patch')], check=True)
            fixture = root / 'fixture.cpp'
            fixture.write_text(NATIVE_FIXTURE)
            subprocess.run([shutil.which('c++'), '-std=c++17', '-O2', '-I', str(source), str(fixture), str(source / 'nxcrypto.cpp'), '-o', str(root / 'fixture')], check=True, capture_output=True, timeout=90)
            result = subprocess.run([str(root / 'fixture'), str(root)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS actual targeted PFS/IVFC', result.stdout)
            self.assertEqual((root / '0.cnmt').read_bytes(), bytes([0x71]) * 48)
            self.assertEqual((root / '1.nacp').read_bytes(), bytes([0x39]) * 0x4000)
            print(result.stdout, end='')

NATIVE_FIXTURE = r'''#include "nximport.cpp"
#include <cassert>
using namespace nxi;
void put(uint8_t* p,uint64_t n,unsigned width) {for(unsigned i=0;i<width;++i)p[i]=uint8_t(n>>(i*8));}
template<class F> void rejects(F fn) {bool caught=false;try{fn();}catch(const std::runtime_error&){caught=true;}assert(caught);}
int main(int argc,char** argv) {
    assert(argc==2);std::string root=argv[1];
    // Independent synthetic PFS0, hierarchical hash table, and plaintext section.
    std::string name="Application.cnmt";std::vector<uint8_t> payload(48,0x71);
    std::vector<uint8_t> pfs(16+24+name.size()+1+payload.size());
    memcpy(pfs.data(),"PFS0",4);put(pfs.data()+4,1,4);put(pfs.data()+8,name.size()+1,4);
    put(pfs.data()+24,payload.size(),8);memcpy(pfs.data()+40,name.c_str(),name.size()+1);
    memcpy(pfs.data()+40+name.size()+1,payload.data(),payload.size());
    std::vector<uint8_t> data(32+pfs.size());sha256(pfs.data(),pfs.size(),data.data());memcpy(data.data()+32,pfs.data(),pfs.size());
    MetadataMemory memory(data);Nca n;n.file=std::make_unique<SubStorage>(&memory,0,memory.size);
    n.key_ok=true;n.content_type=1;n.title_id=1;auto& section=n.sec[0];section.present=true;section.size=data.size();section.fs=n.hdr+0x400;
    auto* fs=n.hdr+0x400;memset(fs,0,0x200);fs[2]=1;fs[4]=1;
    put(fs+0x28,256,4);put(fs+0x38,32,8);put(fs+0x40,32,8);put(fs+0x48,pfs.size(),8);sha256(data.data(),32,fs+8);
    assert(control_pfs(n,0)==pfs);std::ostringstream report;control_extract(n,root,0,report);
    assert(file_size(root+"/0.cnmt")==payload.size());
    data.back()^=1;rejects([&]{control_pfs(n,0);});data.back()^=1;
    fs[8]^=1;rejects([&]{control_pfs(n,0);});fs[8]^=1;
    put(fs+0x48,~0ull,8);rejects([&]{control_pfs(n,0);});put(fs+0x48,pfs.size(),8);
    // Independent one-file RomFS and a two-stored-level IVFC hierarchy.
    std::vector<uint8_t> rom(0x4100);put(rom.data(),0x50,8);put(rom.data()+0x18,0x50,8);put(rom.data()+0x20,24,8);
    put(rom.data()+0x38,0x68,8);put(rom.data()+0x40,44,8);put(rom.data()+0x48,0x100,8);
    put(rom.data()+0x58,0xffffffff,4);put(rom.data()+0x5c,0,4);
    put(rom.data()+0x6c,0xffffffff,4);put(rom.data()+0x78,0x4000,8);put(rom.data()+0x84,12,4);
    memcpy(rom.data()+0x88,"control.nacp",12);std::fill(rom.begin()+0x100,rom.end(),0x39);
    std::vector<uint8_t> padded(32768);memcpy(padded.data(),rom.data(),rom.size());
    std::vector<uint8_t> romdata(32+rom.size());sha256(padded.data(),padded.size(),romdata.data());memcpy(romdata.data()+32,rom.data(),rom.size());
    MetadataMemory rommemory(romdata);Nca control;control.file=std::make_unique<SubStorage>(&rommemory,0,rommemory.size);
    control.key_ok=true;control.content_type=2;control.title_id=1;auto& rs=control.sec[0];rs.present=true;rs.size=romdata.size();rs.fs=control.hdr+0x400;
    auto* rfs=control.hdr+0x400;memset(rfs,0,0x200);rfs[4]=1;auto* iv=rfs+8;memcpy(iv,"IVFC",4);put(iv+12,3,4);
    put(iv+0x18,32,8);put(iv+0x20,5,4);put(iv+0x28,32,8);put(iv+0x30,rom.size(),8);put(iv+0x38,15,4);sha256(romdata.data(),32,iv+0xc0);
    std::ostringstream romreport;control_extract(control,root,1,romreport);assert(file_size(root+"/1.nacp")==0x4000);
    romdata.back()^=1;rejects([&]{std::ostringstream out;control_extract(control,root,2,out);});romdata.back()^=1;
    iv[0xc0]^=1;rejects([&]{std::ostringstream out;control_extract(control,root,3,out);});
    puts("PASS actual targeted PFS/IVFC readers: CNMT/NACP retention, hash corruption and extent rejection");
}
'''

if __name__ == '__main__':
    unittest.main()
