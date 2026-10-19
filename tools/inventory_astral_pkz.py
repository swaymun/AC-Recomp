#!/usr/bin/env python3
"""Bounded, read-only PKZ/DAT inventory; never infers shader code/control offsets.

Format observations are attributed in docs/ASTRAL_SHADER_INVENTORY.md. Only
explicitly selected PKZ members are decoded. Names are metadata, never paths.
"""
import argparse
import collections
import csv
import io
import ctypes
import ctypes.util
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import subprocess
import time


class Invalid(ValueError):
    pass


@dataclass(frozen=True)
class Limits:
    archives: int = 128
    archive_bytes: int = 2 << 30
    input_bytes: int = 12 << 30
    entries: int = 16384
    total_entries: int = 32768
    names_bytes: int = 4 << 20
    declared_bytes: int = 1 << 30
    name_bytes: int = 256
    compressed_bytes: int = 8 << 20
    decoded_bytes: int = 8 << 20
    total_decoded_bytes: int = 16 << 20
    window_bytes: int = 16 << 20
    ratio: int = 1024
    probes: int = 8
    nodes: int = 100000
    seconds: int = 120


def require(ok, reason):
    if not ok:
        raise Invalid(reason)


def span(offset, length, size):
    require(0 <= offset <= size and 0 <= length <= size - offset, 'out-of-bounds extent')


def safe_name(raw, limit=256):
    require(0 < len(raw) <= limit, 'name length limit')
    try:
        name = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise Invalid('invalid UTF-8 name') from exc
    require(not any(ord(c) < 32 or ord(c) == 127 for c in name), 'control in name')
    require('\\' not in name and ':' not in name, 'unsafe name')
    p = PurePosixPath(name)
    require(not p.is_absolute() and all(s not in ('', '.', '..') for s in name.split('/')),
            'unsafe name')
    return name


def read_at(stream, offset, length, size):
    span(offset, length, size)
    stream.seek(offset)
    data = stream.read(length)
    require(len(data) == length, 'truncated read')
    return data


def disjoint(ranges):
    end = 0
    for start, size in sorted((o, n) for o, n in ranges if n):
        require(start >= end, 'overlapping extents')
        end = start + size


def parse_pkz(stream, size, limits=Limits()):
    require(32 <= size <= limits.archive_bytes, 'archive size limit')
    magic, version, declared, count, table, names_len = struct.unpack(
        '<4sIQIIQ', read_at(stream, 0, 32, size))
    require(magic == b'pkzl' and version == 0x10000, 'unsupported PKZ header')
    require(declared == size, 'PKZ size mismatch')
    require(0 < count <= limits.entries, 'entry count limit')
    require(table >= 32, 'table overlaps header')
    names_off = table + count * 32
    require(16 <= names_len <= limits.names_bytes, 'name table limit')
    span(table, count * 32 + names_len, size)
    records = read_at(stream, table, count * 32, size)
    names = read_at(stream, names_off, names_len, size)
    require(names[:16] == b'ZStandard' + b'\0' * 7, 'unsupported compression tag')
    members, used_names, ranges = [], set(), []
    for i in range(count):
        no, raw_size, offset, compressed_size = struct.unpack_from('<4Q', records, i * 32)
        require(16 <= no < len(names), 'name offset outside table')
        require(names[no - 1] == 0, 'name offset inside another name')
        end = names.find(b'\0', no, min(len(names), no + limits.name_bytes + 1))
        require(end != -1, 'unterminated name')
        name = safe_name(names[no:end], limits.name_bytes)
        require(name not in used_names, 'duplicate PKZ name')
        used_names.add(name)
        require(raw_size <= limits.declared_bytes, 'declared member size limit')
        require(offset >= names_off + names_len and compressed_size >= 4,
                'payload overlaps metadata or is empty')
        span(offset, compressed_size, size)
        require(read_at(stream, offset, 4, size) == b'\x28\xb5\x2f\xfd',
                'member lacks Zstandard frame magic')
        ranges.append((offset, compressed_size))
        members.append(dict(index=i, name=name, size=raw_size, offset=offset,
                            compressed_size=compressed_size))
    disjoint(ranges)
    return dict(version=version, compression='ZStandard', table_offset=table,
                name_table_offset=names_off, name_table_length=names_len, members=members)


