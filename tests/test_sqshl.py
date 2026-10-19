"""Actual patch/emitter/native fixtures; required dependencies never skip."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('check_sqshl',ROOT/'tools/check_sqshl.py')
sq=importlib.util.module_from_spec(spec);spec.loader.exec_module(sq)


class SqshlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference,cls.python=sq.defaults()
        base=ROOT/'.local/cpu-sqshl-019';base.mkdir(parents=True,exist_ok=True)
        cls.out=Path(tempfile.mkdtemp(prefix='verify-',dir=base))/'measured'
        cls.report=sq.check(cls.reference,cls.python,base/'arm-contract.pdf',cls.out)
        print(f'\nPrivate SQSHL receipt: {cls.out.relative_to(ROOT)}/report.json',flush=True)

    def test_actual_emitter_bigint_native_ubsan(self):
        self.assertEqual(self.report['cases'],85200)
        self.assertEqual(self.report['native_cases'],self.report['cases'])
        self.assertEqual(self.report['ubsan_cases'],self.report['cases'])
        self.assertGreater(self.report['saturating_cases'],0)
        self.assertGreater(self.report['nonsaturating_cases'],0)
        self.assertGreater(self.report['sticky_cases'],0)

    def test_exact_patch_scope_and_required_rejections(self):
        self.assertEqual(self.report['changed_upstream'],['recomp/emit_neon.py'])
        self.assertGreater(self.report['unchanged_upstream_files'],100)
        self.assertEqual(len(self.report['rejected']),32)
        self.assertEqual(self.report['compiler_jobs'],1)

    def test_missing_required_inputs_fail_closed(self):
        for kwargs in [dict(reference=self.out/'absent'),dict(python=self.out/'absent'),
                       dict(contract=self.out/'absent'),dict(compiler='sqshl-no-such-compiler')]:
            args=dict(reference=self.reference,python=self.python,
                      contract=ROOT/'.local/cpu-sqshl-019/arm-contract.pdf',out=self.out/'never')
            args.update(kwargs)
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                sq.check(**args)

    def test_synthetic_repository_wrong_pin_and_dirty_refused(self):
        fixture=self.out.parent/'synthetic-reference';fixture.mkdir()
        sq.run(['git','init',fixture])
        (fixture/'original.txt').write_text('synthetic original\n')
        sq.run(['git','-C',fixture,'add','original.txt'])
        sq.run(['git','-C',fixture,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                'commit','-m','Synthetic reference'])
        with self.assertRaisesRegex(ValueError,'wrong reference pin'):
            sq.validate_reference(fixture)
        (fixture/'original.txt').write_text('changed\n')
        synthetic_pin=sq.run(['git','-C',fixture,'rev-parse','HEAD']).strip()
        with mock.patch.object(sq,'PIN',synthetic_pin):
            with self.assertRaisesRegex(ValueError,'dirty reference'):
                sq.validate_reference(fixture)

    def test_wrong_contract_and_missing_oracle_fail_closed(self):
        wrong=self.out.parent/'wrong-contract.pdf';wrong.write_bytes(b'synthetic wrong contract')
        with self.assertRaisesRegex(ValueError,'Arm contract'):
            sq.check(self.reference,self.python,wrong,self.out/'never')
        with mock.patch.object(sq.platform,'machine',return_value='x86_64'):
            with self.assertRaisesRegex(ValueError,'oracle unavailable'):
                sq.check(self.reference,self.python,ROOT/'.local/cpu-sqshl-019/arm-contract.pdf',self.out/'never')

    def test_existing_output_refused(self):
        with self.assertRaisesRegex(ValueError,'fresh output required'):
            sq.check(self.reference,self.python,ROOT/'.local/cpu-sqshl-019/arm-contract.pdf',self.out)


if __name__=='__main__':
    unittest.main()
