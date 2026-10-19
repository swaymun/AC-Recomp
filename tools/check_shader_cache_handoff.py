#!/usr/bin/env python3
"""Read-only selected-cache preflight; compile only standalone production parsers."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

import build_astral_shader_batch as batch

require = batch.require
read = batch.read
load = batch.load
sha256 = batch.inventory.sha256
MAX = 16 << 20
SOURCES = ('nvn_shaders.h', 'nvn_shaders.cpp', 'nvn_spirv_reflect.cpp')

# This adapter supplies I/O only. All shader hashing, resource parsing, reflection
# and ShaderInfo construction below execute the unmodified production functions.
HARNESS = r'''
#include "nvn_shaders.h"
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
using namespace nx::nvn;
std::string read(const char* p) {
    std::ifstream f(p, std::ios::binary);
    if (!f) throw 1;
    return {std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>()};
}
int main(int argc, char** argv) {
    if (argc != 7) return 2;
    try {
        auto code = read(argv[1]), ctrl = read(argv[2]), spv = read(argv[3]), tsv = read(argv[4]);
        if (ctrl.size() < 0x758 || spv.size() < 20 || spv.size() % 4) return 3;
        auto c = read_control(reinterpret_cast<const uint8_t*>(ctrl.data()));
        if (!c.valid || c.code_size != code.size()) return 4;
        std::unordered_map<std::string, std::string> records;
        auto lines = parse_results_tsv(tsv, records);
        auto it = records.find(argv[5]);
        if (it == records.end()) return 5;
        std::vector<uint32_t> words(spv.size() / 4);
        std::memcpy(words.data(), spv.data(), spv.size());
        ShaderInfo info;
        std::string error;
        if (!make_shader_info(reinterpret_cast<const uint8_t*>(code.data()),
                              reinterpret_cast<const uint8_t*>(ctrl.data()),
                              std::move(words), &it->second, info, &error)) {
            std::cerr << error << '\n'; return 6;
        }
        if (info.hash != argv[5] || std::string(stage_name(info.stage)) != argv[6]) return 7;
        for (const auto& b : info.refl.bindings)
            if (b.nvn.source == NvnSource::Unknown ||
                (b.type == DescriptorType::StorageBuffer && b.nvn.c0_offset < 0)) return 8;
        std::cout << info.hash << '\t' << stage_name(info.stage) << '\t' << lines << '\t'
                  << info.refl.bindings.size() << '\t' << info.refl.inputs.size() << '\t'
                  << info.refl.outputs.size() << '\t' << describe_like_harness(info.refl) << '\n';
        return 0;
    } catch (...) { return 9; }
}
'''


def anchored(path, expected):
    require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected), 'invalid anchor')
    data = read(path, MAX)
    require(sha256(data) == expected, 'receipt/index anchor mismatch')
    return json.loads(data, object_pairs_hook=batch.unique_object,
                      parse_constant=lambda _: require(False, 'nonfinite JSON'))


def selected_inputs(root, expected_index):
    """Reconstruct selected wrappers; bind filename to whole code and SPH stage."""
    root = batch.inventory.no_symlinks(root)
    index = anchored(root / 'index.json', expected_index)
    batch.validate_index_mode(index)
    if index['schema'] == 2:
        require(sum(p.lstat().st_size for p in root.iterdir()) <= MAX, 'bulk handoff byte limit')
    selections = batch.selectors(index['selection'])
    records = index['by_code_sha1_16']
    require(set(records) == {s['code_sha1_16'] for s in selections}, 'handoff identifiers')
    rows, inputs = [], {}
    for selection in selections:
        h = selection['code_sha1_16']
        record = records[h]
        codepath, ctrlpath = root / (h + '.code.bin'), root / (h + '.ctrl.bin')
        code, ctrl = read(codepath, MAX), read(ctrlpath, MAX)
        require(sha256(code) == record['code_sha256'] and sha256(ctrl) == record['ctrl_sha256'],
                'selected code/control hash mismatch')
        require(len(ctrl) >= 0x758, 'short control')
        size = struct.unpack_from('<I', ctrl, 0x704)[0]
        require(0 < size <= MAX and size == len(code) and
                hashlib.sha1(code[:size]).hexdigest()[:16] == h, 'runtime code hash/size mismatch')
        header = bytes.fromhex(record['wrapper_header_hex'])
        require(len(header) == 24, 'wrapper header size')
        _, _, row = batch.pair_row(header + ctrl + code, selection)
        require(row == record['manifest'], 'selected manifest mismatch')
        rows.append(row)
        inputs[h] = (codepath, ctrlpath, selection['stage'])
    manifest = read(root / 'manifest.tsv', MAX)
    require(manifest == batch.manifest_bytes(rows) and sha256(manifest) == index['manifest_sha256'],
            'handoff manifest mismatch')
    return inputs, index['manifest_sha256']


def result_rows(data, inputs):
    """Strict preflight around production's permissive TSV reader (no CSV quoting)."""
    lines = data.decode('utf-8').split('\n')
    if lines[-1] == '':
        lines.pop()
    cols = [line.removesuffix('\r').split('\t') for line in lines]
    require(cols and cols[0][0] == 'hash' and len(set(cols[0])) == len(cols[0]), 'results header')
    header = cols[0]
    require({'hash', 'stage', 'status', 'spv_bytes', 'resources'} <= set(header), 'results columns')
    rows = {}
    for values in cols[1:]:
        require(len(values) == len(header), 'malformed results row')
        row = dict(zip(header, values))
        h = row['hash']
        require(h in inputs and h not in rows, 'unexpected/duplicate results hash')
        # Upstream's second attempt disables expression propagation. Its successful
        # output still requires the same anchored product and validation checks.
        require(row['stage'] == inputs[h][2] and row['status'] in ('ok', 'ok-retry'),
                'results stage/status mismatch')
        require(re.fullmatch('[0-9]+', row['spv_bytes']) is not None, 'results product size')
        rows[h] = row
    require(set(rows) == set(inputs), 'missing results row')
    return rows


