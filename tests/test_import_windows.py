"""Portable import regressions; synthetic data only, no real keys or game files.

Set ACR_IMPORT_REFERENCE to a clean pinned Wonder checkout to additionally compile
and exercise encrypted NSP -> import -> control -> build handoff end to end.
No network, game launch or dependency installation is performed by these tests.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import types
import unittest
import zlib
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import import_owned_dump as owned
import extract_control_metadata as control
import acr_build
import acr_setup_cmd


class PortableImportTests(unittest.TestCase):
    def test_native_windows_lock_first_byte_and_release(self):
        calls = []
        fake = types.SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0)
        def locking(fd, mode, count):
            calls.append((os.lseek(fd, 0, os.SEEK_CUR), mode, count))
        fake.locking = locking
        with tempfile.TemporaryDirectory() as temp, patch.object(owned, 'WINDOWS', True), \
                patch.dict(sys.modules, msvcrt=fake):
            lock = Path(temp) / 'lock'
            with self.assertRaises(RuntimeError):
                with owned.import_lock(lock):
                    raise RuntimeError('test unwind')
            self.assertEqual(lock.read_bytes(), b'\0')
            self.assertEqual(calls, [(0, 2, 1), (0, 0, 1)])
            fake.locking = lambda *args: (_ for _ in ()).throw(OSError('synthetic busy'))
            with self.assertRaisesRegex(owned.ImportFailure, '^wrapper_already_running$'):
                with owned.import_lock(lock):
                    self.fail('busy lock was acquired')

    def test_lock_excludes_other_process_and_recovers_after_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / 'lock'
            code = ('import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                    'import import_owned_dump as m; '
                    '\nwith m.import_lock(Path(sys.argv[2])):\n print("locked",flush=True); sys.stdin.read()')
            p = subprocess.Popen([sys.executable, '-c', code, str(ROOT / 'tools'), str(lock)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.assertEqual(p.stdout.readline().strip(), b'locked')
                with self.assertRaisesRegex(owned.ImportFailure, 'wrapper_already_running'):
                    with owned.import_lock(lock):
                        self.fail('concurrent lock acquired')
            finally:
                p.communicate(b'', timeout=10)
            self.assertEqual(p.returncode, 0)
            with owned.import_lock(lock):
                pass

    def test_windows_index_rejects_drive_alias_device_and_case_collision(self):
        with patch.object(owned, 'WINDOWS', True):
            for name in ('analysis/C:escape', 'analysis/x:stream', 'analysis/NUL',
                         'analysis/COM1.bin', 'analysis/trailing.', 'analysis/trailing ',
                         'analysis/a\\b', 'analysis/../escape'):
                with self.subTest(name=name), self.assertRaises(owned.ImportFailure):
                    owned.parse_index('exefs\t0\t00000000\t' + name)
            with self.assertRaisesRegex(owned.ImportFailure, 'duplicate_index_path'):
                owned.parse_index('exefs\t0\t00000000\tanalysis/Main\n'
                                  'exefs\t0\t00000000\tanalysis/main')

    def test_atomic_metadata_receipt_is_utf8(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'receipt.json'
            control.atomic_json(p, {'status': 'synthetic', 'value': '\u2603'})
            self.assertEqual(json.loads(p.read_bytes()), {'status': 'synthetic', 'value': '\u2603'})
            self.assertEqual(list(p.parent.iterdir()), [p])

    def test_metadata_retained_inputs_accept_fresh_import_null_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / 'analysis').mkdir()
            (root / '.wrapper').mkdir()
            npdm = bytearray(0xc0)
            npdm[:4] = b'META'
            struct.pack_into('<II', npdm, 0x70, 0x80, 0x40)
            npdm[0x80:0x84] = b'ACI0'
            struct.pack_into('<Q', npdm, 0x90, 0x01007300020FA000)
            (root / 'analysis/main.npdm').write_bytes(npdm)
            dump = {'size': 1, 'sha256': '0'*64}
            (root / '.wrapper/input.json').write_text(json.dumps(dump))
            manifest = {'npdm': {**control.identity(npdm), 'title_id': '01007300020FA000'},
                        'title_id': '01007300020FA000', 'dump': dump, 'parent': None}
            self.assertIsNone(control.retained_inputs(root, manifest)['original_binding_limit'])

    def test_windows_parser_accepts_local_dump_and_keys(self):
        with patch.object(acr_build.sys, 'platform', 'win32'):
            args = acr_build.parse(['--nsp', 'C:/private/game.nsp', '--keys', 'C:/private/prod.keys',
                                    '--out', 'C:/player', '--to-stage', 'control'])
        self.assertIsNone(args.import_dir)
        self.assertEqual(args.to_stage, 'control')

    def test_control_child_discards_diagnostics_and_times_out(self):
        record, data = control.child([sys.executable, '-c',
                                      'import time; print("synthetic secret",flush=True); time.sleep(20)'],
                                     ROOT, .2, time.monotonic() + 3)
        self.assertTrue(record['timed_out'])
        self.assertNotEqual(record['exit_code'], 0)
        self.assertEqual(data, b'')

    @unittest.skipUnless(os.name == 'nt', 'Windows directory junction boundary')
    def test_junction_is_rejected_by_private_and_control_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            (repo / '.gitignore').write_text('.local/\n')
            destination = repo / 'outside'
            destination.mkdir()
            private = repo / '.local/game-private'
            private.mkdir(parents=True)
            link = private / 'escape'
            subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(destination)],
                           stdout=subprocess.DEVNULL, check=True)
            try:
                with self.assertRaisesRegex(owned.ImportFailure, 'private_symlink'):
                    owned.private_path(repo, link / 'output')
                (destination / 'file').write_text('synthetic')
                with self.assertRaisesRegex(control.Failure, 'input_symlink'):
                    control.small(link / 'file')
            finally:
                link.rmdir()


# An encryption-only helper uses the pinned original crypto primitives, not
# production importer parsing. All keys below are generated afresh by the test.
CRYPTO_HELPER = r'''
#include "nxcrypto.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
int main(int argc, char** argv) {
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY); _setmode(_fileno(stdout), _O_BINARY);
#endif
    if (argc != 4 || !nxi::crypto_self_test()) return 2;
    unsigned char key[32] = {}, iv[16] = {};
    for (size_t i=0; i<strlen(argv[2])/2; ++i) {
        unsigned v; if (sscanf(argv[2]+i*2,"%2x",&v)!=1 || i>=32) return 2; key[i]=v;
    }
    for (int i=0; i<16; ++i) { unsigned v; if (sscanf(argv[3]+i*2,"%2x",&v)!=1) return 2; iv[i]=v; }
    std::vector<unsigned char> b; int c;
    while ((c=getchar()) != EOF) b.push_back((unsigned char)c);
    nxi::Aes128 k, t; k.set_key(key); t.set_key(key+16);
    if (!strcmp(argv[1],"xts")) {
        if (b.size()%512) return 2;
        for (size_t s=0; s<b.size()/512; ++s) {
            unsigned char tw[16]={};
            for (int j=0;j<8;++j) tw[15-j]=(unsigned char)(s>>(8*j));
            t.encrypt_block(tw,tw);
            for (size_t off=s*512; off<(s+1)*512; off+=16) {
                for(int j=0;j<16;++j) b[off+j]^=tw[j];
                k.encrypt_block(b.data()+off,b.data()+off);
                for(int j=0;j<16;++j) b[off+j]^=tw[j];
                unsigned char carry=tw[15]>>7;
                for(int j=15;j>0;--j) tw[j]=(unsigned char)((tw[j]<<1)|(tw[j-1]>>7));
                tw[0]=(unsigned char)((tw[0]<<1)^(carry?0x87:0));
            }
        }
    } else if (!strcmp(argv[1],"ctr")) nxi::aes_ctr(k,iv,b.data(),b.size());
    else if (!strcmp(argv[1],"ecb")) {
        if(b.size()%16) return 2;
        for(size_t i=0;i<b.size();i+=16) k.encrypt_block(b.data()+i,b.data()+i);
    } else return 2;
    return fwrite(b.data(),1,b.size(),stdout)==b.size()?0:2;
}
'''


def pfs(files):
    names, entries, payload = bytearray(), bytearray(), bytearray()
    for name, raw in files:
        entries += struct.pack('<QQII', len(payload), len(raw), len(names), 0)
        names += name.encode() + b'\0'
        payload += raw
    return b'PFS0' + struct.pack('<III', len(files), len(names), 0) + entries + names + payload


def synthetic_module(name):
    flat = bytearray(0x300)
    struct.pack_into('<I', flat, 4, 0x40)
    flat[0x40:0x44] = b'MOD0'
    struct.pack_into('<iii', flat, 0x44, 0x40, 0x2c0, 0x2d0)
    for i, pair in enumerate(((12, 0x30), (5, 0x200), (6, 0x140), (10, 128), (11, 24), (0, 0))):
        struct.pack_into('<qQ', flat, 0x80 + i * 16, *pair)
    export = 'nnMain' if name == 'main' else '_ZN2nn4init5StartEmmPFvvES2_'
    strings = b'\0' + export.encode() + b'\0fixture_import\0'
    flat[0x200:0x200 + len(strings)] = strings
    struct.pack_into('<IBBHQQ', flat, 0x158, 1, 0x12, 0, 1, 0x10, 4)
    struct.pack_into('<IBBHQQ', flat, 0x170, len(export) + 2, 0x12, 0, 0, 0, 0)
    header = bytearray(0x100)
    header[:4] = b'NSO0'
    struct.pack_into('<I', header, 0xc, 0x38)  # all segment hashes checked
    for i, (mem, size) in enumerate(((0, 256), (256, 512), (768, 0))):
        struct.pack_into('<III', header, 0x10 + i * 16, 256 + mem, mem, size)
        struct.pack_into('<I', header, 0x60 + i * 4, size)
        header[0xa0 + i * 32:0xc0 + i * 32] = hashlib.sha256(flat[mem:mem + size]).digest()
    struct.pack_into('<I', header, 0x3c, 16)
    struct.pack_into('<II', header, 0x90, 256, 128)
    struct.pack_into('<II', header, 0x98, 64, 72)
    return bytes(header + flat), bytes(flat)


def romfs(name, raw):
    dirs = bytearray(0x18)
    struct.pack_into('<IIII', dirs, 0, 0xffffffff, 0xffffffff, 0xffffffff, 0)
    file = bytearray(0x20)
    struct.pack_into('<IIQQII', file, 0, 0, 0xffffffff, 0, len(raw), 0xffffffff, len(name))
    file += name.encode()
    header = bytearray(0x50)
    struct.pack_into('<Q', header, 0, 0x50)
    struct.pack_into('<QQ', header, 0x18, 0x50, len(dirs))
    struct.pack_into('<QQQ', header, 0x38, 0x50 + len(dirs), len(file), 0x50 + len(dirs) + len(file))
    return bytes(header + dirs + file + raw)


def pfs_section(files):
    raw = pfs(files)
    hashes = b''.join(hashlib.sha256(raw[i:i+512]).digest() for i in range(0, len(raw), 512))
    fs = bytearray(512)
    fs[2], fs[4] = 1, 3
    fs[8:40] = hashlib.sha256(hashes).digest()
    struct.pack_into('<I', fs, 0x28, 512)
    struct.pack_into('<QQQQ', fs, 0x30, 0, len(hashes), len(hashes), len(raw))
    return fs, hashes + raw


def ivfc_section(name, raw):
    data = romfs(name, raw)
    padded = data + bytes(-len(data) % 512)
    hashes = b''.join(hashlib.sha256(padded[i:i+512]).digest() for i in range(0, len(padded), 512))
    fs = bytearray(512)
    fs[4] = 3
    fs[8:12] = b'IVFC'
    struct.pack_into('<I', fs, 0x14, 3)
    struct.pack_into('<QQI', fs, 0x18, 0, len(hashes), 12)
    struct.pack_into('<QQI', fs, 0x30, len(hashes), len(data), 9)
    fs[0xc8:0xe8] = hashlib.sha256(hashes + bytes(4096-len(hashes))).digest()
    return fs, hashes + data


class SyntheticDump:
    def __init__(self, root, reference):
        self.root = root
        self.reference = reference
        self.env = None
        if os.name == 'nt':
            import windows_native
            self.env = windows_native.developer_environment()
        directory = reference / owned.SOURCE
        helper = root / ('fixture-crypto.exe' if os.name == 'nt' else 'fixture-crypto')
        source = root / 'fixture-crypto.cpp'
        source.write_text(CRYPTO_HELPER)
        result = subprocess.run(['clang++', '-std=c++17', '-O2', '-I', str(directory), str(source),
                                 str(directory / 'nxcrypto.cpp'), '-o', str(helper)],
                                env=self.env, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr.decode(errors='replace'))
        self.helper = helper
        self.header_key, self.area_key, self.content_key = os.urandom(32), os.urandom(16), os.urandom(16)
        self.title = 0x01007300020FA000
        self.expected = {}

    def encrypt(self, mode, key, data, iv=bytes(16)):
        return subprocess.run([str(self.helper), mode, key.hex(), iv.hex()], input=data,
                              capture_output=True, check=True).stdout

    def nca(self, kind, sections):
        header = bytearray(0xc00)
        header[0x200:0x204] = b'NCA3'
        header[0x205] = kind
        struct.pack_into('<Q', header, 0x210, self.title)
        header[0x320:0x330] = self.encrypt('ecb', self.area_key, self.content_key)
        body = bytearray()
        for i, (fs, raw) in enumerate(sections):
            offset = 0xc00 + len(body)
            raw += bytes(-len(raw) % 512)
            struct.pack_into('<II', header, 0x240 + i * 16, offset//512, (offset+len(raw))//512)
            header[0x400 + i*512:0x600 + i*512] = fs
            header[0x280 + i*32:0x2a0 + i*32] = hashlib.sha256(fs).digest()
            body += self.encrypt('ctr', self.content_key, raw, (offset//16).to_bytes(16, 'big'))
        struct.pack_into('<Q', header, 0x208, len(header)+len(body))
        return self.encrypt('xts', self.header_key, header) + body

    def write(self):
        # Non-ASCII and spaces exercise argv decoding on native Windows.
        inputs = self.root / 'synthetic inputs \u96ea'
        inputs.mkdir()
        keys = inputs / 'prod.keys'
        keys.write_text('header_key = '+self.header_key.hex()+'\nkey_area_key_application_00 = '+self.area_key.hex()+'\n')
        npdm = bytearray(0xc0)
        npdm[:4] = b'META'; npdm[0xe] = 44
        struct.pack_into('<I', npdm, 0x1c, 1048576)
        struct.pack_into('<II', npdm, 0x70, 0x80, 0x40)
        npdm[0x80:0x84] = b'ACI0'
        struct.pack_into('<Q', npdm, 0x90, self.title)
        files = [('main.npdm', bytes(npdm))]
        self.expected['analysis/main.npdm'] = bytes(npdm)
        for name in ('main', 'sdk'):
            nso, flat = synthetic_module(name)
            files.append((name, nso))
            self.expected['exefs/'+name], self.expected['analysis/'+name+'.bin'] = nso, flat
        payload = bytes(range(256))*8
        self.expected['extract/romfs/fixture.bin'] = payload
        program = self.nca(0, [pfs_section(files), ivfc_section('fixture.bin', payload)])
        nacp = bytearray(0x4000)
        nacp[0x3040:0x3044] = b'1.0\0'
        ctrl = self.nca(2, [ivfc_section('control.nacp', nacp)])
        cnmt = bytearray(0x30)
        struct.pack_into('<Q', cnmt, 0, self.title)
        cnmt[12] = 0x80
        struct.pack_into('<HH', cnmt, 14, 16, 2)
        for raw, kind in ((program, 1), (ctrl, 3)):
            h = hashlib.sha256(raw).digest()
            cnmt += h + h[:16] + len(raw).to_bytes(6, 'little') + bytes((kind, 0))
        cnmt += bytes(32)
        meta = self.nca(1, [pfs_section([('fixture.cnmt', cnmt)])])
        dump = inputs / 'synthetic game \u96ea.nsp'
        dump.write_bytes(pfs([('program.nca', program), ('control.nca', ctrl), ('meta.nca', meta)]))
        return dump, keys


@unittest.skipUnless(os.environ.get('ACR_IMPORT_REFERENCE'), 'set ACR_IMPORT_REFERENCE for native encrypted fixture')
class NativeImportIntegration(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows CRT/native filesystem adapter')
    def test_large_sparse_file_long_unicode_path_and_atomic_replace(self):
        import windows_native
        probe_source = r'''
#include "import_compat.h"
int wmain(int argc, wchar_t** argv) {
    if(argc!=2) return 1;
    int count=WideCharToMultiByte(CP_UTF8,0,argv[1],-1,nullptr,0,nullptr,nullptr);
    std::string p(count,'\0');
    WideCharToMultiByte(CP_UTF8,0,argv[1],-1,p.data(),count,nullptr,nullptr);p.pop_back();
    std::filesystem::create_directories(std::filesystem::path(acr_path(p)).parent_path());
    int fd=acr_open(p.c_str(),_O_RDWR|_O_CREAT|_O_TRUNC,_S_IREAD|_S_IWRITE);
    if(fd<0) return 2;
    DWORD returned;
    if(!DeviceIoControl((HANDLE)_get_osfhandle(fd),FSCTL_SET_SPARSE,nullptr,0,nullptr,0,&returned,nullptr)) return 3;
    int64_t offset=(int64_t(1)<<32)+123;
    const char expected[]="\r\n\x1a\0\xff";
    if(_lseeki64(fd,offset,SEEK_SET)!=offset || _write(fd,expected,sizeof expected)!=sizeof expected) return 4;
    struct _stat64 st{};
    if(_fstat64(fd,&st) || st.st_size!=offset+sizeof expected) return 5;
    char observed[sizeof expected];
    if(acr_pread(fd,observed,sizeof observed,offset)!=sizeof observed || memcmp(observed,expected,sizeof expected)) return 6;
    _close(fd);
    std::string final=p+".renamed";
    { std::ofstream old(std::filesystem::path(acr_path(final)),std::ios::binary);old<<"old"; }
    if(acr_rename(p.c_str(),final.c_str())) return 7;
    if(acr_stat(final.c_str(),&st) || st.st_size!=offset+sizeof expected) return 8;
    std::ifstream in(std::filesystem::path(acr_path(final)),std::ios::binary);
    in.seekg(offset);in.read(observed,sizeof observed);
    if(!in || memcmp(observed,expected,sizeof expected)) return 9;
    in.close();
    if(acr_unlink(final.c_str())) return 10;
    for(const char* bad:{"../x","..\\x","C:escape","NUL.txt","COM1","tail.","tail ","a:b"})
        if(acr_safe_name(bad)) return 11;
    if(!acr_safe_name("fixture.bin")) return 12;
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source, tool = root / 'io.cpp', root / 'io.exe'
            (root / 'import_compat.h').write_text(owned.WINDOWS_IMPORT_COMPAT, encoding='utf-8')
            source.write_text(probe_source)
            # Header supplies Win32 I/O; winioctl defines the sparse-file control.
            source.write_text(source.read_text().replace('#include \"import_compat.h\"', '#include \"import_compat.h\"\n#include <winioctl.h>'))
            env = windows_native.developer_environment()
            result = subprocess.run(['clang++', '-std=c++17', '-O2', '-I', str(root),
                                     str(source), '-o', str(tool)], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            deep = root / ('long-path-'*10) / ('long-path-'*10) / ('long-path-'*10) / 'Unicode \u96ea'
            target = deep / 'binary.bin'
            self.assertGreater(len(str(target)), 300)
            result = subprocess.run([str(tool), str(target)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(owned.long_path(target).exists())
            # Python validation must traverse deep native output even when the
            # Windows machine-wide long-path registry setting is disabled.
            data = owned.long_path(deep / 'analysis/main.bin')
            data.parent.mkdir()
            data.write_bytes(b'fixture')
            rel = (deep / 'analysis/main.bin').relative_to(root).as_posix()
            owned.secure_tree(root)
            self.assertEqual(owned.verify_index(root, {rel: {
                'kind': 'exefs', 'size': 7, 'crc32': '%08x' % zlib.crc32(b'fixture')}})['files'], 1)
            shutil.rmtree(owned.long_path(root))

    def test_encrypted_import_control_resume_and_setup_handoff(self):
        reference = Path(os.environ['ACR_IMPORT_REFERENCE']).resolve()
        # An explicit evidence root retains generated synthetic inputs for audit.
        evidence = os.environ.get('ACR_IMPORT_EVIDENCE')
        with contextlib.ExitStack() as stack:
            if evidence:
                root = Path(evidence).resolve()
                root.mkdir(parents=True, exist_ok=False)
            else:
                root = Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
            fixture = SyntheticDump(root, reference)
            dump, keys = fixture.write()
            out = root / 'private build \u96ea'
            args = acr_build.parse(['--nsp', str(dump), '--keys', str(keys), '--out', str(out),
                                    '--skip-shaders', '--to-stage', 'control'])
            ctx = acr_build.Context(args, out=io.StringIO())
            if ctx.windows:
                ctx.native_env = fixture.env
            acr_build.stage_workspace(ctx)
            # An offline source dependency, not a fake importer/compiler.
            ctx.upstream.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['git', '-c', 'core.autocrlf=false', 'clone', '--no-hardlinks', '-q',
                            str(reference), str(ctx.upstream)], check=True, capture_output=True)
            result = acr_build.stage_import(ctx)
            self.assertTrue(result['manifest_sha256'])
            for name, raw in fixture.expected.items():
                self.assertEqual((ctx.import_dir / name).read_bytes(), raw, name)
            metadata = acr_build.stage_control(ctx)
            receipt = json.loads((ctx.control / 'receipt.json').read_text())
            self.assertTrue(receipt['linkage_verified'])
            self.assertEqual(receipt['binding']['application_id'], '01007300020FA000')
            self.assertEqual(metadata['version'], 0)
            # Exercise the standalone metadata CLI too: Windows must not depend
            # on SIGALRM, fchmod, killpg or a POSIX compiler environment.
            owner = root / 'control-cli-owner'
            (owner / 'tools').mkdir(parents=True)
            (owner / '.gitignore').write_text('.local/\n')
            subprocess.run(['git', 'init', '-q', str(owner)], check=True)
            for name in ('extract_control_metadata.py', 'import_owned_dump.py', 'windows_native.py',
                         'cnmt_metadata.py', 'nacp_metadata.py'):
                shutil.copyfile(ROOT / 'tools' / name, owner / 'tools' / name)
            patch_dir = owner / 'runtime/patches'
            patch_dir.mkdir(parents=True)
            shutil.copyfile(ROOT / 'runtime/patches/astral-control-import.patch',
                            patch_dir / 'astral-control-import.patch')
            stage = root / 'synthetic-control-stage'
            stage.mkdir(mode=0o700)
            shutil.copyfile(dump, stage / 'Astral Chain.nsp')
            shutil.copyfile(keys, stage / 'prod.keys')
            (stage / 'title.keys').write_text('# synthetic unused title keys\n')
            for name in ('prod.keys', 'title.keys'):
                (stage / name).chmod(0o600)
            (stage / 'receipt.json').write_text(json.dumps({'Astral Chain.nsp': {
                'bytes': dump.stat().st_size, 'sha256': hashlib.sha256(dump.read_bytes()).hexdigest()}}))
            native = subprocess.run([sys.executable, str(owner / 'tools/extract_control_metadata.py'),
                                     '--repo', str(owner), '--reference', str(reference),
                                     '--import-dir', str(ctx.import_dir), '--source-stage', str(stage),
                                     '--cnmt-layout', acr_build.CNMT_LAYOUTS[0]], capture_output=True, text=True)
            self.assertEqual(native.returncode, 0, native.stdout + native.stderr)
            produced = json.loads(native.stdout)
            self.assertEqual(produced['status'], 'produced')
            standalone = json.loads(Path(produced['receipt']).read_text())
            self.assertEqual(standalone['binding'], receipt['binding'])
            # Recompilation and verification exercise replacement of retained files.
            self.assertTrue(acr_build.stage_import(ctx)['manifest_sha256'])
            for name, raw in fixture.expected.items():
                self.assertEqual((ctx.import_dir / name).read_bytes(), raw, name)
            # Real setup helper command includes only the requested inputs and stops
            # before later stages/FinishInstall (no invalid launcher shortcut).
            command = [sys.executable, str(ROOT / 'tools/acr_setup_cmd.py'), 'command', '--windows',
                       '--nsp', str(dump), '--keys', str(keys), '--out', str(out), '--to-stage', 'control']
            r = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            build_args = json.loads(r.stdout)['argv']
            self.assertIn('--nsp', build_args)
            self.assertNotIn('--import-dir', build_args)
            self.assertEqual(build_args[-2:], ['--to-stage', 'control'])
            manifest = json.loads((ctx.import_dir / '.wrapper/manifest.json').read_text())
            observation = {'synthetic_only': True, 'platform': sys.platform,
                           'nsp_bytes': dump.stat().st_size, 'indexed_files': manifest['validation']['files'],
                           'indexed_bytes': manifest['validation']['bytes'],
                           'expected_files': {n: hashlib.sha256(raw).hexdigest() for n, raw in fixture.expected.items()},
                           'control_receipt_sha256': metadata['receipt_sha256'], 'resume_passed': True,
                           'standalone_control_cli_verified': True}
            (root / 'evidence.json').write_text(json.dumps(observation, indent=2)+'\n')
            print(json.dumps(observation))


if __name__ == '__main__':
    unittest.main()
