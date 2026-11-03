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
        with patch.object(a.subprocess,'run',return_value=Mock(returncode=1)) as run:
            self.assertFalse(a.validate('/tmp/candidate'))
            self.assertEqual(run.call_count,1)
    def test_failed_tests_reject_candidate(self):
        with patch.object(a.subprocess,'run',side_effect=[Mock(returncode=0),Mock(returncode=1)]):
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

if __name__=='__main__': unittest.main()