def parse_dat(data, limits=Limits()):
    """Only inventory the observed Platinum DAT directory, not its shader wrappers."""
    require(28 <= len(data) <= limits.decoded_bytes, 'DAT size limit')
    magic, count, offsets, extensions, names, sizes, hashes = struct.unpack_from('<4s6I', data)
    require(magic == b'DAT\0', 'unsupported decoded container')
    require(0 < count <= limits.entries, 'DAT entry count limit')
    span(names, 4, len(data))
    width = struct.unpack_from('<I', data, names)[0]
    require(0 < width <= limits.name_bytes + 1, 'DAT name width limit')
    metadata = [(0, 28), (offsets, count * 4), (extensions, count * 4),
                (names, 4 + width * count), (sizes, count * 4)]
    for off, length in metadata:
        span(off, length, len(data))
    disjoint(metadata)
    metadata_end = max(o + n for o, n in metadata)
    require(metadata_end <= hashes <= len(data), 'DAT hash table offset')
    members, ranges = [], []
    for i in range(count):
        raw = data[names + 4 + i * width:names + 4 + (i + 1) * width]
        require(b'\0' in raw, 'unterminated DAT name')
        name = safe_name(raw.split(b'\0', 1)[0], limits.name_bytes)
        ext = data[extensions + i * 4:extensions + (i + 1) * 4].split(b'\0', 1)[0]
        require(ext == Path(name).suffix[1:].encode('utf-8'), 'DAT extension mismatch')
        off = struct.unpack_from('<I', data, offsets + i * 4)[0]
        size = struct.unpack_from('<I', data, sizes + i * 4)[0]
        span(off, size, len(data))
        require(not size or off >= hashes, 'DAT payload overlaps metadata')
        ranges.append((off, size))
        payload = data[off:off + size]
        members.append(dict(index=i, name=name, offset=off, size=size,
                            magic_hex=payload[:8].hex(), sha256=sha256(payload)))
    disjoint(ranges)
    return members



MANIFEST_HEADER = ['id', 'stage', 'code_off', 'code_size', 'ctrl_off', 'ctrl_size',
                   'program_start', 'program_bytes', 'const_off', 'const_size',
                   'code_sha1_16', 'code_file', 'ctrl_file']


def graphics_pair(data, limits=Limits()):
    """Restricted observed wrapper header plus pinned upstream NVN layout checks.

    No scanning or invented headers. Compute wrappers require a separate adapter.
    The tag's meaning and the control section's trailing metadata remain unknown.
    """
    require(24 <= len(data) <= limits.decoded_bytes, 'wrapper size limit')
    magic, tag, ctrl_size, ctrl_off, code_size, code_off = struct.unpack_from('<4s5I', data)
    require(magic in (b'VSO\0', b'PSO\0'), 'unsupported wrapper; compute needs separate adapter')
    require(tag in (0x0f011411, 0x0c010c11, 0x09010a11, 0x0f011111), 'unobserved wrapper tag')
    require(ctrl_off == 24 and ctrl_size >= 0x758 and ctrl_off + ctrl_size == code_off and
            code_off + code_size == len(data), 'wrapper extents disagree')
    span(ctrl_off, ctrl_size, len(data))
    span(code_off, code_size, len(data))
    code, ctrl = data[code_off:code_off + code_size], data[ctrl_off:ctrl_off + ctrl_size]
    require(len(code) >= 0x34 and code[:4] == struct.pack('<I', 0x12345678), 'unsupported code magic')
    require(ctrl[:4] == struct.pack('<I', 0x98761234), 'unsupported control magic')
    program_bytes, const_size, const_off, recorded_size, program_start = struct.unpack_from('<5I', ctrl, 0x6f8)
    require(recorded_size == code_size and program_start == 0x30, 'code/control size or start mismatch')
    require(not any(code[4:program_start]), 'nonzero NVN header padding')
    end = program_start + program_bytes
    require(program_bytes > 0 and program_bytes % 8 == 0 and end <= len(code), 'program extent invalid')
    require(const_off == ((end + 255) & ~255) and
            code_size == ((const_off + const_size + 255) & ~255), 'constant extents disagree')
    require(not any(code[end:const_off]) and not any(code[const_off + const_size:]), 'nonzero code padding')
    stage = 'vertex' if magic == b'VSO\0' else 'pixel'
    require((struct.unpack_from('<I', code, 0x30)[0] >> 10) & 15 ==
            (1 if stage == 'vertex' else 5), 'wrapper/SPH stage mismatch')
    row = ['bounded/' + stage, stage, hex(code_off), hex(code_size), hex(ctrl_off), hex(ctrl_size),
           hex(program_start), hex(program_bytes), hex(const_off), hex(const_size),
           hashlib.sha1(code).hexdigest()[:16], 'sample.code.bin', 'sample.ctrl.bin']
    text = io.StringIO(newline='')
    writer = csv.writer(text, delimiter='\t', lineterminator='\n')
    writer.writerow(MANIFEST_HEADER)
    writer.writerow(row)
    return code, ctrl, text.getvalue().encode()


