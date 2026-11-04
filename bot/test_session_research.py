import sqlite3
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
import session_research as sr


class SessionTests(unittest.TestCase):
    def test_roundtrip_cost_and_depth(self):
        self.assertLess(sr.replay((0,1,10000),(300,1,10000)),0)
        result=sr.depth(50,1,1000)
        self.assertLess(result['half'],result['expected'])
        self.assertIsNone(sr.depth(50,1,0))

    def test_rule_and_vote_evidence(self):
        self.assertTrue(sr.changed_rule({'volume_1h':('fail',),'socials':('pass',)}).startswith('unknown'))
        self.assertEqual(sr.changed_rule({'liquidity':('fail',)}),'liquidity')
        self.assertEqual(sr.objections({'votes':{'risk':[0.2],'filter':[0.8]}}),['risk'])
        self.assertEqual(sr.objections({'votes':{'risk':[0.2]}}),[])

    def test_session_spans_clock_change(self):
        tz=ZoneInfo('America/Los_Angeles')
        now=datetime(2026,11,1,8,tzinfo=tz)
        start=datetime.fromtimestamp(sr.session_start(now.timestamp()),tz)
        self.assertEqual((start.day,start.hour),(31,18))

    def test_replay_requires_two_later_quotes_on_same_pool(self):
        db=sqlite3.connect(':memory:')
        db.executescript("""
        CREATE TABLE events(ts,kind,mint,symbol,data);
        CREATE TABLE seen(first_ts,mint);
        CREATE TABLE positions(symbol,mint,version,opened,closed,pnl,status);
        CREATE TABLE first_usable(venue,ts,created);
        CREATE TABLE research_quotes(mint,pool,ts,price,liq);
        INSERT INTO events VALUES(1793820000,'kill','abc','ABC','{"reason":"low"}');
        INSERT INTO research_quotes VALUES('abc','a',1793820010,1,10000),('abc','b',1793820320,4,10000);
        """)
        now=1793823000
        first=sr.build(db,db,now)
        self.assertEqual((first['sample'],first['measured']),(1,0))
        db.execute("INSERT INTO research_quotes VALUES('abc','a',1793820400,1,10000)")
        second=sr.build(db,db,now)
        self.assertEqual(second['measured'],1)
        self.assertLess(second['replays'][0]['net'],0)
