#!/usr/bin/env python3
"""Whole-archive Astral shader inventory, harness batch input, V7 validation, data-set assembly.

Every PKZ member is decoded. Wrappers are found wherever a control section
(magic 0x98761234) is preceded by a six-word wrapper header whose control offset
is 24, so wrappers nested in any container type are found, not only DAT children.
Each wrapper's code block and control section are copied byte-for-byte from the
extents its own header declares; nothing is synthesized. The runtime key is
sha1(code)[:16] (docs/SHADER_CACHE_HANDOFF.md). See docs/ASTRAL_SHADER_FULL_INVENTORY.md.
"""
import argparse
import collections
import concurrent.futures
import csv
import dataclasses
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory_astral_pkz as pkz  # noqa: E402

Invalid = pkz.Invalid
require = pkz.require

CTRL_MAGIC = struct.pack('<I', 0x98761234)
GRAPHICS_CODE_MAGIC = 0x12345678
WRAPPER_STAGE = {b'VSO\0': 'vertex', b'PSO\0': 'fragment', b'CSO\0': 'compute'}
SPH_TYPE = {'vertex': 1, 'fragment': 5}
# Control bytes the harness reads (StaticGpuAccessor/Program.cs): program/constant
# extents 0x6f8..0x70c and compute workgroup/shared memory 0x748..0x758.
RELEVANT = ((0x6f8, 0x70c), (0x748, 0x758))
MAX_CODE = 16 << 20  # runtime accepts code lengths 1..16 MiB
MANIFEST_HEADER = ['id', 'stage', 'code_off', 'code_size', 'ctrl_off', 'ctrl_size',
                   'program_start', 'program_bytes', 'const_off', 'const_size',
                   'code_sha1_16', 'code_file', 'ctrl_file']
LIMITS = dataclasses.replace(
    pkz.Limits(), archive_bytes=4 << 30, input_bytes=64 << 30, entries=1 << 20,
    total_entries=1 << 22, names_bytes=64 << 20, declared_bytes=1 << 30,
    compressed_bytes=1 << 30, decoded_bytes=1 << 30, total_decoded_bytes=1 << 40,
    window_bytes=1 << 30, ratio=1 << 20)


def relevant(ctrl):
    return b''.join(ctrl[a:b] for a, b in RELEVANT)


def parse_wrapper(data, at):
    """Return (stage, code, ctrl, info) for the wrapper header at `at`, or raise Invalid."""
    require(at >= 0 and at + 24 <= len(data), 'truncated wrapper header')
    magic, tag, ctrl_size, ctrl_off, code_size, code_off = struct.unpack_from('<4s5I', data, at)
    require(magic in WRAPPER_STAGE, 'unknown wrapper magic ' + magic.hex())
    require(ctrl_off == 24 and ctrl_size >= 0x758 and code_off == ctrl_off + ctrl_size,
            'wrapper extents disagree')
    require(0 < code_size <= MAX_CODE and at + code_off + code_size <= len(data),
            'code extent outside container')
    ctrl = data[at + ctrl_off:at + code_off]
    code = data[at + code_off:at + code_off + code_size]
    require(ctrl[:4] == CTRL_MAGIC, 'control magic')
    program_bytes, const_size, const_off, recorded, start = struct.unpack_from('<5I', ctrl, 0x6f8)
    require(recorded == code_size, 'control code length disagrees with wrapper')
    stage = WRAPPER_STAGE[magic]
    if stage == 'compute':
        require(start == 0, 'compute program start is not 0')
    else:
        require(start == 0x30 and len(code) >= 0x34, 'graphics program start is not 0x30')
        require(struct.unpack_from('<I', code, 0)[0] == GRAPHICS_CODE_MAGIC, 'graphics code magic')
        require((struct.unpack_from('<I', code, 0x30)[0] >> 10) & 15 == SPH_TYPE[stage],
                'wrapper/SPH stage mismatch')
    require(0 < program_bytes and start + program_bytes <= code_size, 'program extent')
    require(const_off + const_size <= code_size, 'constant extent')
    end = start + program_bytes
    wonder_layout = (const_off == ((end + 255) & ~255) and
                     code_size == ((const_off + const_size + 255) & ~255))
    info = dict(tag=tag, start=start, program_bytes=program_bytes, const_off=const_off,
                const_size=const_size, wrapper_size=code_off + code_size,
                wonder_layout=wonder_layout)
    return stage, code, ctrl, info