def zstd_envelope(data, expected, limits):
    """Bound standard frame window/content sizes before calling the native decoder."""
    require(0 <= expected <= limits.decoded_bytes, 'decoded size limit')
    require(6 <= len(data) <= limits.compressed_bytes, 'compressed size limit')
    require(expected <= len(data) * limits.ratio, 'compression ratio limit')
    require(data[:4] == b'\x28\xb5\x2f\xfd', 'unsupported compressed magic')
    descriptor = data[4]
    require(not descriptor & 0x18, 'reserved Zstandard frame bits')
    single = bool(descriptor & 0x20)
    pos = 5
    window = 0
    if not single:
        w = data[pos]
        pos += 1
        base = 1 << (10 + (w >> 3))
        window = base + (base >> 3) * (w & 7)
    dictionary_bytes = (0, 1, 2, 4)[descriptor & 3]
    content_bytes = (1 if single else 0, 2, 4, 8)[descriptor >> 6]
    require(pos + dictionary_bytes + content_bytes <= len(data), 'truncated Zstandard header')
    dictionary = int.from_bytes(data[pos:pos + dictionary_bytes], 'little')
    require(dictionary == 0, 'unsupported Zstandard dictionary')
    pos += dictionary_bytes
    content = int.from_bytes(data[pos:pos + content_bytes], 'little') if content_bytes else None
    if content_bytes == 2:
        content += 256
    require(content is None or content == expected, 'Zstandard content size mismatch')
    window = content if single else window
    require(window <= limits.window_bytes, 'Zstandard window limit')


class Zstd:
    def __init__(self):
        path = ctypes.util.find_library('zstd')
        require(path is not None, 'libzstd unavailable; retain compressed sample')
        self.library = path
        self.lib = ctypes.CDLL(path)
        self.lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                             ctypes.c_void_p, ctypes.c_size_t]
        self.lib.ZSTD_decompress.restype = ctypes.c_size_t
        self.lib.ZSTD_findFrameCompressedSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        self.lib.ZSTD_findFrameCompressedSize.restype = ctypes.c_size_t
        self.lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
        self.lib.ZSTD_isError.restype = ctypes.c_uint
        self.lib.ZSTD_versionNumber.restype = ctypes.c_uint

    def decode(self, data, expected, limits=Limits()):
        zstd_envelope(data, expected, limits)
        n = self.lib.ZSTD_findFrameCompressedSize(data, len(data))
        require(not self.lib.ZSTD_isError(n) and n == len(data),
                'truncated, concatenated or trailing Zstandard data')
        out = ctypes.create_string_buffer(max(1, expected))
        n = self.lib.ZSTD_decompress(out, expected, data, len(data))
        require(not self.lib.ZSTD_isError(n) and n == expected, 'Zstandard decode failed or size mismatch')
        return out.raw[:expected]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def no_symlinks(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'symlink path refused')
    return path


def regular_open(path):
    no_symlinks(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise Invalid('input must be a single-link regular file')
    return os.fdopen(fd, 'rb')


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def git(repo, *args):
    p = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, timeout=10)
    return p


