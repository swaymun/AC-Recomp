#!/usr/bin/env python3
"""Bounded graphics representatives; private exact-hash handoff, never a pipeline."""
import argparse
from contextlib import contextmanager
import signal
from datetime import datetime, timezone
import csv
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

import inventory_astral_pkz as inventory
import prepare_shader_tools as translator

require = inventory.require
STAGES = {'vertex': 'vertex', 'fragment': 'pixel'}
MAX_JSON = 1 << 20
MAX_PRODUCT = 16 << 20
MAX_BULK = 128
MAX_REQUESTS = 32768
MAX_LOG = 64 << 20


def read(path, limit):
    with inventory.regular_open(path) as stream:
        before = os.fstat(stream.fileno())
        require(before.st_size <= limit, 'file size limit')
        data = stream.read(limit + 1)
        require(len(data) == before.st_size and len(data) <= limit, 'file size changed')
        require(inventory.identity(before) == inventory.identity(os.fstat(stream.fileno())) ==
                inventory.identity(Path(path).stat()), 'input changed')
        return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def load(path):
    return json.loads(read(path, MAX_JSON), object_pairs_hook=unique_object,
                      parse_constant=lambda _: require(False, 'nonfinite JSON'))


def save(root, name, value):
    return inventory.write_private(root, name, (json.dumps(value, indent=2) + '\n').encode())


def selectors(value):
    bulk = isinstance(value, dict) and value.get('schema') == 2
    key = 'products' if bulk else 'representatives'
    require(isinstance(value, dict) and set(value) ==
            ({'schema', 'mode', key} if bulk else {'schema', key}) and
            type(value['schema']) is int and value['schema'] == (2 if bulk else 1), 'selector schema')
    if bulk:
        require(value['mode'] == 'bulk-graphics', 'explicit bulk mode required')
    rows = value[key]
    require(isinstance(rows, list) and (1 <= len(rows) <= MAX_BULK if bulk else 2 <= len(rows) <= 4),
            'bulk product limit' if bulk else 'select 2 to 4 representatives')
    seen, hashes, stages = set(), set(), set()
    for row in rows:
        require(isinstance(row, dict) and set(row) ==
                {'archive', 'member', 'index', 'stage', 'wrapper_sha256', 'code_sha1_16'},
                'representative schema')
        for key in ('archive', 'member'):
            require(isinstance(row[key], str) and '::' not in row[key], 'selector text')
            inventory.safe_name(row[key].encode())
        require(type(row['index']) is int and 0 <= row['index'] < inventory.Limits().entries,
                'selector index')
        require(isinstance(row['stage'], str) and row['stage'] in STAGES, 'graphics stage required')
        for key, length in (('wrapper_sha256', 64), ('code_sha1_16', 16)):
            require(isinstance(row[key], str) and re.fullmatch('[0-9a-f]{' + str(length) + '}', row[key]),
                    'selector hash')
        source = (row['archive'], row['member'], row['index'])
        require(source not in seen and row['code_sha1_16'] not in hashes,
                'duplicate/conflicting identifier')
        seen.add(source)
        hashes.add(row['code_sha1_16'])
        stages.add(row['stage'])
    require(bulk or stages == set(STAGES), 'vertex and fragment representatives required')
    return rows


