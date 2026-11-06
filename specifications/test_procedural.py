"""Synthetic conditional-execution contracts, independent of benchmark answers."""
from dataclasses import asdict
import json
from pathlib import Path
import unittest

from cuetrail import procedural as p


def source(text, role='user', sid='s1'):
    return dict(id=sid, content=text, role=role, session_id='session1', timestamp=None)


class ProcedureTests(unittest.TestCase):
    def setUp(self):
        self.index = p.ProcedureIndex()

    def test_condition_action_and_quote(self):
        s = source('Whenever I deploy production, I must first back up the database; then verify the checksums.')
        proc = self.index.compile([s])[0]
        self.assertEqual(proc.authority, 'user_constraint')
        self.assertEqual(proc.status, 'active')
        self.assertEqual(s['content'][proc.sources[0].start:proc.sources[0].end], proc.sources[0].quote)
        self.assertIn('then verify', proc.steps[0])
        selected, trace = self.index.select([proc], 'How should I deploy production today?')
        self.assertEqual(len(selected), 1)
        self.assertTrue(trace['triggered'])

    def test_irrelevant_scope_and_non_task(self):
        procs = self.index.compile([source('Whenever I deploy production, I must back up the database.')])
        self.assertFalse(self.index.select(procs, 'Help me plan a hiking trip.')[0])
        self.assertFalse(self.index.select(procs, 'When did I deploy production?')[0])

    def test_advice_is_not_permanent(self):
        procs = self.index.compile([source('Whenever you deploy production, you should back up the database.', 'assistant')])
        self.assertEqual(procs[0].status, 'proposal')
        self.assertFalse(self.index.select(procs, 'How should I deploy production?')[0])

    def test_habit_is_distinct(self):
        proc = self.index.compile([source('When I cook dinner, I usually chop vegetables first and clean the worktop last.')])[0]
        self.assertEqual(proc.authority, 'confirmed_habit')
        self.assertTrue(self.index.select([proc], 'Help me cook dinner.')[0])

    def test_preference_alone_is_not_procedure(self):
        self.assertEqual(self.index.compile([source('I prefer quiet hotels and I like jazz.')]), [])

    def test_one_off_does_not_become_standing_rule(self):
        proc = self.index.compile([source('When I deploy production tomorrow, please back up the database.')])[0]
        self.assertEqual(proc.status, 'source_session_only')
        self.assertFalse(self.index.select([proc], 'How should I deploy production tomorrow?')[0])

    def test_missing_prerequisite_and_polarity(self):
        proc = self.index.compile([source('If the production server is offline, I always check logs before restarting services.')])[0]
        self.assertFalse(self.index.select([proc], 'How should I restart the server?')[0])
        self.assertTrue(self.index.select([proc], 'How should I proceed if the production server is offline?')[0])
        self.assertFalse(self.index.select([proc], 'How should I proceed if the production server is not offline?')[0])

    def test_conflict_keeps_all_evidence(self):
        procs = self.index.compile([source('Whenever I deploy production, I must back up the database.', sid='a'),
                                   source('Whenever I deploy production, I must skip backups.', sid='b')])
        self.assertEqual(len(procs), 2)
        self.assertEqual({x.status for x in procs}, {'ambiguous'})
        self.assertEqual({x.version for x in procs}, {1, 2})
        self.assertFalse(self.index.select(procs, 'How should I deploy production?')[0])

    def test_repeat_same_rule_is_not_new_version(self):
        procs = self.index.compile([source('Whenever I deploy production, I must back up the database.', sid=s) for s in ('a', 'b')])
        self.assertEqual({x.version for x in procs}, {1})
        self.assertEqual(len(self.index.select(procs, 'How should I deploy production?')[0]), 1)

    def test_inject_preserves_native_order_and_anchor(self):
        procs = self.index.compile([source('Whenever I deploy production, I must back up the database.')])
        hits = [dict(id=str(i), content=f'original {i}', score=1/(i+1)) for i in range(5)]
        result, audit = p.inject(hits, procs, None)
        self.assertTrue(audit['applied'])
        self.assertEqual(result[0], hits[0])
        self.assertEqual([x for x in result if not x['id'].startswith('procedure:')], hits)
        self.assertEqual(p.inject(hits, [], None)[0], hits)
        self.assertEqual(p.inject(hits, procs, None, 10)[0], hits)


if __name__ == '__main__':
    unittest.main()