def stage_model(data, stage):
    require(len(data) >= 20 and len(data) % 4 == 0, 'SPIR-V length')
    words = struct.unpack('<' + 'I' * (len(data) // 4), data)
    require(words[0] == 0x07230203, 'SPIR-V magic')
    pos, models = 5, []
    while pos < len(words):
        n, op = words[pos] >> 16, words[pos] & 65535
        require(n > 0 and pos + n <= len(words), 'SPIR-V instruction extent')
        if op == 15:
            require(n >= 4, 'SPIR-V entry point extent')
            models.append(words[pos + 1])
        pos += n
    require(models == [0 if stage == 'vertex' else 4], 'SPIR-V selected stage mismatch')


def accepted_products(receipt_path, receipt_hash, index_path, translation_root):
    receipt = anchored(receipt_path, receipt_hash)
    require(receipt['state'] == 'translated-validated' and receipt['exit_code'] == 0,
            'translation not accepted')
    index = anchored(index_path, receipt['result_index_sha256'])
    require({'translation.json', 'products/results.tsv'} <= set(index['files']),
            'missing accepted metadata identity')
    for name, identity in index['files'].items():
        require(name in {'translation.json', 'products/results.tsv', 'products/summary.txt',
                         'products/batch.log', 'products/receipt.json'} or
                re.fullmatch(r'products/[0-9a-f]{16}\.spv', name), 'result index path')
        data = read(translation_root / name, MAX)
        require(len(data) == identity['bytes'] and sha256(data) == identity['sha256'],
                'accepted result identity mismatch')
    translation = load(translation_root / 'translation.json')
    require(translation['status'] == 'translated-validated', 'translation status')
    product_names = {'products/' + h + '.spv' for h in translation['products']}
    require(product_names == {name for name in index['files'] if name.endswith('.spv')} ==
            set(receipt['products']), 'accepted product identifiers')
    return translation, index, receipt


def check(args):
    inputs, manifest_hash = selected_inputs(args.handoff, args.handoff_index_sha256)
    translation, index, receipt = accepted_products(args.accepted_receipt,
        args.accepted_receipt_sha256, args.result_index, args.translation_root)
    require(translation['input_manifest_sha256'] == manifest_hash and
            set(translation['products']) == set(inputs), 'translation input identifiers')
    handoff_index = anchored(args.handoff / 'index.json', args.handoff_index_sha256)
    if handoff_index['schema'] == 2:
        require(translation.get('schema') == 2 and translation.get('mode') == 'bulk-graphics' and
                translation.get('input_index_sha256') == args.handoff_index_sha256,
                'explicit bulk translation receipt required')
    cache = batch.inventory.no_symlinks(args.data_root / 'spirv')
    tsvpath = cache / 'results.tsv'
    tsv = read(tsvpath, MAX)
    require(sha256(tsv) == index['files']['products/results.tsv']['sha256'], 'cache results identity')
    rows = result_rows(tsv, inputs)
    snapshots = {tsvpath: sha256(tsv)}
    source = batch.inventory.no_symlinks(args.native_source / 'runtime/src/nvn')
    source_hashes = {name: sha256(read(source / name, MAX)) for name in SOURCES}
    records = []
    with tempfile.TemporaryDirectory(prefix='shader-handoff-') as directory:
        work = Path(directory)
        adapter, exe = work / 'adapter.cpp', work / 'probe'
        adapter.write_text(HARNESS)
        command = [args.cxx, '-std=c++17', '-DNX_SHADERS_STANDALONE', '-I', str(source),
                   str(adapter), str(source / 'nvn_shaders.cpp'),
                   str(source / 'nvn_spirv_reflect.cpp'), '-o', str(exe)]
        compiled = subprocess.run(command, capture_output=True, timeout=90)
        require(compiled.returncode == 0, 'standalone production parser compilation failed')
        for h, (code, ctrl, stage) in inputs.items():
            path = cache / (h + '.spv')
            data = read(path, MAX)
            product = translation['products'][h]
            identity = index['files']['products/' + h + '.spv']
            require(sha256(data) == product['sha256'] == identity['sha256'] ==
                    receipt['products']['products/' + h + '.spv']['sha256'] and
                    len(data) == product['size'] == identity['bytes'] == int(rows[h]['spv_bytes']),
                    'cache product identity/size mismatch')
            require(product['stage'] == ('pixel' if stage == 'fragment' else stage) and
                    product['validation_exit'] == 0, 'accepted product stage/validation')
            stage_model(data, stage)
            snapshots[path] = sha256(data)
            for p in (code, ctrl):
                snapshots[p] = sha256(read(p, MAX))
            run = subprocess.run([str(exe), str(code), str(ctrl), str(path), str(tsvpath), h, stage],
                                 capture_output=True, text=True, timeout=15)
            require(run.returncode == 0, 'production parser rejected selected shader (exit %d)' % run.returncode)
            fields = run.stdout.rstrip('\n').split('\t')
            require(len(fields) == 7 and fields[:2] == [h, stage] and int(fields[2]) == len(inputs),
                    'production probe output mismatch')
            # Production apply_harness is deliberately permissive about some named
            # bindings. Require the metadata to describe the resulting reflection too.
            require(sorted(fields[6].split()) == sorted(rows[h]['resources'].split()),
                    'metadata/reflection description mismatch')
            records.append(dict(hash=h, stage=stage, bytes=len(data), sha256=sha256(data),
                                bindings=int(fields[3]), inputs=int(fields[4]), outputs=int(fields[5]),
                                production_parser_exit=run.returncode))
    selected_inputs(args.handoff, args.handoff_index_sha256)
    accepted_products(args.accepted_receipt, args.accepted_receipt_sha256,
                      args.result_index, args.translation_root)
    for path, digest in snapshots.items():
        require(sha256(read(path, MAX)) == digest, 'input changed during preflight')
    require(source_hashes == {name: sha256(read(source / name, MAX)) for name in SOURCES},
            'production source changed during preflight')
    return dict(schema=1, at=datetime.now(timezone.utc).isoformat(), status='selected-preflight-passed',
                checker_sha256=sha256(read(Path(__file__), MAX)),
                native_source=str(args.native_source.absolute()),
                handoff=str(args.handoff.absolute()),
                nx_data_root=str(args.data_root.absolute()), counts=dict(Counter(r['stage'] for r in records)),
                products=records, source_sha256=source_hashes, adapter_sha256=sha256(HARNESS.encode()),
                accepted_receipt_sha256=args.accepted_receipt_sha256,
                result_index_sha256=receipt['result_index_sha256'],
                accepted_files_checked=len(index['files']),
                handoff_index_sha256=args.handoff_index_sha256, results_sha256=sha256(tsv),
                standalone_compile_exit=compiled.returncode, runtime_consumption='unmeasured',
                linked_pipeline='unproven', frame='unverified', gameplay='unverified',
                total_shader_coverage='unknown',
                limitations=['Selected offline code/control bytes only; live upload identity unobserved.',
                             'Production standalone parser/reflection executed; shader_for cache I/O and guest not executed.',
                             'Historical accepted spirv-val identities checked; validator not rerun.'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('data-root', 'handoff', 'native-source', 'accepted-receipt', 'result-index', 'translation-root'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('accepted-receipt-sha256', 'handoff-index-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--cxx', default='c++')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(check(args), indent=2))
        return 0
    except batch.inventory.Invalid as exc:
        # These diagnostics are fixed messages from the original bounded checker.
        print('shader handoff preflight rejected: ' + str(exc), file=sys.stderr)
        return 1
    except (ValueError, OSError, KeyError, TypeError, IndexError, subprocess.SubprocessError):
        print('shader handoff preflight rejected: input/schema/tool failure', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