def dat_nodes(data, base=0, chain=(), depth=0, failures=None):
    """Recursive DAT children as (abs_offset, size, ext, chain); parse failures are counted."""
    nodes = []
    if depth > 8 or data[:4] != b'DAT\0':
        return nodes
    if len(data) >= 8 and struct.unpack_from('<I', data, 4)[0] == 0:
        if failures is not None:
            failures['empty DAT (zero members)'] += 1
        return nodes
    try:
        children = pkz.parse_dat(data, LIMITS)
    except Invalid as exc:
        if failures is not None:
            failures[str(exc)] += 1
        return nodes
    for child in children:
        ext = PurePosixPath(child['name']).suffix.lower()
        here = chain + (ext,)
        nodes.append((base + child['offset'], child['size'], ext, here))
        payload = data[child['offset']:child['offset'] + child['size']]
        nodes.extend(dat_nodes(payload, base + child['offset'], here, depth + 1, failures))
    return nodes


def scan_member(data, ext):
    """All wrappers in one decoded member, plus orphan control magics and attribution."""
    stats = collections.Counter()
    failures = collections.Counter()
    nodes = dat_nodes(data, failures=failures)
    found = []
    pos = data.find(CTRL_MAGIC)
    while pos != -1:
        at = pos - 24
        try:
            stage, code, ctrl, info = parse_wrapper(data, at)
        except Invalid as exc:
            magic = data[at:at + 4] if at >= 0 else b''
            stats['orphan_ctrl_magic|%s|%s|%s' % (ext, magic.hex(), exc)] += 1
        else:
            inside = [n for n in nodes if n[0] <= at < n[0] + n[1]]
            deepest = max(inside, key=lambda n: len(n[3])) if inside else None
            exact = bool(deepest and deepest[0] == at and deepest[1] == info['wrapper_size'])
            where = '/'.join((ext,) + (deepest[3] if deepest else ())) + (' exact' if exact else ' nested')
            stats['wrapper_location|' + where] += 1
            found.append((stage, code, ctrl, info))
        pos = data.find(CTRL_MAGIC, pos + 1)
    for reason, n in failures.items():
        stats['dat_parse_failure|%s|%s' % (ext, reason)] += n
    return found, stats


def scan_archive(path, root):
    """Worker: decode every member of one PKZ; return dedup'd blocks keyed by runtime hash."""
    decoder = pkz.Zstd()
    blocks = {}
    stats = collections.Counter()
    relative = str(Path(path).relative_to(root))
    with pkz.regular_open(Path(path)) as stream:
        size = os.fstat(stream.fileno()).st_size
        archive = pkz.parse_pkz(stream, size, LIMITS)
        for member in archive['members']:
            ext = PurePosixPath(member['name']).suffix.lower()
            compressed = pkz.read_at(stream, member['offset'], member['compressed_size'], size)
            data = decoder.decode(compressed, member['size'], LIMITS)
            stats['members'] += 1
            stats['decoded_bytes'] += len(data)
            found, member_stats = scan_member(data, ext)
            stats.update(member_stats)
            for stage, code, ctrl, info in found:
                stats['wrappers|' + stage] += 1
                stats['wrapper_tag|%s|%08x' % (stage, info['tag'])] += 1
                if not info['wonder_layout']:
                    stats['wonder_layout_mismatch|' + stage] += 1
                key = hashlib.sha1(code).hexdigest()[:16]
                block = blocks.setdefault(key, dict(code=code, stage=stage, stages=collections.Counter(),
                                                    ctrls={}, sources=[]))
                require(block['code'] == code, 'SHA-1 prefix collision ' + key)
                block['stages'][stage] += 1
                variant = block['ctrls'].setdefault(hashlib.sha256(ctrl).hexdigest(),
                                                    dict(ctrl=ctrl, count=0, info=info))
                variant['count'] += 1
                if len(block['sources']) < 4:
                    block['sources'].append('%s::%s' % (relative, member['name']))
    return relative, blocks, stats


