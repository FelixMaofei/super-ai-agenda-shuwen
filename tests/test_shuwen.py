from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import complete_template as template
import package_local
import confirm_shuwen


def small_facts(long=False):
    title = '工作坊：' + '练习沟通与表达，理解听众并说清楚自己的观点。' * 8 if long else '沟通工作坊'
    rows = [
        {'id': 'open', 'section': 'opening', 'label': '开场', 'owner': '测试甲', 'duration': .5, 'start': '19:30', 'end': '19:30:30'},
        {'id': 'workshop', 'section': 'first_half', 'label': title, 'owner': '测试乙', 'duration': 59.5, 'start': '19:30:30', 'end': '20:30'},
        {'id': 'close', 'section': 'closing', 'label': '结束分享', 'owner': '测试丙', 'duration': 10, 'start': '20:30', 'end': '20:40'},
    ]
    if long:
        rows[1]['details'] = ['练习：' + '用一个具体的故事说明自己的想法。' * 8] * 3
    return {'schema_version': 3, 'club': {'name': 'Super AI Lab'},
            'meeting': {'number': '测试', 'theme': '从第一次表达走向更自信的自己' if long else '沟通与合作',
                        'date': '2026-09-14', 'start': '19:30', 'end': '20:40', 'location': '程序测试会议室', 'word_of_day': '练习', 'manager': '测试甲'},
            'timeline': rows, 'backstage': [],
            'computed': {'status': 'exact', 'total_minutes': 70, 'approved_overtime_minutes': 0, 'final_end': '20:40', 'duration_confirmation_required': False}}


class ShuwenTests(unittest.TestCase):
    def test_default_timing_matches_accepted_meeting(self):
        data = json.loads((ROOT / 'examples/shuwen-meeting.fixture.json').read_text())
        before = deepcopy(data)
        computed = confirm_shuwen.prepare(data, ROOT, allow_pending=True)
        self.assertEqual(data, before)
        rows = {r['id']: r for r in computed['timeline']}
        self.assertEqual(rows['president_opening']['start'], '19:32')
        self.assertEqual(rows['toastmaster_opening']['start'], '19:35')
        self.assertEqual(rows['timer_intro']['start'], '19:38')
        self.assertEqual(rows['table_topics']['start'], '20:08')
        self.assertEqual(rows['table_topics']['end'], '20:26')
        self.assertEqual(rows['prepared_evaluation:1']['start'], '20:38')
        self.assertEqual(computed['computed']['transition_minutes'], 18)
        self.assertEqual(computed['computed']['final_end'], '21:30')
        visible = template.facts(computed)['rows']
        self.assertEqual(len(visible), 21)
        self.assertTrue(all('串场' not in r['title'] for r in visible))

    def test_explicit_meeting_gap_overrides_club_default(self):
        data = json.loads((ROOT / 'examples/shuwen-meeting.fixture.json').read_text())
        next(r for r in data['agenda_overrides'] if r['id'] == 'photo_break')['transition_after'] = .5
        data['impromptu']['minutes'] = 18.5
        computed = confirm_shuwen.prepare(data, ROOT, allow_pending=True)
        self.assertEqual(computed['computed']['transition_minutes'], 17.5)
        self.assertEqual(computed['computed']['total_minutes'], 120)
        self.assertEqual(computed['computed']['final_end'], '21:30')

    def test_half_minutes_and_no_phantom_speeches(self):
        data = small_facts()
        before = deepcopy(data)
        result = template.facts(data)
        self.assertEqual(data, before)
        self.assertEqual([r['id'] for r in result['rows']], ['open', 'workshop', 'close'])
        self.assertEqual(result['rows'][1]['start'], '19:30:30')
        self.assertEqual(result['rows'][1]['minutes'], 59.5)

    def test_corrupt_timeline_is_rejected(self):
        data = small_facts()
        data['timeline'][1]['start'] = '19:31'
        with self.assertRaisesRegex(ValueError, '不连续'):
            template.facts(data)

    def test_short_and_long_outputs_keep_fixed_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            hero = path / 'fixture-hero.png'
            Image.new('RGB', (2600, 932), '#fff7e6').save(hero)
            short = template.render(small_facts(), hero, path / 'short')
            long = template.render(small_facts(long=True), hero, path / 'long')
            self.assertEqual(short['canvas'], [2600, 3700])
            self.assertGreater(long['canvas'][1], 3700)
            for result in (short, long):
                self.assertEqual(result['fixed_pixels'], {'right': True, 'bottom': True})
                self.assertEqual(result['flow_font_px'], 52)

    def test_empty_phase_is_allowed(self):
        data = small_facts()
        for row in data['timeline']:
            row['section'] = 'first_half'
        self.assertEqual(len(template.facts(data)['rows']), 3)

    def test_confirmed_hash_required(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            source = path / 'facts.json'
            source.write_text(json.dumps(small_facts(), ensure_ascii=False))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/complete_template.py'), 'render', str(source),
                                     '--confirmed-sha256', 'wrong', '--output-dir', str(path / 'out')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('确认编号', result.stderr)
            self.assertFalse((path / 'out/agenda.png').exists())

    def test_packaged_copy_runs_without_source_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            package, archive = package_local.build_package(path / 'package')
            self.assertTrue(archive.is_file())
            for name in ('scripts/complete_template.py', 'scripts/editable_agenda.py', 'assets/complete/source.jpg', 'references/complete-template.md'):
                self.assertTrue((package / name).is_file(), name)
            source = path / 'facts.json'
            source.write_text(json.dumps(small_facts(), ensure_ascii=False))
            hero = path / 'hero.png'
            Image.new('RGB', (2600, 932), '#fff7e6').save(hero)
            result = subprocess.run([sys.executable, str(package / 'scripts/complete_template.py'), 'render', str(source),
                                     '--hero', str(hero), '--confirmed-sha256', hashlib.sha256(source.read_bytes()).hexdigest(),
                                     '--output-dir', str(path / 'out')], cwd=path, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with Image.open(path / 'out/agenda.png') as output:
                self.assertEqual(output.size, (2600, 3700))

    def test_real_engine_confirmation_to_render(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            data = json.loads((ROOT / 'examples/mingyuan-ai-lab/meeting.json').read_text())
            data['club'].update(name='Super AI Lab', default_location='程序测试会议室', support_components=[])
            data['meeting'].update(number='测试', theme='表达与成长', location='程序测试会议室')
            source = path / 'meeting.json'
            source.write_text(json.dumps(data, ensure_ascii=False))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_agenda.py'), 'confirm', str(source), '--output-dir', str(path / 'confirmed')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            computed = json.loads((path / 'confirmed/agenda.computed.json').read_text())
            adapted = template.facts(computed)
            self.assertEqual([r['start'] for r in adapted['rows']], [r['start'] for r in computed['timeline']])
            self.assertEqual(len(adapted['rows']), len(computed['timeline']))
            self.assertTrue(all('串场' not in r['title'] and '转场' not in r['title'] for r in adapted['rows']))
            self.assertEqual(sum(r['transition_after'] for r in adapted['rows']), 17)
            self.assertEqual(adapted['computed']['final_end'], '21:30')
            hero = path / 'hero.png'
            Image.new('RGB', (2600, 932), '#fff7e6').save(hero)
            rendered = template.render(computed, hero, path / 'out')
            self.assertTrue(all(rendered['fixed_pixels'].values()))


if __name__ == '__main__':
    unittest.main()