def fresh_output(repo, output, input_root):
    repo, output, input_root = map(no_symlinks, (repo, output, input_root))
    require(git(repo, 'rev-parse', '--show-toplevel').stdout.decode().strip() == str(repo),
            'repo must be a worktree root')
    require(output.is_relative_to(repo / '.local') and output != repo / '.local',
            'output must be below repo .local')
    require(not output.is_relative_to(input_root) and not input_root.is_relative_to(output),
            'input/output overlap')
    relative = str(output.relative_to(repo))
    require(git(repo, 'check-ignore', '--no-index', '-q', '--', relative).returncode == 0,
            'output must be Git ignored')
    require(not git(repo, 'ls-files', '--', relative).stdout, 'tracked output refused')
    require(not output.exists(), 'output must be fresh')
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.mkdir(mode=0o700)
    return output


def write_private(root, name, data):
    # Callers supply fixed/generated flat filenames, never archive member names.
    require('/' not in name and '\\' not in name and name not in ('', '.', '..'), 'unsafe output name')
    no_symlinks(root)
    fd = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
    return dict(path=name, size=len(data), sha256=sha256(data))


def discover(root, limits):
    root = no_symlinks(root)
    require(root.is_dir(), 'input root missing')
    paths, nodes = [], 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        require(len(Path(directory).relative_to(root).parts) <= 32, 'input depth limit')
        nodes += len(dirs) + len(files)
        require(nodes <= limits.nodes, 'input node limit')
        for name in dirs + files:
            require(not (Path(directory) / name).is_symlink(), 'symlink in input tree')
        for name in files:
            if name.lower().endswith('.pkz'):
                paths.append(Path(directory) / name)
                require(len(paths) <= limits.archives, 'archive count limit')
    require(paths, 'no PKZ inputs')
    return sorted(paths)


