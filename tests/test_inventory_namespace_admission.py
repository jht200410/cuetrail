"""Counterexamples for SQL LIKE underscore vs actual internal SQLite names."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from cuetrail_governance import inventory as i


class NamespaceAdmissionContracts(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'unrelated.sqlite3'

    def test_literal_sqlite_lookalike_tables_rejected_and_preserved(self):
        for index,name in enumerate(('sqliteX_unrelated','sqlitex','sqliteanything','SQLITEX_UNRELATED')):
            with self.subTest(table=name):
                path=Path(self.folder.name)/f'lookalike-{index}.sqlite3'
                with closing(sqlite3.connect(path)) as db,db:
                    db.execute('create table "'+name+'" (id integer)')
                    db.execute('insert into "'+name+'" values (7)')
                with self.assertRaises(i.SourceIntegrityError):
                    i.Inventory(path)
                with closing(sqlite3.connect(path)) as db,db:
                    self.assertEqual(db.execute("select name from sqlite_master where type='table'").fetchall(),[(name,)])
                    self.assertEqual(db.execute('select * from "'+name+'"').fetchall(),[(7,)])

    def test_sqlite_sequence_is_ignored_but_its_foreign_owner_table_is_rejected(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('create table unrelated (id integer primary key autoincrement)')
            self.assertIn(('sqlite_sequence',),db.execute("select name from sqlite_master where type='table'").fetchall())
        with self.assertRaises(i.SourceIntegrityError):
            i.Inventory(self.path)
        with closing(sqlite3.connect(self.path)) as db,db:
            names={v[0] for v in db.execute("select name from sqlite_master where type='table'")}
            self.assertEqual(names,{'unrelated','sqlite_sequence'})



if __name__=='__main__':
    unittest.main()