def merge(into, blocks):
    for key, block in blocks.items():
        have = into.get(key)
        if have is None:
            into[key] = block
            continue
        require(have['code'] == block['code'], 'SHA-1 prefix collision ' + key)
        have['stages'].update(block['stages'])
        for digest, variant in block['ctrls'].items():
            if digest in have['ctrls']:
                have['ctrls'][digest]['count'] += variant['count']
            else:
                have['ctrls'][digest] = variant
        have['sources'] = (have['sources'] + block['sources'])[:4]


def choose(block):
    """Most frequent control variant; ties broken by the control's SHA-256 for determinism."""
    return sorted(block['ctrls'].items(), key=lambda kv: (-kv[1]['count'], kv[0]))


def manifest_row(key, stage, info, code, ctrl, code_file, ctrl_file):
    return [key, stage, '0x0', hex(len(code)), '0x0', hex(len(ctrl)), hex(info['start']),
            hex(info['program_bytes']), hex(info['const_off']), hex(info['const_size']),
            key, code_file, ctrl_file]


def write_batch(directory, rows):
    directory.mkdir(parents=True, exist_ok=False)
    with open(directory / 'manifest.tsv', 'w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(MANIFEST_HEADER)
        for row, code, ctrl in rows:
            (directory / row[11]).write_bytes(code)
            (directory / row[12]).write_bytes(ctrl)
            writer.writerow(row)


def extract(input_root, out, jobs=8):
    input_root = pkz.no_symlinks(input_root)
    out = Path(out)
    require(not out.exists(), 'output must be fresh')
    paths = [str(p) for p in pkz.discover(input_root, LIMITS)]
    blocks, stats, archives = {}, collections.Counter(), []
    with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(scan_archive, p, str(input_root)) for p in paths]
        for future in concurrent.futures.as_completed(futures):
            relative, found, archive_stats = future.result()
            archives.append(relative)
            merge(blocks, found)
            stats.update(archive_stats)
    out.mkdir(parents=True)
    rows, variant_rows, conflicts, mixed = [], collections.defaultdict(list), {}, []
    for key in sorted(blocks):
        block = blocks[key]
        if len(block['stages']) > 1:
            mixed.append(key)
        variants = choose(block)
        stage = block['stage']
        digest, first = variants[0]
        rows.append((manifest_row(key, stage, first['info'], block['code'], first['ctrl'],
                                  'code_%s.bin' % key, 'ctrl_%s.bin' % key), block['code'], first['ctrl']))
        distinct = {relevant(v['ctrl']) for _, v in variants}
        if len(distinct) > 1:
            conflicts[key] = [dict(ctrl_sha256=d, count=v['count'], relevant_hex=relevant(v['ctrl']).hex())
                              for d, v in variants]
            # Each other translation-relevant variant gets its own batch root, so the
            # harness (which dedups by hash) translates it separately.
            seen = {relevant(first['ctrl'])}
            for d, v in variants[1:]:
                if relevant(v['ctrl']) in seen:
                    continue
                seen.add(relevant(v['ctrl']))
                variant_rows[len(seen) - 1].append((manifest_row(
                    key, stage, v['info'], block['code'], v['ctrl'], 'code_%s.bin' % key,
                    'ctrl_%s_%s.bin' % (key, d[:16])), block['code'], v['ctrl']))
    write_batch(out / 'batch', rows)
    for index, vrows in sorted(variant_rows.items()):
        write_batch(out / 'variants' / str(index), vrows)
    by_stage = collections.Counter(blocks[k]['stage'] for k in blocks)
    report = dict(
        schema=1, at=datetime.now(timezone.utc).isoformat(), input_root=str(input_root),
        tool_sha256=pkz.sha256(Path(__file__).read_bytes()), archives=len(archives),
        members=stats['members'], decoded_bytes=stats['decoded_bytes'],
        wrappers={s: stats['wrappers|' + s] for s in WRAPPER_STAGE.values()},
        distinct_code_blocks=len(blocks), distinct_by_stage=dict(sorted(by_stage.items())),
        keys_with_multiple_controls=sum(len(b['ctrls']) > 1 for b in blocks.values()),
        keys_with_relevant_control_conflicts=len(conflicts), conflicts=conflicts,
        keys_with_mixed_wrapper_stage=mixed,
        variant_batches={str(i): len(r) for i, r in variant_rows.items()},
        stats={k: v for k, v in sorted(stats.items()) if '|' in k},
        sources={k: blocks[k]['sources'] for k in sorted(blocks)})
    (out / 'inventory.json').write_text(json.dumps(report, indent=1) + '\n')
    return report


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_results(path):
    with open(path, newline='') as stream:
        lines = stream.read().split('\n')
    header = lines[0].split('\t')
    rows = {}
    for line in lines[1:]:
        if line:
            fields = line.split('\t')
            rows[fields[0]] = dict(zip(header, fields), _line=line)
    return header, rows