def manifest_bytes(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=inventory.MANIFEST_HEADER,
                            delimiter='\t', lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def pair_row(wrapper, selection):
    code, ctrl, manifest = inventory.graphics_pair(wrapper)
    row = next(csv.DictReader(io.StringIO(manifest.decode()), delimiter='\t'))
    require(row['stage'] == STAGES[selection['stage']], 'selected stage mismatch')
    require(inventory.sha256(wrapper) == selection['wrapper_sha256'] and
            row['code_sha1_16'] == selection['code_sha1_16'], 'selected hash mismatch')
    h = row['code_sha1_16']
    row.update(id='bounded/' + row['stage'] + '/' + h,
               code_file=h + '.code.bin', ctrl_file=h + '.ctrl.bin')
    return code, ctrl, row


def validate_handoff(repo, root):
    """Recheck original header/extents and all manifest fields before translation."""
    root = inventory.no_symlinks(root)
    translator.private_path(repo, root)
    index = load(root / 'index.json')
    validate_index_mode(index)
    if index['schema'] == 2:
        require(sum(p.lstat().st_size for p in root.iterdir()) <= MAX_PRODUCT, 'bulk handoff byte limit')
    rows = selectors(index['selection'])
    records = index['by_code_sha1_16']
    require(isinstance(records, dict) and set(records) == {r['code_sha1_16'] for r in rows},
            'index identifiers mismatch')
    manifests = []
    expected_files = {'manifest.tsv', 'index.json'}
    for selection in rows:
        h = selection['code_sha1_16']
        record = records[h]
        code = read(root / (h + '.code.bin'), inventory.Limits().decoded_bytes)
        ctrl = read(root / (h + '.ctrl.bin'), inventory.Limits().decoded_bytes)
        require(inventory.sha256(code) == record['code_sha256'] and
                inventory.sha256(ctrl) == record['ctrl_sha256'], 'handoff hash mismatch')
        header = bytes.fromhex(record['wrapper_header_hex'])
        require(len(header) == 24, 'wrapper header size')
        _, _, row = pair_row(header + ctrl + code, selection)
        require(row == record['manifest'], 'index manifest mismatch')
        manifests.append(row)
        expected_files.update((row['code_file'], row['ctrl_file']))
    require({p.name for p in root.iterdir()} == expected_files, 'unexpected handoff files')
    expected = manifest_bytes(manifests)
    require(read(root / 'manifest.tsv', MAX_JSON) == expected and
            inventory.sha256(expected) == index['manifest_sha256'], 'manifest mismatch')
    require(translator.validate_manifest(repo, root) == len(rows), 'manifest count mismatch')
    return index


def strict_products(repo, output, index, validator):
    """Require exactly named regular products and independent validation of each."""
    expected = set(index['by_code_sha1_16'])
    products = {}
    nodes = list(output.iterdir())
    require(len(nodes) <= (MAX_BULK + 8 if index['schema'] == 2 else 32), 'translator output node limit')
    if index['schema'] == 2:
        require(sum(p.lstat().st_size for p in nodes) <= MAX_PRODUCT, 'bulk output byte limit')
    for path in nodes:
        inventory.no_symlinks(path)
        require(path.is_file(), 'unexpected translator output directory')
        translator.private_path(repo, path)
        # Also reject hardlinks, nonregular files and oversized logs/results.
        read(path, MAX_PRODUCT)
    require(translator.check_results(output / 'results.tsv', expected) == len(expected), 'result count')
    actual = {p.name for p in nodes if p.suffix == '.spv'}
    require(actual == {h + '.spv' for h in expected}, 'exact product identifiers mismatch')
    for h, record in index['by_code_sha1_16'].items():
        path = output / (h + '.spv')
        data = read(path, MAX_PRODUCT)
        require(len(data) >= 20 and len(data) % 4 == 0 and
                struct.unpack_from('<I', data)[0] == 0x07230203, 'SPIR-V header invalid')
        words = struct.unpack('<' + 'I' * (len(data) // 4), data)
        pos, models = 5, []
        while pos < len(words):
            count, opcode = words[pos] >> 16, words[pos] & 0xffff
            require(count > 0 and pos + count <= len(words), 'SPIR-V instruction extent')
            if opcode == 15:
                require(count >= 4, 'SPIR-V entry point extent')
                models.append(words[pos + 1])
            pos += count
        require(models == [0 if record['manifest']['stage'] == 'vertex' else 4],
                'SPIR-V stage mismatch')
        before = inventory.sha256(data)
        result = subprocess.run([str(validator), '--target-env', 'vulkan1.2', str(path)],
                                capture_output=True, timeout=60)
        require(result.returncode == 0, 'independent SPIR-V validation failed')
        require(inventory.sha256(read(path, MAX_PRODUCT)) == before, 'product changed during validation')
        products[h] = {'path': path.name, 'sha256': before, 'size': len(data),
                       'stage': record['manifest']['stage'], 'validation_exit': 0,
                       'validation_log_sha256': inventory.sha256(result.stdout + result.stderr)}
    return products


def translate(repo, root, output, prefix, expected_index=None):
    marker = load(Path(root) / 'index.json')
    require(isinstance(marker, dict), 'index schema')
    bulk = marker.get('schema') == 2
    with bounded_seconds(180) if bulk else unbounded():
        return _translate(repo, root, output, prefix, expected_index)


def _translate(repo, root, output, prefix, expected_index):
    repo, root, output, prefix = map(inventory.no_symlinks, (repo, root, output, prefix))
    index_digest = inventory.sha256(read(root / 'index.json', MAX_JSON))
    index = validate_handoff(repo, root)
    require((index['schema'] != 2 or expected_index is not None) and
            (expected_index is None or expected_index == index_digest), 'handoff index anchor required/mismatch')
    # Reserve a fresh ignored parent before the strict API creates products/.
    output = inventory.fresh_output(repo, output, root)
    report = {'schema': 1, 'status': 'translation-rejected', 'pipeline': 'unproven',
              'rendering': 'unverified', 'shader_semantic_coverage': 'unknown'}
    try:
        receipt_path = prefix / 'toolchain.json'
        receipt = load(receipt_path)
        inventory.no_symlinks(receipt['validator']['path'])
        report['toolchain_sha256'] = inventory.sha256(read(receipt_path, MAX_JSON))
        # Existing API revalidates pins, lock, packages, SDK/DLL/runtime hashes and
        # validator, rejects failed results, then runs spirv-val on every module.
        report['upstream'] = translator.batch(repo, prefix, root, output / 'products', 1)
        products = strict_products(repo, output / 'products', index, receipt['validator']['path'])
        # Publish the accepted map only after every product and source passes.
        report['input_index_sha256'] = inventory.sha256(read(root / 'index.json', MAX_JSON))
        require(inventory.sha256(read(receipt_path, MAX_JSON)) == report['toolchain_sha256'],
                'toolchain receipt changed')
        validate_handoff(repo, root)
        require(inventory.sha256(read(root / 'index.json', MAX_JSON)) == index_digest, 'handoff index changed')
        report['input_manifest_sha256'] = index['manifest_sha256']
        report['products'] = products
        if index['schema'] == 2:
            report.update(schema=2, mode='bulk-graphics')
        report['status'] = 'translated-validated'
    except (ValueError, OSError, KeyError, TypeError, StopIteration, subprocess.SubprocessError) as exc:
        report['blocker'] = str(exc)
        save(output, 'translation.json', report)
        raise inventory.Invalid('translation rejected; inspect private translation.json') from exc
    save(output, 'translation.json', report)
    return report


@contextmanager
def unbounded():
    yield


@contextmanager
def bounded_seconds(seconds):
    """Wall deadline on supported local Linux/macOS CLI; subprocess.run cleans children."""
    require(hasattr(signal, 'SIGALRM'), 'bulk wall deadline unavailable')
    def expired(*_):
        raise inventory.Invalid('bulk wall time limit')
    previous = signal.signal(signal.SIGALRM, expired)
    timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *timer)
        signal.signal(signal.SIGALRM, previous)


def validate_index_mode(index):
    require(isinstance(index, dict) and type(index.get('schema')) is int and index['schema'] in (1, 2) and
            index.get('pipeline') == 'unproven', 'index schema')
    bulk = index['schema'] == 2
    require((index.get('mode') == 'bulk-graphics' and index['selection'].get('schema') == 2)
            if bulk else index['selection'].get('schema') == 1, 'index/selection mode mismatch')
    if bulk:
        progress = index['runtime']
        requested = hash_list(progress['requested'])
        matched = hash_list(progress['matched'])
        completed = hash_list(progress['completed'])
        conflicted = hash_list(progress['conflicted'])
        require(set(completed) <= set(matched) <= set(requested) and
                set(conflicted) <= set(requested) and not set(conflicted) & set(matched) and
                progress['unmatched'] == sorted(set(requested) - set(matched) - set(conflicted)) and
                progress['remaining_matched'] == sorted(set(matched) - set(completed)) and
                set(index['by_code_sha1_16']) <= set(completed), 'bulk progress mismatch')
        for key in ('log_sha256', 'plan_sha256', 'source_sha256'):
            require(re.fullmatch('[0-9a-f]{64}', progress[key]) is not None, 'bulk identity')


def hash_list(rows):
    require(isinstance(rows, list) and len(rows) <= MAX_REQUESTS and
            all(isinstance(h, str) and re.fullmatch('[0-9a-f]{16}', h) for h in rows) and
            rows == sorted(set(rows)), 'runtime hash list')
    return rows


def runtime_requests(log, expected):
    data = read(log, MAX_LOG)
    require(inventory.sha256(data) == expected, 'runtime log hash mismatch')
    # Bind both occurrences: a missing filename alone is not a runtime request.
    matches = re.findall(rb'^nvn: shader ([0-9a-f]{16}) \(code 0x[0-9a-f]+ bytes, control '
                         rb'[0-9a-f]+\): no [^\r\n]*/([0-9a-f]{16})\.spv\r?$', data, re.M)
    require(all(a == b for a, b in matches), 'runtime request/filename mismatch')
    hashes = sorted({a.decode() for a, _ in matches})
    require(hashes, 'no observed missing runtime requests')
    return hash_list(hashes)


def bulk_extract(repo, input_root, output, plan, log, count=MAX_BULK,
                 resume=None, resume_sha256=None):
    """Explicit bounded DAT probes; exact runtime hashes, deterministic sorted chunks."""
    require(type(count) is int and 1 <= count <= MAX_BULK, 'bulk product limit')
    require(isinstance(plan, dict) and set(plan) == {'schema', 'mode', 'log_sha256', 'probes'} and
            type(plan['schema']) is int and plan['schema'] == 2 and
            plan['mode'] == 'runtime-graphics', 'bulk plan schema')
    require(isinstance(plan['log_sha256'], str) and
            re.fullmatch('[0-9a-f]{64}', plan['log_sha256']), 'runtime log anchor')
    requested = runtime_requests(log, plan['log_sha256'])
    probes = plan['probes']
    require(isinstance(probes, list) and 1 <= len(probes) <= inventory.Limits().probes, 'probe limit')
    names = []
    for p in probes:
        require(isinstance(p, dict) and set(p) ==
                {'archive', 'member', 'archive_sha256', 'decoded_sha256'}, 'bulk probe schema')
        for key in ('archive', 'member'):
            require(isinstance(p[key], str), 'bulk probe name')
            inventory.safe_name(p[key].encode())
        for key in ('archive_sha256', 'decoded_sha256'):
            require(isinstance(p[key], str) and re.fullmatch('[0-9a-f]{64}', p[key]), 'probe anchor')
        names.append(p['archive'] + '::' + p['member'])
    require(len(set(names)) == len(names), 'duplicate probes')
    canonical = dict(plan, probes=sorted(probes, key=lambda p: (p['archive'], p['member'])))
    plan_hash = inventory.sha256(json.dumps(canonical, sort_keys=True).encode())
    previous = None
    if resume is not None:
        require(resume_sha256 == inventory.sha256(read(Path(resume) / 'index.json', MAX_JSON)),
                'resume index anchor')
        previous = validate_handoff(repo, Path(resume))
        require(previous['schema'] == 2, 'bulk resume schema')
    else:
        require(resume_sha256 is None, 'resume arguments')
    output = inventory.fresh_output(repo, output, input_root)
    report = dict(schema=2, mode='bulk-graphics', at=datetime.now(timezone.utc).isoformat(),
                  tool_sha256=inventory.sha256(read(Path(__file__), MAX_JSON)),
                  status='rejected', translated=0,
                  validated=0, cache_published=0, rendering='unverified', pipeline='unproven')
    try:
        with bounded_seconds(120):
            scanned, receipt = inventory.inventory(repo, input_root, output / 'inventory', sorted(names))
        require(scanned['status'] == 'ok', 'bounded inventory rejected')
        with bounded_seconds(180):
            archives = {a['path']: a for a in scanned['archives']}
            expected = {p['archive']+'::'+p['member']: p for p in probes}
            records, payloads, selections = {}, {}, {}
            conflicts = set()
            excluded = dict(compute=0, unknown=0)
            for n, probe in enumerate(scanned['probes'], 1):
                p = expected[probe['selector']]
                require(archives[p['archive']]['sha256'] == p['archive_sha256'] and
                        probe['decoded_sha256'] == p['decoded_sha256'], 'changed source identity')
                decoded = read(output / 'inventory' / f'probe-{n:02d}.bin', inventory.Limits().decoded_bytes)
                require(inventory.sha256(decoded) == p['decoded_sha256'], 'decoded identity')
                # Reparse retained bytes without a second DAT decompression.
                for child in inventory.parse_dat(decoded):
                    wrapper = decoded[child['offset']:child['offset'] + child['size']]
                    magic = wrapper[:4]
                    if magic not in (b'VSO\0', b'PSO\0'):
                        excluded['compute' if magic == b'CSO\0' else 'unknown'] += 1
                        continue
                    code, ctrl, manifest = inventory.graphics_pair(wrapper)
                    row = next(csv.DictReader(io.StringIO(manifest.decode()), delimiter='\t'))
                    h = row['code_sha1_16']
                    selected = dict(archive=p['archive'], member=p['member'], index=child['index'],
                        stage='vertex' if row['stage'] == 'vertex' else 'fragment',
                        wrapper_sha256=inventory.sha256(wrapper), code_sha1_16=h)
                    code, ctrl, row = pair_row(wrapper, selected)
                    source = dict(archive=p['archive'], archive_sha256=p['archive_sha256'],
                                  archive_size=archives[p['archive']]['size'],
                                  compressed_member={k:v for k,v in probe.items() if k != 'members'},
                                  dat_member=child, wrapper_sha256=selected['wrapper_sha256'],
                                  wrapper_header_hex=wrapper[:24].hex())
                    if h in records:
                        if payloads[h] != (code, ctrl) or records[h]['manifest'] != row:
                            conflicts.add(h)
                        records[h]['sources'].append(source)
                        continue
                    records[h] = dict(manifest=row, wrapper_header_hex=wrapper[:24].hex(),
                                      code_sha256=inventory.sha256(code), ctrl_sha256=inventory.sha256(ctrl),
                                      sources=[source])
                    payloads[h], selections[h] = (code, ctrl), selected
            associated = sorted(set(requested) & set(records))
            conflicted = sorted(set(requested) & conflicts)
            matched = sorted(set(associated) - conflicts)
            # Bind full scanned source snapshot, including explicitly selected DAT identities.
            source_hash = inventory.sha256(json.dumps(
                [(a['path'], a['size'], a['sha256']) for a in scanned['archives']], sort_keys=True).encode())
            completed = []
            if previous is not None:
                old = previous['runtime']
                require((old['plan_sha256'], old['source_sha256'], old['requested'], old['matched'], old['conflicted']) ==
                        (plan_hash, source_hash, requested, matched, conflicted), 'resume source/plan identity changed')
                completed = old['completed']
            selected_hashes = sorted(set(matched) - set(completed))[:count]
            report.update(observed_requests=len(requested), known_graphics_associations=len(associated),
                          matched_graphics=len(matched), conflicted=len(conflicted), extracted=0,
                          unmatched=len(set(requested)-set(associated)), remaining_untranslated=len(requested))
            completed = sorted(set(completed) | set(selected_hashes))
            progress = dict(log_sha256=plan['log_sha256'], plan_sha256=plan_hash, source_sha256=source_hash,
                requested=requested, matched=matched, conflicted=conflicted, completed=completed,
                unmatched=sorted(set(requested)-set(matched)-set(conflicted)),
                remaining_matched=sorted(set(matched)-set(completed)), excluded_wrappers=excluded)
            # Conflicting identifiers never enter the transferable cache handoff.
            save(output, 'conflicts.json', {h: records[h]['sources'] for h in sorted(conflicts)})
            save(output, 'runtime.json', progress)
            require(selected_hashes, 'no remaining matched graphics products')
            handoff = output / 'handoff'
            handoff.mkdir(mode=0o700)
            rows = []
            for h in selected_hashes:
                code, ctrl = payloads[h]
                row = records[h]['manifest']
                inventory.write_private(handoff, row['code_file'], code)
                inventory.write_private(handoff, row['ctrl_file'], ctrl)
                rows.append(row)
            manifest = inventory.write_private(handoff, 'manifest.tsv', manifest_bytes(rows))
            index = dict(schema=2, mode='bulk-graphics', pipeline='unproven', runtime=progress,
                selection=dict(schema=2, mode='bulk-graphics', products=[selections[h] for h in selected_hashes]),
                manifest_sha256=manifest['sha256'], by_code_sha1_16={h:records[h] for h in selected_hashes})
            index_receipt = save(handoff, 'index.json', index)
            require(sum(p.stat().st_size for p in handoff.iterdir()) <= MAX_PRODUCT, 'bulk handoff byte limit')
            validate_handoff(repo, handoff)
            report.update(status='extracted-translation-blocked', observed_requests=len(requested),
                known_graphics_associations=len(associated), matched_graphics=len(matched),
                conflicted=len(conflicted), extracted=len(selected_hashes),
                unmatched=len(progress['unmatched']), remaining_matched=len(progress['remaining_matched']),
                remaining_untranslated=len(requested), excluded_wrappers=excluded,
                inventory_receipt=receipt, handoff_index=index_receipt,
                handoff_bytes=sum(p.stat().st_size for p in handoff.iterdir()),
                inventory_seconds=scanned['elapsed_seconds'],
                blocker='No verified local toolchain supplied; parent owns Linux translation job.',
                next_command=[sys.executable, str(Path(__file__).absolute()), 'translate', '--repo', str(repo),
                    '--input', str(handoff), '--output', str(output / 'translation-next'),
                    '--toolchain-prefix', 'PARENT_VERIFIED_LOCAL_PREFIX',
                    '--handoff-index-sha256', index_receipt['sha256']])
    except (ValueError, OSError, KeyError, TypeError, StopIteration, subprocess.SubprocessError) as exc:
        report['blocker'] = str(exc)
        save(output, 'batch.json', report)
        raise inventory.Invalid('bulk rejected; inspect private batch.json') from exc
    save(output, 'batch.json', report)
    return report


def extract(repo, input_root, output, selection, prefix=None, limits=inventory.Limits()):
    require(isinstance(selection, dict) and selection.get('schema') == 1,
            'representative extraction requires schema 1')
    chosen = selectors(selection)
    output = inventory.fresh_output(repo, output, input_root)
    report = {'schema': 1, 'status': 'rejected', 'pipeline': 'unproven',
              'rendering': 'unverified', 'shader_semantic_coverage': 'unknown',
              'cross_isa_byte_match': 'N/A', 'translated': 0,
              'tools': {Path(p).name: inventory.sha256(Path(p).read_bytes()) for p in
                        (__file__, inventory.__file__, translator.__file__)}}
    try:
        probes = list(dict.fromkeys(r['archive'] + '::' + r['member'] for r in chosen))
        scanned, receipt = inventory.inventory(repo, input_root, output / 'inventory', probes, limits)
        require(scanned['status'] == 'ok', 'bounded inventory rejected; inspect inventory/inventory.json')
        report['inventory_receipt'] = receipt
        handoff = output / 'handoff'
        handoff.mkdir(mode=0o700)
        by_selector = {r['selector']: (i, r) for i, r in enumerate(scanned['probes'], 1)}
        archives = {r['path']: r for r in scanned['archives']}
        records, manifests = {}, []
        for selected in chosen:
            n, probe = by_selector[selected['archive'] + '::' + selected['member']]
            decoded = read(output / 'inventory' / f'probe-{n:02d}.bin', limits.decoded_bytes)
            require(inventory.sha256(decoded) == probe['decoded_sha256'], 'decoded hash mismatch')
            children = inventory.parse_dat(decoded, limits)
            require(selected['index'] < len(children), 'selected DAT index missing')
            child = children[selected['index']]
            wrapper = decoded[child['offset']:child['offset'] + child['size']]
            code, ctrl, row = pair_row(wrapper, selected)
            h = row['code_sha1_16']
            require(h not in records, 'duplicate/conflicting identifier')
            inventory.write_private(handoff, row['code_file'], code)
            inventory.write_private(handoff, row['ctrl_file'], ctrl)
            records[h] = {'manifest': row, 'wrapper_header_hex': wrapper[:24].hex(),
                          'code_sha256': inventory.sha256(code), 'ctrl_sha256': inventory.sha256(ctrl),
                          'source': {'input_root': str(Path(input_root).absolute()),
                                     'archive': selected['archive'],
                                     'archive_sha256': archives[selected['archive']]['sha256'],
                                     'archive_size': archives[selected['archive']]['size'],
                                     'compressed_member': {k: v for k, v in probe.items() if k != 'members'},
                                     'dat_member': child}}
            manifests.append(row)
        manifest = inventory.write_private(handoff, 'manifest.tsv', manifest_bytes(manifests))
        index = {'schema': 1, 'pipeline': 'unproven', 'selection': selection,
                 'manifest_sha256': manifest['sha256'], 'by_code_sha1_16': records}
        index_receipt = save(handoff, 'index.json', index)
        validate_handoff(repo, handoff)
        report.update(extracted=len(records), stages={s: sum(r['stage'] == s for r in chosen) for s in STAGES},
                      handoff_manifest=manifest, handoff_index=index_receipt,
                      handoff_bytes=sum(p.stat().st_size for p in handoff.iterdir()),
                      status='extracted-translation-blocked',
                      blocker='No freshly revalidated local toolchain supplied; parent owns dependencies/transfers.',
                      next_command=[sys.executable, str(Path(__file__).absolute()), 'translate',
                                    '--repo', str(repo), '--input', str(handoff),
                                    '--output', str(output / 'translation-next'),
                                    '--toolchain-prefix', 'PARENT_VERIFIED_LOCAL_PREFIX'])
        if prefix is not None:
            translated = translate(repo, handoff, output / 'translation', prefix)
            report.update(status=translated['status'], translated=len(translated['products']), blocker=None)
    except (ValueError, OSError, KeyError, TypeError, StopIteration, subprocess.SubprocessError) as exc:
        report['status'] = 'rejected'
        report['blocker'] = str(exc)
        save(output, 'batch.json', report)
        raise inventory.Invalid('batch rejected; inspect private batch.json') from exc
    save(output, 'batch.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('extract', 'translate', 'bulk-extract'))
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--selectors', type=Path)
    parser.add_argument('--toolchain-prefix', type=Path)
    parser.add_argument('--runtime-log', type=Path)
    parser.add_argument('--chunk-size', type=int, default=MAX_BULK)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--resume-sha256')
    parser.add_argument('--handoff-index-sha256')
    args = parser.parse_args()
    try:
        if args.action == 'bulk-extract':
            require(args.selectors is not None and args.runtime_log is not None and
                    args.toolchain_prefix is None, 'bulk arguments')
            report = bulk_extract(args.repo, args.input, args.output, load(args.selectors),
                args.runtime_log, args.chunk_size, args.resume, args.resume_sha256)
        elif args.action == 'extract':
            require(args.selectors is not None, '--selectors required')
            report = extract(args.repo, args.input, args.output, load(args.selectors), args.toolchain_prefix)
        else:
            require(args.toolchain_prefix is not None and args.selectors is None, 'translate arguments')
            report = translate(args.repo, args.input, args.output, args.toolchain_prefix, args.handoff_index_sha256)
        print(json.dumps({k: report[k] for k in ('status', 'pipeline', 'rendering')}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'rejected', 'error': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