def inventory(repo, input_root, output, probes=(), limits=Limits(), extract_pair=None):
    start = time.monotonic()
    input_root = no_symlinks(input_root)
    paths = discover(input_root, limits)
    require(len(probes) <= limits.probes and len(set(probes)) == len(probes), 'probe count/duplicate limit')
    selectors = set(probes)
    for selector in selectors:
        require(selector.count('::') == 1, 'probe must be archive::member')
        for name in selector.split('::'):
            safe_name(name.encode(), limits.name_bytes)
    pair_selector = None
    pair_index = None
    if extract_pair is not None:
        require(extract_pair.count('::') == 2, 'pair must be archive::member::index')
        pair_selector, index_text = extract_pair.rsplit('::', 1)
        require(index_text.isascii() and index_text.isdecimal(), 'invalid pair member index')
        pair_index = int(index_text)
        require(pair_selector in selectors and pair_index < limits.entries, 'pair must name an explicit probe')
    output = fresh_output(repo, output, input_root)
    report = dict(schema=1, tool_sha256=sha256(Path(__file__).read_bytes()),
                  limits=asdict(limits), input_root=str(input_root),
                  archives=[], probes=[], artifacts=[], shader_code_control_pairs=None,
                  total_game_shader_count=None, shader_semantic_coverage='unknown',
                  translated_game_shaders=None, rendering='unverified')
    total_bytes = total_entries = total_decoded = 0
    found = set()
    decoder = None

    def deadline():
        require(time.monotonic() - start <= limits.seconds, 'runtime limit')

    try:
        for path in paths:
            deadline()
            relative = str(path.relative_to(input_root))
            with regular_open(path) as stream:
                before = os.fstat(stream.fileno())
                total_bytes += before.st_size
                require(total_bytes <= limits.input_bytes and before.st_size <= limits.archive_bytes,
                        'total/archive input size limit')
                digest = hashlib.sha256()
                hashed = 0
                while chunk := stream.read(min(1 << 20, before.st_size - hashed + 1)):
                    deadline()
                    hashed += len(chunk)
                    require(hashed <= before.st_size, 'input grew during hashing')
                    digest.update(chunk)
                require(hashed == before.st_size, 'input truncated during hashing')
                row = dict(path=relative, size=before.st_size, sha256=digest.hexdigest(),
                           members=[], status='rejected')
                report['archives'].append(row)
                try:
                    row.update(parse_pkz(stream, before.st_size, limits))
                except Invalid as exc:
                    row['error'] = str(exc)
                    raise
                row['status'] = 'parsed'
                total_entries += len(row['members'])
                require(total_entries <= limits.total_entries, 'total entry limit')
                for member in row['members']:
                    selector = relative + '::' + member['name']
                    if selector not in selectors:
                        continue
                    deadline()
                    found.add(selector)
                    require(member['compressed_size'] <= limits.compressed_bytes and
                            member['size'] <= limits.decoded_bytes, 'probe size limit')
                    total_decoded += member['size']
                    require(total_decoded <= limits.total_decoded_bytes, 'total decoded size limit')
                    compressed = read_at(stream, member['offset'], member['compressed_size'], before.st_size)
                    item = dict(selector=selector, **member, compressed_sha256=sha256(compressed))
                    report['probes'].append(item)
                    report['artifacts'].append(write_private(output, f'probe-{len(found):02d}.zst', compressed))
                    if decoder is None:
                        decoder = Zstd()
                        report['decoder'] = dict(library=decoder.library,
                                                version=decoder.lib.ZSTD_versionNumber())
                    decoded = decoder.decode(compressed, member['size'], limits)
                    deadline()
                    item.update(decoded_sha256=sha256(decoded), magic_hex=decoded[:8].hex())
                    report['artifacts'].append(write_private(output, f'probe-{len(found):02d}.bin', decoded))
                    children = parse_dat(decoded, limits)
                    item['members'] = children
                    item['types'] = dict(collections.Counter(Path(x['name']).suffix for x in children))
                    item['boundary'] = 'DAT directory; restricted graphics wrapper extraction only on explicit request'
                    if selector == pair_selector:
                        require(pair_index < len(children), 'pair member index outside DAT')
                        child = children[pair_index]
                        wrapper = decoded[child['offset']:child['offset'] + child['size']]
                        code, ctrl, manifest = graphics_pair(wrapper, limits)
                        for name, blob in [('sample.code.bin', code), ('sample.ctrl.bin', ctrl),
                                           ('manifest.tsv', manifest)]:
                            report['artifacts'].append(write_private(output, name, blob))
                        report['shader_code_control_pairs'] = 1
                        report['pair_source'] = dict(selector=selector, **child)
                    candidates = [x for x in children if x['magic_hex'][:8] in
                                  ('56534f00', '50534f00', '43534f00')]
                    if candidates:
                        smallest = min(candidates, key=lambda x: (x['size'], x['index']))
                        item['smallest_wrapper'] = smallest
                        payload = decoded[smallest['offset']:smallest['offset'] + smallest['size']]
                        report['artifacts'].append(write_private(output, f'probe-{len(found):02d}-smallest.bin', payload))
                require(identity(before) == identity(os.fstat(stream.fileno())) == identity(path.stat()),
                        'input changed during inventory')
        require(found == selectors, 'selected member not found')
        report['status'] = 'ok'
    except (Invalid, OSError) as exc:
        report['status'] = 'rejected'
        report['error'] = str(exc)
    report.update(archive_count=len(paths), parsed_archives=sum(a['status'] == 'parsed' for a in report['archives']),
                  archive_bytes=total_bytes, member_count=total_entries,
                  decoded_bytes=total_decoded, elapsed_seconds=round(time.monotonic() - start, 3))
    report['types'] = dict(collections.Counter(Path(m['name']).suffix
                          for a in report['archives'] for m in a['members']))
    receipt = write_private(output, 'inventory.json', (json.dumps(report, indent=2) + '\n').encode())
    return report, receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, default=Path.cwd())
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--extract-pair', help='one archive::member::DAT-child-index; graphics only')
    p.add_argument('--probe', action='append', default=[], help='exact archive-relative-path::member-name')
    args = p.parse_args()
    try:
        report, receipt = inventory(args.repo, args.input, args.output, args.probe, extract_pair=args.extract_pair)
        print(json.dumps(dict(status=report['status'], archives=report['parsed_archives'],
                              members=report['member_count'], receipt=receipt)))
        return 0 if report['status'] == 'ok' else 1
    except (Invalid, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps(dict(status='rejected', error=str(exc))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