def validate(batch, out, reference, dumps=None):
    """Compare harness products against a reference data set's spirv/ directory."""
    batch, out, reference = Path(batch), Path(out), Path(reference)
    with open(batch / 'manifest.tsv', newline='') as stream:
        extracted = {r[10]: r for r in csv.reader(stream, delimiter='\t')}
    extracted.pop('code_sha1_16', None)
    _, results = read_results(out / 'results.tsv')
    _, ref_rows = read_results(reference / 'results.tsv')
    ref_keys = sorted(p.stem for p in reference.glob('*.spv'))
    report = dict(reference_products=len(ref_keys), reference_rows=len(ref_rows),
                  missing_from_extraction=[], missing_product=[], identical=0, different=[],
                  stage_disagreements=[], dump_control_checks=None)
    for key in ref_keys:
        if key not in extracted:
            report['missing_from_extraction'].append(key)
            continue
        product = out / (key + '.spv')
        status = results.get(key, {}).get('status')
        if not product.exists() or status not in ('ok', 'ok-retry'):
            report['missing_product'].append(dict(key=key, status=status))
            continue
        if product.read_bytes() == (reference / (key + '.spv')).read_bytes():
            report['identical'] += 1
        else:
            report['different'].append(dict(key=key, status=status,
                                             reference_status=ref_rows.get(key, {}).get('status'),
                                             size=product.stat().st_size,
                                             reference_size=(reference / (key + '.spv')).stat().st_size))
        if ref_rows.get(key, {}).get('stage') not in (None, results[key]['stage']):
            report['stage_disagreements'].append(key)
    if dumps:
        dumps = Path(dumps)
        checks = dict(compared=0, code_identical=0, ctrl_identical=0, relevant_identical=0,
                      relevant_differs=[])
        for code_path in sorted(dumps.glob('code_*.bin')):
            key = code_path.stem[5:]
            if key not in extracted:
                continue
            ctrl_dump = (dumps / ('ctrl_%s.bin' % key)).read_bytes()
            ours_code = (batch / extracted[key][11]).read_bytes()
            ours_ctrl = (batch / extracted[key][12]).read_bytes()
            checks['compared'] += 1
            checks['code_identical'] += ours_code == code_path.read_bytes()
            checks['ctrl_identical'] += ours_ctrl == ctrl_dump
            if relevant(ours_ctrl) == relevant(ctrl_dump):
                checks['relevant_identical'] += 1
            else:
                checks['relevant_differs'].append(key)
        report['dump_control_checks'] = checks
    statuses = collections.Counter(r['status'] for r in results.values())
    report.update(extracted_keys=len(extracted), result_rows=len(results), statuses=dict(statuses),
                  statuses_by_stage={s: dict(collections.Counter(r['status'] for r in results.values()
                                                                 if r['stage'] == s))
                                     for s in sorted({r['stage'] for r in results.values()})})
    report['matches'] = report['identical'] == len(ref_keys)
    return report


