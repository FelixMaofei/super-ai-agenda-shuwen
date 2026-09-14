#!/usr/bin/env python3
"""Shuwen compositor: render confirmed V4.2 facts over the Super AI Lab template."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps
from build_agenda import parse_clock, format_clock, minute_ticks, minutes_from_ticks

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'assets/complete/source.jpg'
NAVY = '#073650'
PHASES = {'opening': 'opening', 'first_half': 'upper', 'second_half': 'lower', 'closing': 'lower'}


def resolve_font(given=None, *, bold=False):
    if given:
        path = Path(given).expanduser()
        if not path.is_file():
            raise ValueError('指定字体不存在：' + str(path))
        return str(path)
    home_fonts = Path.home() / 'Library/Fonts'
    windows_fonts = Path(os.environ.get('WINDIR', 'C:' + os.sep + 'Windows')) / 'Fonts'
    choices = [
        home_fonts / ('msyhbd_0.ttc' if bold else 'msyh.ttc'),
        windows_fonts / ('msyhbd.ttc' if bold else 'msyh.ttc'),
        Path('/System/Library/Fonts/STHeiti Medium.ttc'),
        Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
        Path('/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc'),
    ]
    for path in choices:
        if path.is_file():
            return str(path)
    raise ValueError('缺少中文字体；请通过 --font 指定中文 TTF/TTC/OTF 文件')


def facts(data):
    """Adapt existing computed facts; validate their arithmetic without changing the agenda."""
    data = deepcopy(data)
    if data.get('schema_version') != 3 or not isinstance(data.get('timeline'), list):
        raise ValueError('请先用 run_agenda.py confirm 生成 agenda.computed.json；不读取旧 V009 接龙格式')
    meeting = data['meeting']
    for key in ('theme', 'number', 'date', 'start', 'end', 'location'):
        if not str(meeting.get(key) or '').strip():
            raise ValueError('缺少本期信息：' + key)
    date.fromisoformat(meeting['date'])
    meta = data.get('computed', {})
    if meta.get('status') not in ('exact', 'exact_with_approved_overtime', 'exact_with_pending') or meta.get('duration_confirmation_required'):
        raise ValueError('会议时间尚未确认，请回到 confirm 处理')
    if meta.get('status') == 'exact_with_pending' and not data.get('accepted_pending_roles'):
        raise ValueError('待定岗位尚未明确接受')
    if not data['timeline']:
        raise ValueError('会议流程为空')
    current = minute_ticks(parse_clock(meeting['start']))
    start = current
    rows = []
    ids = set()
    for item in data['timeline']:
        if item['id'] in ids:
            raise ValueError('重复环节 ID：' + item['id'])
        ids.add(item['id'])
        if item.get('section') not in PHASES:
            raise ValueError('未知流程分段：' + str(item.get('section')))
        duration = minute_ticks(item['duration'])
        transition = minute_ticks(item.get('transition_after', 0))
        if duration <= 0 or transition < 0:
            raise ValueError('环节时长须为正数，转场时长不可为负')
        if minute_ticks(parse_clock(item['start'])) != current % 2880:
            raise ValueError('开始时间不连续：' + item['id'])
        current += duration
        if minute_ticks(parse_clock(item['end'])) != current % 2880:
            raise ValueError('结束时间与时长不一致：' + item['id'])
        parts = [str(item['label'])]
        if item.get('pathways'):
            parts.append(str(item['pathways']))
        details = item.get('details') or []
        parts.extend([details] if isinstance(details, str) else map(str, details))
        rows.append({
            'id': item['id'], 'phase': PHASES[item['section']], 'title': '\n'.join(parts),
            'owner': str(item.get('owner') or '待定'), 'start': item['start'], 'end': item['end'],
            'minutes': item['duration'], 'transition_after': minutes_from_ticks(transition),
        })
        # Transitions affect timestamps only; never render them as agenda content.
        current += transition
    declared = minute_ticks(parse_clock(meeting['end']))
    approved = minute_ticks(meta.get('approved_overtime_minutes', 0))
    if current - declared != approved or current - start != minute_ticks(meta['total_minutes']):
        raise ValueError('流程总时长与确认结果不一致')
    if meta.get('final_end') != format_clock(minutes_from_ticks(current)):
        raise ValueError('最终结束时间与确认结果不一致')
    return {'meeting': meeting, 'rows': rows, 'backstage': data.get('backstage', []),
            'computed': meta, 'time_closed': True, 'source_schema': 3}


def render(data, hero, out, fontfile=None, brand_font=None, title_font=None, highlight='', reference_header=False):
    result = facts(data)
    source = Image.open(SOURCE).convert('RGB')
    if source.size != (2600, 3700):
        raise ValueError('完整模板须为 2600×3700')
    fontfile = resolve_font(fontfile)
    brand_font = resolve_font(brand_font or fontfile, bold=True)
    title_font = resolve_font(title_font or brand_font, bold=True)
    body = ImageFont.truetype(fontfile, 52)
    measure = ImageDraw.Draw(source)

    def wrap(value, width, font=body):
        lines = []
        for paragraph in str(value).split('\n'):
            line = ''
            for char in paragraph:
                if line and measure.textlength(line + char, font=font) > width:
                    lines.append(line)
                    line = char
                else:
                    line += char
            lines.append(line)
        return '\n'.join(lines)

    def text_height(value, font=body):
        box = measure.multiline_textbbox((0, 0), value, font=font, spacing=10)
        return box[3] - box[1]

    # Contiguous groups preserve the exact input order, including unusual phase changes.
    groups = []
    for row in result['rows']:
        row['display_title'] = wrap(row['title'], 885)
        row['display_owner'] = wrap(row['owner'], 245)
        row['height'] = max(93, text_height(row['display_title']) + 38, text_height(row['display_owner']) + 38)
        if not groups or groups[-1][0]['phase'] != row['phase']:
            groups.append([])
        groups[-1].append(row)
    minimum = sum(r['height'] for r in result['rows']) + 75 + 13 * (len(groups) - 1)
    total = max(2020, minimum)
    extra = (total - minimum) / len(result['rows'])
    delta = total - 2020
    backstage = []
    manager = result['meeting'].get('manager')
    if manager:
        backstage.append('会议经理：' + str(manager))
    for item in result['backstage']:
        backstage.append(str(item.get('label') or item.get('id') or '幕后') + '：' + str(item.get('person') or '待定'))
    backstage_font = ImageFont.truetype(fontfile, 47)
    backstage_text = wrap(' ｜ '.join(backstage) or '待定', 2175, backstage_font)
    backstage_extra = max(0, text_height(backstage_text, backstage_font) + 24 - 74)
    footer_shift = delta + backstage_extra
    image = Image.new('RGB', (2600, 3700 + footer_shift), NAVY)
    image.paste(source.crop((0, 0, 2600, 3095)), (0, 0))
    image.paste(source.crop((0, 3095, 2600, 3195)), (0, 3095 + delta))
    image.paste(source.crop((0, 3195, 2600, 3700)), (0, 3195 + footer_shift))
    draw = ImageDraw.Draw(image)

    def text(value, box, size=52, fill='#111111', center=False, bold=False, typeface=None):
        font = ImageFont.truetype(typeface or fontfile, size)
        stroke = 1 if bold else 0
        bounds = draw.multiline_textbbox((0, 0), value, font=font, spacing=10, stroke_width=stroke)
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        if width > box[2] - box[0] or height > box[3] - box[1]:
            raise ValueError('文字超出槽位，请换行或调整布局：' + value)
        x = box[0] + ((box[2] - box[0] - width) / 2 if center else 0)
        y = box[1] + (box[3] - box[1] - height) / 2
        draw.multiline_text((x - bounds[0], y - bounds[1]), value, font=font, fill=fill,
                            spacing=10, stroke_width=stroke, align='center' if center else 'left')

    m = result['meeting']
    if not reference_header:
        if not hero:
            raise ValueError('请提供本期无字主题插画 --hero')
        image.paste(ImageOps.fit(Image.open(hero).convert('RGB'), (2600, 932)), (0, 0))
        logo = Image.open(ROOT / 'assets/v009/logo.png').convert('RGBA')
        logo.thumbnail((389, 321))
        image.paste(logo, (66, 88), logo)
        text('Super AI Lab', (477, 80, 1630, 205), 106, NAVY, bold=True, typeface=brand_font)
        text('头马俱乐部', (477, 215, 1510, 309), 78, NAVY, bold=True, typeface=brand_font)
        text('第' + str(m['number']) + '期例会', (477, 330, 1590, 425), 74, '#772432', bold=True, typeface=brand_font)
        theme = str(m['theme'])
        theme_size = 190
        theme_face = ImageFont.truetype(title_font, theme_size)
        if draw.textlength(theme, font=theme_face) > 1685 or '\n' in theme:
            theme_size = 140
            theme = wrap(theme, 1685, ImageFont.truetype(title_font, theme_size))
        text(theme, (90, 468, 1775, 780), theme_size, NAVY, bold=True, typeface=title_font)
        word = str(m.get('word_of_day') or '')
        badges = []
        if word:
            badges.append(((102, 800, 850, 902), '今日一词：' + word, '#772432'))
        if highlight:
            badges.append(((880, 800, 1670, 902), '会议亮点：' + highlight, '#005574'))
        for box, label, color in badges:
            draw.rounded_rectangle(box, 18, fill=color)
            text(label, box, 48, 'white', True, True)
    weekday = '一二三四五六日'[date.fromisoformat(m['date']).weekday()]
    end = result['computed']['final_end']
    labels = [((54, 946, 1054, 1031), m['date'].replace('-', '.') + ' 周' + weekday + ' ' + m['start'] + '-' + end),
              ((1080, 946, 2546, 1031), '地址：' + m['location'])]
    for box, label in labels:
        draw.rounded_rectangle(box, 42, fill='#edf1f1')
        text(label, box, 52, NAVY, True, True)
    draw.rectangle((50, 1046, 1854, 3074 + delta), fill=NAVY)
    y = 1050
    for index, group in enumerate(groups):
        height = sum(r['height'] + extra for r in group) + (75 if index == 0 else 0)
        top, bottom = round(y), round(y + height)
        draw.rounded_rectangle((54, top, 1850, bottom), 28, fill='white', outline='#b6d9e3', width=3)
        phase = group[0]['phase']
        draw.rectangle((58, top + 4, 160, bottom - 4), fill='#772432' if phase == 'upper' else NAVY)
        phase_label = {'opening': '开\n场', 'upper': '上\n半\n场', 'lower': '下\n半\n场'}[phase]
        if height > 260:
            icon_y = {'opening': 1290, 'upper': 1833, 'lower': 2520}[phase]
            image.paste(source.crop((72, icon_y, 151, icon_y + 80)), (72, round((top + bottom) / 2) - 115))
            text(phase_label, (62, (top + bottom) / 2 - 25, 155, (top + bottom) / 2 + 190), 49, 'white', True)
        else:
            text(phase_label.replace('\n', ''), (62, top + 10, 155, bottom - 10), 28, 'white', True)
        row_y = y
        if index == 0:
            draw.rectangle((165, top + 4, 1846, top + 75), fill='#005775')
            for label, box in [('时间', (165, y, 390, y + 75)), ('会议流程', (414, y, 1320, y + 75)),
                               ('负责人', (1345, y, 1600, y + 75)), ('时长', (1620, y, 1828, y + 75))]:
                text(label, box, 48, 'white', True, True)
            row_y += 75
        for row_index, row in enumerate(group):
            row_end = row_y + row['height'] + extra
            text(row['display_title'], (414, row_y, 1300, row_end))
            text(row['display_owner'], (1350, row_y, 1600, row_end), center=True)
            duration = f'{row["minutes"]:g}分钟'
            # Half-minute starts retain seconds; widen the pill instead of truncating.
            for value, box, color in [(row['start'], (172, (row_y + row_end) / 2 - 31, 400, (row_y + row_end) / 2 + 31), '#e8f8fb'),
                                      (duration, (1620, (row_y + row_end) / 2 - 31, 1828, (row_y + row_end) / 2 + 31), '#fbf3c1')]:
                draw.rounded_rectangle(box, 17, fill=color)
                text(value, box, 46, center=True)
            if row_index < len(group) - 1:
                draw.line((165, row_end, 1828, row_end), fill='#d2d8db', width=2)
            row_y = row_end
        draw.rounded_rectangle((54, top, 1850, bottom), 28, outline='#b6d9e3', width=3)
        y = bottom + 13
    # Extend the backstage card when names wrap; keep the footer itself pixel-identical.
    if backstage_extra:
        draw.rounded_rectangle((54, 3095 + delta, 2547, 3180 + footer_shift), 28, fill='white')
        image.paste(source.crop((54, 3095, 330, 3180)), (54, 3095 + delta))
    draw.rectangle((330, 3100 + delta, 2515, 3174 + footer_shift), fill='white')
    text(backstage_text, (332, 3100 + delta, 2515, 3174 + footer_shift), 47)
    checks = {}
    for name, box, dest in [('right', (1877, 1050, 2548, 3070), (1877, 1050, 2548, 3070)),
                             ('bottom', (0, 3195, 2600, 3700), (0, 3195 + footer_shift, 2600, 3700 + footer_shift))]:
        checks[name] = ImageChops.difference(source.crop(box), image.crop(dest)).getbbox() is None
    if not all(checks.values()):
        raise ValueError('固定区域像素发生变化：' + str(checks))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    image.save(out / 'agenda.png')
    result.update(canvas=list(image.size), fixed_pixels=checks, font=fontfile, brand_font=brand_font,
                  title_font=title_font, flow_font_px=52, extension_px=footer_shift, highlight=highlight)
    (out / 'agenda.render.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['inspect', 'render'])
    parser.add_argument('input')
    parser.add_argument('--hero')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--font')
    parser.add_argument('--brand-font')
    parser.add_argument('--title-font')
    parser.add_argument('--highlight', default='')
    parser.add_argument('--confirmed-sha256')
    args = parser.parse_args()
    try:
        raw = Path(args.input).read_bytes()
        data = json.loads(raw)
        digest = hashlib.sha256(raw).hexdigest()
        if args.command == 'inspect':
            result = facts(data)
        else:
            if args.confirmed_sha256 != digest:
                raise ValueError('确认编号与事实文件不一致，请先确认当前文字稿')
            result = render(data, args.hero, args.output_dir, args.font, args.brand_font, args.title_font, args.highlight)
        print(json.dumps({'ok': True, 'facts_sha256': digest, 'result': result}, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
