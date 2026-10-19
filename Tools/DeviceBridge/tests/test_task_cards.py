import base64
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task_cards import TaskCards, render_title
from protocol import Limits, ProtocolError, validate_snapshot, encode, envelope, token
from simulator import DeviceSimulator, HostSession


def body(count=6):
    return dict(revision=1, validForMs=5000, sourceLiveness='unverified', overallStatus='working',
                sessions=[dict(id=f's{i+1}', display='working', observed='working', host='running') for i in range(count)])


class TaskCardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.index = Path(self.tmp.name) / 'session_index.jsonl'
        self.index.write_text(json.dumps(dict(id='chat1', thread_name='修复灯光预览'))+'\n', encoding='utf-8')
        self.rendered = []
        def render(text):
            self.rendered.append(text)
            return bytes([0xA5] * 320)
        self.cards = TaskCards(self.index, render)

    def test_titles_stable_slots_waiting_priority_overflow_and_completion(self):
        value = body()
        first = self.cards.build(value, {'chat1': 's1'})
        self.assertIn('修复灯光预览', self.rendered)
        self.assertEqual(first['active'], 6)
        self.assertEqual([c['id'] for c in first['cards']], ['s1','s2','s3','s4'])
        value['sessions'][5]['display'] = 'waitingApproval'
        second = self.cards.build(value, {})
        positions = {c['id']: c['slot'] for c in second['cards']}
        self.assertIn('s6', positions)
        self.assertEqual(positions['s1'], 0)
        self.assertEqual(positions['s2'], 1)
        value['sessions'] = []
        self.assertEqual(self.cards.build(value, {})['cards'], [])

    def test_worst_supported_snapshot_fits_usb_and_wss_budget(self):
        value = body(16)
        for s in value['sessions']: s.update(display='waitingApproval', observed='waitingApproval')
        value.update(overallStatus='waitingApproval', challengeSeq=4294967295)
        value['taskCards'] = self.cards.build(value, {})
        validate_snapshot(value, Limits(4096,16))
        raw = encode(envelope(token(),token(),token(),4294967295,'snapshot',value), Limits(4096,16))
        self.assertLessEqual(len(raw),4096)

    def test_bad_slots_aliases_rasters_counts_rejected(self):
        good = body(4)
        good['taskCards'] = self.cards.build(good,{})
        for mutate in [lambda s:s['cards'][1].update(slot=0), lambda s:s['cards'][1].update(id='s1'),
                       lambda s:s['cards'][0].update(bitmap='!'+s['cards'][0]['bitmap'][1:]),
                       lambda s:s.update(active=99), lambda s:s['cards'][0].update(id='s9'),
                       lambda s:s['cards'][0].update(id=[])]:
            value=copy.deepcopy(good)
            mutate(value['taskCards'])
            with self.assertRaises(ProtocolError): validate_snapshot(value, Limits(4096,16))

    def test_missing_metadata_uses_alias_and_bad_capability_is_rejected(self):
        self.index.unlink()
        self.cards.build(body(1),{})
        self.assertEqual(self.rendered, ['Conversation s1'])
        simulator=DeviceSimulator(Limits(4096,16),lease_ms=5000,task_cards=True)
        welcome=simulator.open(0)
        self.assertTrue(HostSession(welcome,Limits(4096,16)).task_cards)
        welcome['body']['taskCards']='true'
        with self.assertRaises(ProtocolError): HostSession(welcome,Limits(4096,16))

    @unittest.skipUnless(os.name=='nt','Windows system font renderer')
    def test_real_cjk_raster_has_ink_and_is_cached(self):
        pixels=render_title('任务气泡中文测试')
        self.assertEqual(len(pixels),320)
        self.assertTrue(any(pixels))
        self.assertIs(pixels,render_title('任务气泡中文测试'))


if __name__=='__main__': unittest.main()
