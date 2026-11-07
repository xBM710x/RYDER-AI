import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, Mock
import auto_update as a

class UpdaterTests(unittest.TestCase):
    def test_runtime_and_dependency_changes_blocked(self):
        for path in ['bot/.env','bot/desk.db','bot/brain13.json','bot/requirements.txt','bot/events.jsonl']:
            self.assertFalse(a.allowed([path]))
        self.assertTrue(a.allowed(['bot/runner.py','app.js','data.json']))
    def test_bad_compile_never_runs_tests(self):
        with patch.object(a,'candidate_tests',return_value=['test_existing']), patch.object(a.subprocess,'run',return_value=Mock(returncode=1)) as run:
            self.assertFalse(a.validate('/tmp/candidate'))
            self.assertEqual(run.call_count,1)
    def test_failed_tests_reject_candidate(self):
        with patch.object(a,'candidate_tests',return_value=['test_existing']), patch.object(a.subprocess,'run',side_effect=[Mock(returncode=0),Mock(returncode=1)]):
            self.assertFalse(a.validate('/tmp/candidate'))
    def test_dirty_tree_retains_running_child(self):
        with patch.object(a,'git',side_effect=['main',' M bot/runner.py']),patch.object(a,'stop_child') as stop:
            self.assertFalse(a.update());stop.assert_not_called()
    def test_backup_integrity_and_original_preserved(self):
        import sqlite3
        with TemporaryDirectory() as td,patch.object(a,'BOT',Path(td)):
            db=Path(td)/'desk.db'
            with sqlite3.connect(db) as c:c.execute('CREATE TABLE memory(value)');c.execute("INSERT INTO memory VALUES('kept')")
            a.backup()
            target=next((Path(td)/'update-backups').glob('*.db'))
            with sqlite3.connect(target) as c:self.assertEqual(c.execute('SELECT value FROM memory').fetchone()[0],'kept')
            self.assertTrue(db.exists())

class CandidateManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.stage = Path(self.temp.name)
        self.bot = self.stage/'bot'; self.bot.mkdir()
        self.patch = patch.object(a, 'TESTS', ['test_existing']); self.patch.start()
        self.manifest("['test_added']")
        self.write_test('test_existing', True); self.write_test('test_added', True)
    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()
    def manifest(self, expression):
        (self.bot/'auto_update.py').write_text('TESTS = '+expression+'\n')
    def write_test(self, name, passes):
        (self.bot/(name+'.py')).write_text('import unittest\nclass Check(unittest.TestCase):\n def test_result(self): self.assertTrue('+str(passes)+')\n')
    def test_union_preserves_old_checks_and_adds_new(self):
        self.assertEqual(a.candidate_tests(self.bot), ['test_existing','test_added'])
    def test_malformed_manifests_fail_closed(self):
        for raw in ["[]", "'test_added'", "['../test_added']", "['test_added','test_added']", "[123]", "list(['test_added'])", "['test_missing']"]:
            with self.subTest(raw=raw):
                self.manifest(raw)
                with patch.object(a.subprocess, 'run') as run:
                    self.assertFalse(a.validate(self.stage)); run.assert_not_called()
    def test_missing_old_check_rejects_candidate(self):
        (self.bot/'test_existing.py').unlink()
        self.assertFalse(a.validate(self.stage))
    def test_candidate_updater_not_executed(self):
        with (self.bot/'auto_update.py').open('a') as f: f.write("raise RuntimeError('must not import')\n")
        self.assertEqual(a.candidate_tests(self.bot), ['test_existing','test_added'])
    def test_added_failure_blocks_install_real_subprocess(self):
        import sys
        self.write_test('test_added', False)
        self.assertFalse(a.validate(self.stage, python=sys.executable))
    def test_passing_candidate_runs_real_subprocess(self):
        import sys
        self.assertTrue(a.validate(self.stage, python=sys.executable))
    def test_old_failure_still_blocks_install(self):
        import sys
        self.write_test('test_existing', False)
        self.assertFalse(a.validate(self.stage, python=sys.executable))
    def test_duplicate_declaration_rejected(self):
        with (self.bot/'auto_update.py').open('a') as f: f.write("TESTS = ['test_added']\n")
        self.assertFalse(a.validate(self.stage))

if __name__=='__main__': unittest.main()
