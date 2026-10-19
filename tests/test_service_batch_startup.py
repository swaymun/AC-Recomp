"""Offline supervisor acceptance: real temporary Git repositories and processes."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import service_batch_startup as batch


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL, text=True).strip()

    def repository(self):
        self.git('init', '-b', 'main')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.root / '.gitignore').write_text('.local/\n')
        self.git('add', '.gitignore')
        self.git('commit', '-m', 'base')
        return self.git('rev-parse', 'HEAD')

    def review_fixture(self):
        base = self.repository()
        (self.root / 'overlay.patch').write_text('original fixture patch\n')
        self.git('add', 'overlay.patch')
        self.git('commit', '-m', 'overlay')
        head = self.git('rev-parse', 'HEAD')
        store = self.root / '.local/store'
        (store / 'reports').mkdir(parents=True)
        identity = batch.patch_identity(self.root, base, head)
        row = dict(id='FIXTURE', state='landed', head=head, review_run_id='review', run_id='producer',
                   patch=identity, base=base, files='overlay.patch')
        with (store / 'units.tsv').open('w') as f:
            w = csv.DictWriter(f, fieldnames=list(row), delimiter='\t')
            w.writeheader()
            w.writerow(row)
        review = dict(kind='review', verdict='pass', model='gpt-6-astra', effort='medium', head=head,
                      producer_run='producer', patch=identity, report=dict(unit='FIXTURE', head=head, patch=identity, verdict='pass'))
        (store / 'reports/review.review.json').write_text(json.dumps(review))
        return store, head, review

    def test_exact_head_review_git_ancestry_and_drift(self):
        store, head, review = self.review_fixture()
        self.assertEqual(batch.reviewed(self.root, store, {'FIXTURE': (head, head)})['FIXTURE']['landed'], head)
        (self.root / 'overlay.patch').write_text('tampered\n')
        with self.assertRaisesRegex(ValueError, 'drift'):
            batch.reviewed(self.root, store, {'FIXTURE': (head, head)})

    def preparation_fixture(self):
        store, head, review = self.review_fixture()
        base = self.git('rev-parse', head + '^')
        self.git('checkout', base, '--', '.gitignore')
        (self.root / 'tools').mkdir()
        (self.root / 'tools/prepare_runtime.py').write_text('original preparation\n')
        (self.root / 'support.txt').write_text('fixed support\n')
        self.git('add', 'tools', 'support.txt')
        self.git('commit', '-m', 'preparation baseline')
        base = self.git('rev-parse', 'HEAD')
        (self.root / 'tools/prepare_runtime.py').write_text('reviewed preparation\n')
        self.git('add', 'tools/prepare_runtime.py')
        self.git('commit', '-m', 'reviewed preparation')
        head = self.git('rev-parse', 'HEAD')
        patch = batch.patch_identity(self.root, base, head)
        row = dict(id='FIXTURE', state='landed', head=head, review_run_id='review', run_id='producer',
                   patch=patch, base=self.git('rev-parse', base + '^'), files='tools/prepare_runtime.py')
        with (store / 'units.tsv').open('w') as f:
            w = csv.DictWriter(f, fieldnames=list(row), delimiter='\t')
            w.writeheader()
            w.writerow(row)
        review.update(head=head, patch=patch, report=dict(unit='FIXTURE', head=head, patch=patch, verdict='pass'))
        (store / 'reports/review.review.json').write_text(json.dumps(review))
        for name, value in dict(BASE=base, SUPPORT=['tools/prepare_runtime.py', 'support.txt'], PATCHES=[],
                                PREPARATION_DEPENDENCY={'FIXTURE': (head, head)},
                                PREPARATION_REVIEW_BASES={'FIXTURE': base}).items():
            patcher = mock.patch.object(batch, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return store, head, review

    def test_preparation_accepts_exact_reviewed_identity(self):
        store, head, review = self.preparation_fixture()
        result = batch.shared_preparation(self.root, store)
        self.assertEqual(result['review']['FIXTURE']['landed'], head)
        self.assertEqual(result['tools/prepare_runtime.py'], batch.digest(self.root / 'tools/prepare_runtime.py'))

    def test_preparation_rejects_unreviewed_drift(self):
        store, head, review = self.preparation_fixture()
        (self.root / 'support.txt').write_text('unknown change\n')
        self.git('add', 'support.txt')
        self.git('commit', '-m', 'unreviewed support')
        with self.assertRaisesRegex(ValueError, 'base drift'):
            batch.shared_preparation(self.root, store)

    def test_preparation_rejects_wrong_content(self):
        store, head, review = self.preparation_fixture()
        (self.root / 'tools/prepare_runtime.py').write_text('unknown preparation\n')
        self.git('add', 'tools/prepare_runtime.py')
        self.git('commit', '-m', 'unreviewed preparation')
        with self.assertRaisesRegex(ValueError, 'file drift'):
            batch.shared_preparation(self.root, store)

    def test_preparation_rejects_altered_review(self):
        store, head, review = self.preparation_fixture()
        review['patch'] = '0' * 64
        (store / 'reports/review.review.json').write_text(json.dumps(review))
        with self.assertRaisesRegex(ValueError, 'review'):
            batch.shared_preparation(self.root, store)

    def test_preparation_rejects_missing_main_and_worker_ancestry(self):
        store, head, review = self.preparation_fixture()
        self.git('checkout', '--detach', head)
        self.git('branch', '-f', 'main', head + '^')
        with self.assertRaises(subprocess.CalledProcessError):
            batch.shared_preparation(self.root, store)
        self.git('branch', '-f', 'main', head)
        self.git('checkout', '--detach', head + '^')
        # Keep the exact reviewed bytes, while the reviewed commit is absent
        # from worker ancestry: content alone must never grant acceptance.
        self.git('checkout', head, '--', 'tools/prepare_runtime.py')
        with self.assertRaises(subprocess.CalledProcessError):
            batch.shared_preparation(self.root, store)

    def successor_fixture(self):
        store, head, review = self.preparation_fixture()
        # Expand the historical review with a non-consumed iOS patch and doc.
        (self.root / 'ios.patch').write_text('first iOS patch\n')
        (self.root / 'ios.md').write_text('first iOS result\n')
        self.git('add', 'ios.patch', 'ios.md')
        self.git('commit', '-m', 'original review closeout')
        head = self.git('rev-parse', 'HEAD')
        with (store / 'units.tsv').open() as f:
            original = next(csv.DictReader(f, delimiter='\t'))
        original.update(head=head, files='tools/prepare_runtime.py,ios.patch,ios.md', deps='')
        original['base'] = batch.BASE
        original['patch'] = batch.patch_identity(self.root, batch.BASE, head)
        review.update(head=head, patch=original['patch'],
                      report=dict(unit='FIXTURE', head=head, patch=original['patch'], verdict='pass'))
        (store / 'reports/review.review.json').write_text(json.dumps(review))
        batch.PREPARATION_DEPENDENCY = {'FIXTURE': (head, head)}
        (self.root / 'ios.patch').write_text('reviewed iOS successor patch\n')
        (self.root / 'ios.md').write_text('reviewed iOS successor result\n')
        self.git('add', 'ios.patch', 'ios.md')
        self.git('commit', '-m', 'reviewed iOS successor')
        successor = self.git('rev-parse', 'HEAD')
        row = dict(original, id='SUCCESSOR', head=successor, base=head, deps='FIXTURE',
                   files='ios.patch,ios.md', review_run_id='successor-review', run_id='successor-producer',
                   patch=batch.patch_identity(self.root, head, successor))
        receipt = dict(review, head=successor, producer_run=row['run_id'], patch=row['patch'],
                       report=dict(unit='SUCCESSOR', head=successor, patch=row['patch'], verdict='pass'))
        (store / 'reports/successor-review.review.json').write_text(json.dumps(receipt))
        self.write_rows(store, [original, row])
        return store, original, row, receipt

    def write_rows(self, store, rows):
        with (store / 'units.tsv').open('w') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter='\t')
            writer.writeheader()
            writer.writerows(rows)

    def test_reviewed_unrelated_successor_preserves_consumed_bytes(self):
        store, original, successor, receipt = self.successor_fixture()
        result = batch.shared_preparation(self.root, store)['review']
        self.assertEqual(result['FIXTURE']['supersessions'],
                         {'ios.patch': 'SUCCESSOR', 'ios.md': 'SUCCESSOR'})
        self.assertEqual(result['SUCCESSOR']['patch'], successor['patch'])
        self.assertEqual(result['FIXTURE']['files']['tools/prepare_runtime.py'],
                         batch.digest(self.root / 'tools/prepare_runtime.py')['sha256'])
        # Services retain the existing all-current-files requirement.
        with self.assertRaisesRegex(ValueError, 'file drift'):
            batch.reviewed(self.root, store, batch.PREPARATION_DEPENDENCY, batch.PREPARATION_REVIEW_BASES)

    def test_successor_cannot_authorize_consumed_helper_or_base_patch_tamper(self):
        store, original, successor, receipt = self.successor_fixture()
        for path in ('tools/prepare_runtime.py', 'support.txt'):
            saved = (self.root / path).read_bytes()
            (self.root / path).write_text('unreviewed consumed bytes\n')
            with self.assertRaises(ValueError):
                batch.shared_preparation(self.root, store)
            (self.root / path).write_bytes(saved)
        # An actual service overlay must also retain its authenticated bytes.
        (self.root / 'ios.patch').write_text('tampered service overlay\n')
        with self.assertRaisesRegex(ValueError, 'file drift'):
            batch.reviewed(self.root, store, {'SUCCESSOR': (successor['head'], successor['head'])})

    def test_successor_review_identity_failures(self):
        store, original, successor, receipt = self.successor_fixture()
        path = store / 'reports/successor-review.review.json'
        for key, bad in [('verdict', 'fail'), ('head', original['head']), ('patch', '0' * 64),
                         ('producer_run', 'wrong-producer'), ('model', 'gpt-6.1-sol'), ('effort', 'low')]:
            with self.subTest(key=key):
                path.write_text(json.dumps(dict(receipt, **{key: bad})))
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    batch.shared_preparation(self.root, store)
        path.unlink()
        with self.assertRaises(ValueError):
            batch.shared_preparation(self.root, store)

    def test_successor_requires_explicit_scope_landing_and_patch(self):
        store, original, successor, receipt = self.successor_fixture()
        for key, bad in [('deps', ''), ('files', 'ios.md'), ('state', 'reviewed'),
                         ('head', original['head']), ('patch', '0' * 64)]:
            with self.subTest(key=key):
                self.write_rows(store, [original, dict(successor, **{key: bad})])
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    batch.shared_preparation(self.root, store)
        self.write_rows(store, [original, successor])
        (self.root / 'ios.md').write_text('unreviewed follow-up\n')
        self.git('add', 'ios.md')
        self.git('commit', '-m', 'unreviewed follow-up')
        with self.assertRaisesRegex(ValueError, 'successor'):
            batch.shared_preparation(self.root, store)

    def test_successor_both_ancestries_required(self):
        store, original, successor, receipt = self.successor_fixture()
        self.git('checkout', '--detach', successor['head'])
        self.git('branch', '-f', 'main', original['head'])
        with self.assertRaises(subprocess.CalledProcessError):
            batch.shared_preparation(self.root, store)
        self.git('branch', '-f', 'main', successor['head'])
        self.git('checkout', '--detach', original['head'])
        self.git('checkout', successor['head'], '--', 'ios.patch', 'ios.md')
        with self.assertRaises(subprocess.CalledProcessError):
            batch.shared_preparation(self.root, store)

    def test_reviewed_successor_chain(self):
        store, original, successor, receipt = self.successor_fixture()
        base = successor['head']
        (self.root / 'ios.md').write_text('independently reviewed final doc\n')
        self.git('add', 'ios.md')
        self.git('commit', '-m', 'reviewed documentation successor')
        head = self.git('rev-parse', 'HEAD')
        patch = batch.patch_identity(self.root, base, head)
        row = dict(successor, id='FINAL', head=head, base=base, deps='SUCCESSOR', files='ios.md',
                   patch=patch, review_run_id='final-review', run_id='final-producer')
        review = dict(receipt, head=head, patch=patch, producer_run='final-producer',
                      report=dict(unit='FINAL', head=head, patch=patch, verdict='pass'))
        self.write_rows(store, [original, successor, row])
        (store / 'reports/final-review.review.json').write_text(json.dumps(review))
        result = batch.shared_preparation(self.root, store)['review']
        self.assertEqual(result['SUCCESSOR']['supersessions'], {'ios.md': 'FINAL'})
        self.assertEqual(result['FINAL']['reviewed'], head)

    def test_successor_report_patch_and_scoped_landing_equality(self):
        store, original, successor, receipt = self.successor_fixture()
        bad = dict(receipt, report=dict(receipt['report'], patch='0' * 64))
        path = store / 'reports/successor-review.review.json'
        path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError, 'report mismatch'):
            batch.shared_preparation(self.root, store)
        path.write_text(json.dumps(receipt))
        # Landing at a later commit with different scoped bytes is not the
        # exact reviewed landing, even when both commits are main ancestors.
        (self.root / 'ios.patch').write_text('wrong landing bytes\n')
        self.git('add', 'ios.patch')
        self.git('commit', '-m', 'incorrect landing')
        successor['head'] = self.git('rev-parse', 'HEAD')
        self.write_rows(store, [original, successor])
        with self.assertRaisesRegex(ValueError, 'landing content mismatch'):
            batch.shared_preparation(self.root, store)

    def test_successor_must_start_from_original_reviewed_bytes(self):
        store, original, successor, receipt = self.successor_fixture()
        # Build a fully reviewed successor on top of unreviewed interim drift.
        self.git('reset', '--hard', original['head'])
        (self.root / 'ios.patch').write_text('unreviewed interim patch\n')
        self.git('add', 'ios.patch')
        self.git('commit', '-m', 'unreviewed interim')
        base = self.git('rev-parse', 'HEAD')
        (self.root / 'ios.patch').write_text('reviewed later patch\n')
        (self.root / 'ios.md').write_text('reviewed later doc\n')
        self.git('add', 'ios.patch', 'ios.md')
        self.git('commit', '-m', 'reviewed later change')
        head = self.git('rev-parse', 'HEAD')
        patch = batch.patch_identity(self.root, base, head)
        successor.update(base=base, head=head, patch=patch)
        receipt.update(head=head, patch=patch, report=dict(unit='SUCCESSOR', head=head, patch=patch, verdict='pass'))
        self.write_rows(store, [original, successor])
        (store / 'reports/successor-review.review.json').write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'baseline mismatch'):
            batch.shared_preparation(self.root, store)

    def test_consumed_patch_tamper(self):
        store, head, review = self.review_fixture()
        (self.root / 'overlay.patch').write_text('unreviewed patch mutation\n')
        self.git('add', 'overlay.patch')
        self.git('commit', '-m', 'unreviewed patch mutation')
        with self.assertRaisesRegex(ValueError, 'file drift'):
            batch.reviewed(self.root, store, {'FIXTURE': (head, head)}, consumed={'overlay.patch'})

    def test_reject_wrong_review_and_unlanded_head(self):
        store, head, review = self.review_fixture()
        review['effort'] = 'low'
        (store / 'reports/review.review.json').write_text(json.dumps(review))
        with self.assertRaisesRegex(ValueError, 'review'):
            batch.reviewed(self.root, store, {'FIXTURE': (head, head)})
        review['effort'] = 'medium'
        (store / 'reports/review.review.json').write_text(json.dumps(review))
        self.git('checkout', '--detach', head)
        self.git('branch', '-f', 'main', head + '^')
        with self.assertRaises(subprocess.CalledProcessError):
            batch.reviewed(self.root, store, {'FIXTURE': (head, head)})

    def test_multi_commit_finalized_review_pair(self):
        store, first, review = self.review_fixture()
        base = self.git('rev-parse', first + '^')
        (self.root / 'overlay.patch').write_text('reviewed formatting repair\n')
        self.git('add', 'overlay.patch')
        self.git('commit', '-m', 'repair')
        head = self.git('rev-parse', 'HEAD')
        patch = batch.patch_identity(self.root, base, head)
        with (store / 'units.tsv').open() as f:
            rows = list(csv.DictReader(f, delimiter='\t'))
        rows[0].update(head=head, patch=patch)
        with (store / 'units.tsv').open('w') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter='\t')
            w.writeheader()
            w.writerows(rows)
        (store / 'reports/review.review.json').unlink()
        (store / 'runs').mkdir()
        meta = dict(run_id='review', kind='review', producer_run='producer', head=head,
                    patch=patch, model='gpt-6-astra', effort='medium')
        final = dict(run_id='review', kind='review', unit='FIXTURE', head=head, patch=patch, verdict='pass')
        (store / 'runs/review.json').write_text(json.dumps(meta))
        (store / 'reports/review.final.json').write_text(json.dumps(final))
        result = batch.reviewed(self.root, store, {'FIXTURE': (head, head)})
        self.assertEqual(result['FIXTURE']['review_base'], base)
        final['head'] = first
        (store / 'reports/review.final.json').write_text(json.dumps(final))
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            batch.reviewed(self.root, store, {'FIXTURE': (head, head)})

    def test_missing_overlay_and_review_are_blocked(self):
        store, head, review = self.review_fixture()
        (self.root / 'overlay.patch').unlink()
        with self.assertRaises(FileNotFoundError):
            batch.reviewed(self.root, store, {'FIXTURE': (head, head)})
        self.git('checkout', '--', 'overlay.patch')
        (store / 'reports/review.review.json').unlink()
        with self.assertRaises(ValueError):
            batch.reviewed(self.root, store, {'FIXTURE': (head, head)})

    def test_ordered_composition_existing_interface(self):
        pin = self.repository()
        reference = self.root
        # Create a tiny real pinned reference and patches applied in dependency order.
        (reference / 'base.txt').write_text('base\n')
        self.git('add', 'base.txt')
        self.git('commit', '-m', 'reference')
        pin = self.git('rev-parse', 'HEAD')
        patches = []
        for index, (old, new) in enumerate((('base', 'service1'), ('service1', 'service2'))):
            patch = reference / '.local' / f'{index}.patch'
            patch.parent.mkdir(exist_ok=True)
            patch.write_text(f'diff --git a/base.txt b/base.txt\n--- a/base.txt\n+++ b/base.txt\n@@ -1 +1 @@\n-{old}\n+{new}\n')
            patches.append(patch)
        source = reference / '.local/composed'
        hashes = batch.prepare.prepare_source(reference, source, patches, pin=pin)
        self.assertEqual((source / 'base.txt').read_text(), 'service2\n')
        self.assertEqual(hashes['base.txt'], hashlib.sha256(b'service2\n').hexdigest())
        with self.assertRaises(subprocess.CalledProcessError):
            batch.prepare.prepare_source(reference, reference / '.local/wrong', list(reversed(patches)), pin=pin)

    def cumulative_fixture(self):
        self.repository()
        store = self.root / '.local/store'
        (store / 'reports').mkdir(parents=True)
        patchdir = self.root / 'runtime/patches'
        patchdir.mkdir(parents=True)
        (self.root / 'state.txt').write_text('stage0\n')
        self.git('add', 'state.txt')
        self.git('commit', '-m', 'synthetic source')
        pin = self.git('rev-parse', 'HEAD')
        rows, dependencies = [], {}
        for i, name in enumerate(batch.PATCHES):
            base = self.git('rev-parse', 'HEAD')
            patch = ('diff --git a/state.txt b/state.txt\n--- a/state.txt\n+++ b/state.txt\n'
                     f'@@ -1 +1 @@\n-stage{i}\n+stage{i + 1}\n')
            (patchdir / name).write_text(patch)
            self.git('add', 'runtime')
            self.git('commit', '-m', f'independent overlay {i}')
            head = self.git('rev-parse', 'HEAD')
            identity = batch.patch_identity(self.root, base, head)
            unit = 'FIXTURE' if i == 0 else f'OVERLAY-{i}'
            reviewer = 'review' if i == 0 else f'review-{i}'
            producer = f'producer-{i}'
            rows.append(dict(id=unit, state='landed', head=head, review_run_id=reviewer,
                             run_id=producer, patch=identity, base=base,
                             files='runtime/patches/' + name))
            review = dict(kind='review', verdict='pass', model='gpt-6-astra', effort='medium',
                          head=head, producer_run=producer, patch=identity,
                          report=dict(unit=unit, head=head, patch=identity, verdict='pass'))
            (store / f'reports/{reviewer}.review.json').write_text(json.dumps(review))
            dependencies[unit] = (head, head)
        self.write_rows(store, rows)
        for name, value in [('DEPENDENCIES', dependencies), ('SERVICE_REVIEW_BASES', {})]:
            patcher = mock.patch.object(batch, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(batch, 'shared_preparation', return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cumulative_pin = pin
        return store

    def test_eleven_independently_reviewed_overlays_compose_in_order(self):
        store = self.cumulative_fixture()
        patches, reviews, _ = batch.cumulative_patches(self.root, store)
        self.assertEqual(len(reviews), 11)
        out = self.root / '.local/composed'
        reference = self.root / '.local/reference'
        subprocess.run(['git', 'clone', '--no-hardlinks', str(self.root), str(reference)],
                       check=True, capture_output=True)
        subprocess.run(['git', '-C', str(reference), 'checkout', '--detach', self.cumulative_pin],
                       check=True, capture_output=True)
        receipt = batch.prepare.prepare_source(reference, out, patches, pin=self.cumulative_pin)
        self.assertEqual((out / 'state.txt').read_text(), 'stage11\n')
        self.assertEqual(receipt['state.txt'], hashlib.sha256(b'stage11\n').hexdigest())
        result = batch.run_stage([sys.executable, '-c',
                                 'from pathlib import Path; print(Path("state.txt").read_text(), end="")'],
                                self.root / 'composition.log', 4, cwd=out)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['log']['sha256'], hashlib.sha256(b'stage11\n').hexdigest())

    def test_cumulative_order_and_authenticated_overlay_identities(self):
        store = self.cumulative_fixture()
        patches, reviews, preparation = batch.cumulative_patches(self.root, store)
        self.assertEqual([p.name for p in patches], batch.PATCHES)
        self.assertEqual(len(patches), 11)
        self.assertIn('FIXTURE', reviews)
        for bad in [batch.PATCHES[:-1], batch.PATCHES + [batch.PATCHES[-1]],
                    list(reversed(batch.PATCHES)), batch.PATCHES[:-1] + ['unknown.patch']]:
            with self.subTest(order=bad), self.assertRaisesRegex(ValueError, 'order'):
                batch.cumulative_patches(self.root, store, bad)
        patches[-1].write_text('committed but unreviewed controller drift\n')
        self.git('add', 'runtime'); self.git('commit', '-m', 'unreviewed')
        with self.assertRaisesRegex(ValueError, 'drift'):
            batch.cumulative_patches(self.root, store)

    def test_cumulative_review_failure_is_not_replaced_by_hashes(self):
        store = self.cumulative_fixture()
        path = store / 'reports/review.review.json'
        review = json.loads(path.read_text())
        path.write_text(json.dumps(dict(review, verdict='fail')))
        with self.assertRaisesRegex(ValueError, 'review'):
            batch.cumulative_patches(self.root, store)

    def test_parser_fragments_preserve_exact_reviewed_source(self):
        source = (batch.ROOT / 'tools/service_batch_startup.py').read_text()
        exact = next(iter(batch.PARSER_DEPENDENCY.values()))[1]
        original = subprocess.check_output(['git', '-C', str(batch.ROOT), 'show',
                                            exact + ':tools/service_batch_startup.py']).decode()
        self.assertEqual(batch.parser_fragments(source), batch.parser_fragments(original))
        self.assertNotEqual(batch.parser_fragments(source.replace('16 * 1024 * 1024', '8 * 1024 * 1024')),
                            batch.parser_fragments(original))
        self.assertNotEqual(batch.parser_fragments(source.replace("data = stream.read(LIMIT)", "data = stream.read(LIMIT - 1)")),
                            batch.parser_fragments(original))

    def test_historical_authentication_still_checks_review_scope_and_landing(self):
        store, head, review = self.review_fixture()
        (self.root / 'overlay.patch').write_text('integration changes scoped supervisor\n')
        result = batch.reviewed(self.root, store, {'FIXTURE': (head, head)}, historical_only=True)
        self.assertEqual(result['FIXTURE']['reviewed'], head)
        review['head'] = '0' * 40
        (store / 'reports/review.review.json').write_text(json.dumps(review))
        with self.assertRaisesRegex(ValueError, 'review'):
            batch.reviewed(self.root, store, {'FIXTURE': (head, head)}, historical_only=True)

    def test_object_identities_require_fresh_unique_in_build_objects(self):
        build = self.root / 'build'; build.mkdir()
        obj = build / 'a.o'; obj.write_bytes(b'fixture compiled object')
        commands = [dict(directory=str(build), arguments=['cc', '-c', 'a.cpp', '-o', 'a.o'])]
        self.assertEqual(batch.object_identities(commands, build), {'a.o': batch.digest(obj)})
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            batch.object_identities(commands * 2, build)
        commands[0]['arguments'][-1] = '../outside.o'
        with self.assertRaisesRegex(ValueError, 'outside'):
            batch.object_identities(commands, build)

    def test_process_success_failure_and_shell_rejection(self):
        for code in (0, 7):
            result = batch.run_stage([sys.executable, '-c', f'print("fixture"); raise SystemExit({code})'],
                                     self.root / f'process{code}.log', 4)
            self.assertEqual(result['exit_code'], code)
            self.assertEqual(result['log']['sha256'], hashlib.sha256(b'fixture\n').hexdigest())
            self.assertFalse(result['timeout'])
        with self.assertRaisesRegex(ValueError, 'argv'):
            batch.run_stage('echo unsafe', self.root / 'unsafe.log', 1)

    def test_timeout_cleans_separate_descendant_group(self):
        child_pid = self.root / 'pid'
        script = ('import subprocess,sys,time; '
                  'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],start_new_session=True); '
                  f'open({str(child_pid)!r},"w").write(str(p.pid)); time.sleep(30)')
        result = batch.run_stage([sys.executable, '-c', script], self.root / 'timeout.log', 0.7)
        self.assertTrue(result['timeout'])
        pid = int(child_pid.read_text())
        status = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
        self.assertTrue(not status.stdout.strip() or status.stdout.strip().startswith('Z'))
        self.assertIn(pid, result['cleanup_groups'])
        self.assertLess(result['elapsed_seconds'], 4)

    def test_reused_pid_does_not_authorize_group_signal(self):
        owned = {111: (111, 'original birth'), 222: (222, 'still owned')}
        with mock.patch.object(batch, 'process_table', return_value=[
                (111, 1, 111, 'replacement birth'), (222, 1, 222, 'still owned')]):
            self.assertEqual(batch.live_owned_groups(owned), {222})

    def test_output_bound(self):
        with mock.patch.object(batch, 'LIMIT', 128):
            result = batch.run_stage([sys.executable, '-c', 'print("x"*10000)'], self.root / 'noisy.log', 3)
        self.assertTrue(result['output_limit'])
        self.assertEqual((self.root / 'noisy.log').stat().st_size, 128)

    def test_strict_every_translation_unit(self):
        gen = self.root / 'gen'
        commands = [{'file': str(gen / n / 'a.cpp'), 'arguments': ['clang++', '-DNX_APPLE_HIGH_MEMORY=1', '-DNX_ASTRAL_STRICT=1']}
                    for n in ('main', 'sdk')]
        batch.check_flags(commands, gen)
        commands[1]['arguments'].append('-DNX_ASTRAL_STRICT=0')
        with self.assertRaises(ValueError):
            batch.check_flags(commands, gen)

    def test_controls_stale_late_auth_drift_stop(self):
        store = self.root
        targets = ['macos-arm64', 'windows-x86_64', 'linux-x86_64', 'ios-ipados-simulator-arm64']
        (store / 'AUTHORIZATION.md').write_text('fixture authorization')
        (store / 'RUN_OBJECTIVE.md').write_text('both iPhone and iPad remain required')
        (store / 'config.json').write_text(json.dumps(dict(budget_usd=20, max_workers=3)))
        lead = dict(mode='game', targets=targets, task_id='fixture', deadline='2026-10-18T21:00:00Z',
                    dispatch_stop_at='2026-10-18T20:30:00Z', owner_approval=dict(approved=True, targets=targets,
                    task_id='fixture', deadline='2026-10-18T21:00:00Z', authorization_sha256=batch.digest(store / 'AUTHORIZATION.md')['sha256']))
        (store / 'lead-config.json').write_text(json.dumps(lead))
        batch.controls(store, datetime(2026, 10, 18, 16, tzinfo=timezone.utc))
        with mock.patch.dict(os.environ, ACS_BUDGET_CAP_USD='20'):
            batch.controls(store, datetime(2026, 10, 18, 16, tzinfo=timezone.utc))
        with mock.patch.dict(os.environ, ACS_BUDGET_CAP_USD='15'), self.assertRaisesRegex(ValueError, 'budget'):
            batch.controls(store, datetime(2026, 10, 18, 16, tzinfo=timezone.utc))
        for date in (datetime(2026, 10, 18, 20, 30, tzinfo=timezone.utc), datetime(2026, 10, 19, 16, tzinfo=timezone.utc)):
            with self.assertRaises(ValueError):
                batch.controls(store, date)
        (store / 'STOP').touch()
        with self.assertRaisesRegex(ValueError, 'stopped'):
            batch.controls(store, datetime(2026, 10, 18, 16, tzinfo=timezone.utc))
        (store / 'STOP').unlink()
        (store / 'AUTHORIZATION.md').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'authorization'):
            batch.controls(store, datetime(2026, 10, 18, 16, tzinfo=timezone.utc))

    def test_malformed_controls_fail_closed(self):
        store = self.root
        (store / 'AUTHORIZATION.md').write_text('fixture')
        (store / 'lead-config.json').write_text('{}')
        for text in ('{', '[]', '{}', '{"budget_usd":"20","max_workers":3}'):
            with self.subTest(text=text):
                (store / 'config.json').write_text(text)
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    batch.controls(store, datetime(2026, 10, 18, 16, tzinfo=timezone.utc))

    def test_unsafe_private_output(self):
        self.repository()
        with self.assertRaises(ValueError):
            batch.prepare.private(self.root, self.root / 'public')
        private = self.root / '.local'
        private.mkdir()
        (private / 'link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            batch.prepare.private(self.root, private / 'link/out')

    def test_sanitized_boundary_no_guest_payload(self):
        log = self.root / 'trace'
        log.write_text('guest-secret arbitrary payload\nipc: ISelfController cmd 14\n'
                       'logger: accepted packet bytes=208 flags=7 secret\n'
                       'FATAL: strict IPC missing command: service=ISelfController command=15\n')
        result = batch.safe_observations([log])
        self.assertEqual(result['first_unsupported_boundary']['command'], 15)
        self.assertNotIn('secret', json.dumps(result))
        self.assertFalse(result['gameplay_verified'])

    def test_missing_service_and_command_first_boundary_order(self):
        service = 'FATAL: strict IPC missing service: hid'
        command = 'FATAL: strict IPC missing command: service=ISession command=0'
        log = self.root / 'trace'
        other = self.root / 'startup'
        for first, second, kind in ((service, command, 'strict IPC missing service'),
                                    (command, service, 'strict IPC missing command')):
            log.write_text(first + '\n' + second + '\n')
            other.write_text(second + '\n')
            result = batch.safe_observations([log, other])
            self.assertEqual(result['first_unsupported_boundary']['kind'], kind)
            self.assertEqual('command' in result['first_unsupported_boundary'], first == command)
            # Caller-supplied log order and then physical line order are authoritative.
            result = batch.safe_observations([other, log])
            self.assertEqual(result['first_unsupported_boundary']['kind'],
                'strict IPC missing command' if first == service else 'strict IPC missing service')

    def test_malformed_boundaries_and_guest_payload_rejected(self):
        log = self.root / 'trace'
        service = 'FATAL: strict IPC missing service: '
        command = 'FATAL: strict IPC missing command: service='
        invalid = [service, service + 'hid secret', service + 'hid/secret', service + '9hid',
                   service + 'hid\x00', service + 'a' * 82, 'guest ' + service + 'hid',
                   service + 'hid command=1', service + 'hid\x1c' + service + 'hid',
                   command + 'ISession command=-1', command + 'ISession command=1secret',
                   command + 'ISession command=12345678901', command + 'ISession command=1 secret',
                   command + 'ISession command=1 ' + service + 'hid']
        for line in invalid:
            with self.subTest(line=repr(line)):
                log.write_text(line + '\n')
                result = batch.safe_observations([log])
                self.assertIsNone(result['first_unsupported_boundary'])
                self.assertNotIn('secret', json.dumps(result))
        log.write_text('private guest payload\n' + service + 'hid:sys\nprivate tail')
        result = batch.safe_observations([log])
        self.assertEqual(result['first_unsupported_boundary'],
                         {'kind': 'strict IPC missing service', 'service': 'hid:sys'})
        self.assertNotIn('private', json.dumps(result))
        self.assertFalse(result['gameplay_verified'])

    def test_limit_truncation_never_accepts_partial_physical_line(self):
        log = self.root / 'trace'
        lines = (b'FATAL: strict IPC missing service: hid',
                 b'FATAL: strict IPC missing command: service=ISession command=0')
        # Exercise the production limit as well as a small bound. Both a
        # malformed suffix and the newline itself can lie beyond the read cap.
        for limit in (128, batch.LIMIT):
            for line in lines:
                for suffix in (b' arbitrary guest payload\n', b'\n'):
                    with self.subTest(limit=limit, line=line, suffix=suffix):
                        log.write_bytes(b'x' * (limit - len(line) - 1) + b'\n' + line + suffix)
                        with mock.patch.object(batch, 'LIMIT', limit):
                            result = batch.safe_observations([log])
                        self.assertIsNone(result['first_unsupported_boundary'])
                        self.assertNotIn('guest payload', json.dumps(result))

    def test_limit_complete_newline_and_true_eof_are_distinct(self):
        log = self.root / 'trace'
        lines = (b'FATAL: strict IPC missing service: hid',
                 b'FATAL: strict IPC missing command: service=ISession command=0')
        for line in lines:
            for limit in (len(line), len(line) + 1, 128):
                for newline in (False, True):
                    with self.subTest(line=line, limit=limit, newline=newline):
                        tail = line + (b'\n' if newline else b'')
                        if len(tail) > limit:
                            continue
                        complete = b'\n' * (limit - len(tail)) + tail
                        log.write_bytes(complete)
                        with mock.patch.object(batch, 'LIMIT', limit):
                            result = batch.safe_observations([log])
                        self.assertIsNotNone(result['first_unsupported_boundary'])
                        if newline:
                            # A complete line within the cap survives an unread
                            # later line; an EOF-only fragment does not.
                            log.write_bytes(complete + b'private payload')
                            with mock.patch.object(batch, 'LIMIT', limit):
                                self.assertEqual(batch.safe_observations([log]), result)

    def test_truncated_tail_preserves_boundary_and_log_order(self):
        log, other = self.root / 'trace', self.root / 'startup'
        service = b'FATAL: strict IPC missing service: hid'
        command = b'FATAL: strict IPC missing command: service=ISession command=0'
        for first, second in ((service, command), (command, service)):
            limit = len(first) + 1 + len(second)
            log.write_bytes(first + b'\n' + second + b' private payload\n')
            other.write_bytes(second)  # genuine EOF, no newline
            with mock.patch.object(batch, 'LIMIT', limit):
                single = batch.safe_observations([log])
                self.assertEqual(batch.safe_observations([log, other]), single)
                self.assertNotEqual(batch.safe_observations([other, log])['first_unsupported_boundary'],
                                    single['first_unsupported_boundary'])
                log.write_bytes(b'\n' * (limit - len(first)) + first + b' private payload\n')
                self.assertEqual(batch.safe_observations([log, other]), batch.safe_observations([other]))

    def test_observation_read_is_bounded_with_one_byte_eof_probe(self):
        import io
        limit = 128
        reads = []

        class GuardedStream(io.BytesIO):
            def read(self, size=-1):
                reads.append(size)
                self.assert_bound(size)
                return super().read(size)

            def assert_bound(self, size):
                if size < 0 or size > limit:
                    raise AssertionError('unbounded log read')

        path = mock.Mock()
        path.is_file.return_value = True
        path.open.return_value = GuardedStream(b'x' * (limit + 100))
        with mock.patch.object(batch, 'LIMIT', limit):
            result = batch.safe_observations([path])
        self.assertEqual(reads, [limit, 1])
        self.assertIsNone(result['first_unsupported_boundary'])
        self.assertEqual(result['observed_service_dispatches'], [])

    def test_fatal_fields_are_ascii_bounded_and_uint32(self):
        log = self.root / 'trace'
        command = b'FATAL: strict IPC missing command: service=ISession command='
        for selector in (b'0', b'4294967295'):
            log.write_bytes(command + selector)
            self.assertEqual(batch.safe_observations([log])['first_unsupported_boundary']['command'],
                             int(selector))
        for selector in (b'4294967296', b'9999999999', b'01', b'+1', b'1.0', b'\xff'):
            log.write_bytes(command + selector + b'\n')
            self.assertIsNone(batch.safe_observations([log])['first_unsupported_boundary'])
        for prefix in (b'FATAL: strict IPC missing service: ',
                       b'FATAL: strict IPC missing command: service='):
            suffix = b' command=1' if prefix.endswith(b'=') else b''
            log.write_bytes(prefix + b'A' * 81 + suffix + b'\n')
            self.assertIsNotNone(batch.safe_observations([log])['first_unsupported_boundary'])
            for service in (b'A' * 82, b'hid\xff', b'hid\x00', b'hid/secret'):
                log.write_bytes(prefix + service + suffix + b'\n')
                result = batch.safe_observations([log])
                self.assertIsNone(result['first_unsupported_boundary'])
                self.assertNotIn('secret', json.dumps(result))

    def test_only_lf_delimits_physical_fatal_lines(self):
        log = self.root / 'trace'
        lines = (b'FATAL: strict IPC missing service: hid',
                 b'FATAL: strict IPC missing command: service=ISession command=0')
        for line in lines:
            for separator in (b'\r', b'\v', b'\f', b'\x1c', b'\x1d', b'\x1e',
                              '\u0085'.encode(), '\u2028'.encode(), '\u2029'.encode()):
                with self.subTest(line=line, separator=separator):
                    log.write_bytes(b'private' + separator + line + b'\n')
                    self.assertIsNone(batch.safe_observations([log])['first_unsupported_boundary'])
                    log.write_bytes(line + separator + b'private\n')
                    self.assertIsNone(batch.safe_observations([log])['first_unsupported_boundary'])

    def test_unread_fatal_is_unknown_and_truncated_dispatch_is_not_exported(self):
        log = self.root / 'trace'
        log.write_bytes(b'x' * 128 + b'\nFATAL: strict IPC missing service: hid\n')
        with mock.patch.object(batch, 'LIMIT', 128):
            result = batch.safe_observations([self.root / 'absent', log])
        self.assertIsNone(result['first_unsupported_boundary'])
        self.assertEqual(result['unobserved_handlers'], 'unverified')
        partial = b'ipc: ISecret cmd 12'
        log.write_bytes(partial + b'private payload\n')
        with mock.patch.object(batch, 'LIMIT', len(partial)):
            result = batch.safe_observations([log])
        self.assertEqual(result['observed_service_dispatches'], [])


if __name__ == '__main__':
    unittest.main()