def assemble(reference, reference_receipt, out, dataset, receipt_path, source, translator, validation):
    """New data set = reference products/rows untouched + new ok/ok-retry products appended."""
    reference, out, dataset = Path(reference), Path(out), Path(dataset)
    require(not dataset.exists() and not Path(receipt_path).exists(), 'data set must be fresh')
    ref_spirv = reference / 'spirv'
    header, ref_rows = read_results(ref_spirv / 'results.tsv')
    out_header, results = read_results(out / 'results.tsv')
    require(header == out_header, 'results.tsv header differs from reference')
    dataset.mkdir(parents=True)
    for entry in sorted(reference.iterdir()):
        if entry.is_symlink():
            os.symlink(os.readlink(entry), dataset / entry.name)
        elif entry.is_dir() and entry.name != 'spirv':
            require(not any(entry.iterdir()), 'unexpected non-empty reference directory ' + entry.name)
            (dataset / entry.name).mkdir()
        elif entry.name != 'spirv':
            raise Invalid('unexpected reference entry ' + entry.name)
    spirv = dataset / 'spirv'
    spirv.mkdir()
    for product in sorted(ref_spirv.glob('*.spv')):
        shutil.copyfile(product, spirv / product.name)
    with open(ref_spirv / 'results.tsv', newline='') as stream:
        text = stream.read()
    require(text.endswith('\n'), 'reference results.tsv lacks final newline')
    added = {}
    for key in sorted(results):
        row = results[key]
        if row['status'] not in ('ok', 'ok-retry') or (ref_spirv / (key + '.spv')).exists():
            continue
        product = out / (key + '.spv')
        require(product.exists(), 'missing product ' + key)
        shutil.copyfile(product, spirv / product.name)
        text += row['_line'] + '\n'
        added[key] = dict(sha256=file_sha256(product), stage=row['stage'], status=row['status'])
    (spirv / 'results.tsv').write_text(text)
    receipt = dict(
        at=datetime.now(timezone.utc).isoformat(), path=str(dataset),
        base='%s (receipt %s…)' % (reference.name, file_sha256(reference_receipt)[:8]),
        added=added, added_count=len(added), source=source, translator=translator,
        validation=validation, results_tsv_sha256=file_sha256(spirv / 'results.tsv'),
        product_count=len(list(spirv.glob('*.spv'))))
    Path(receipt_path).write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt, file_sha256(receipt_path)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    e = sub.add_parser('extract')
    e.add_argument('--input', type=Path, required=True)
    e.add_argument('--out', type=Path, required=True)
    e.add_argument('--jobs', type=int, default=8)
    v = sub.add_parser('validate')
    v.add_argument('--batch', type=Path, required=True)
    v.add_argument('--out', type=Path, required=True)
    v.add_argument('--reference', type=Path, required=True, help='reference spirv/ directory')
    v.add_argument('--dumps', type=Path, help='runtime miss-dump code_/ctrl_ files')
    a = sub.add_parser('assemble')
    a.add_argument('--reference', type=Path, required=True)
    a.add_argument('--reference-receipt', type=Path, required=True)
    a.add_argument('--out', type=Path, required=True)
    a.add_argument('--dataset', type=Path, required=True)
    a.add_argument('--receipt', type=Path, required=True)
    a.add_argument('--source', required=True)
    a.add_argument('--translator', required=True)
    a.add_argument('--validation', required=True)
    args = p.parse_args(argv)
    try:
        if args.command == 'extract':
            report = extract(args.input, args.out, args.jobs)
            report = {k: v for k, v in report.items() if k not in ('conflicts', 'sources', 'stats')}
        elif args.command == 'validate':
            report = validate(args.batch, args.out, args.reference, args.dumps)
        else:
            receipt, digest = assemble(args.reference, args.reference_receipt, args.out, args.dataset,
                                       args.receipt, args.source, args.translator, args.validation)
            report = dict(added_count=receipt['added_count'], product_count=receipt['product_count'],
                          results_tsv_sha256=receipt['results_tsv_sha256'], receipt_sha256=digest)
    except (Invalid, OSError) as exc:
        print(json.dumps(dict(status='rejected', error=str(exc))))
        return 1
    print(json.dumps(report, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
