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


def semantic_title(meeting):
    title = str(meeting['theme'])
    visible = ''.join(title.split())
    supplied = meeting.get('title_lines')
    if supplied:
        lines = [str(line).strip() for line in supplied]
    elif '\n' in title:
        lines = [line.strip() for line in title.splitlines()]
    elif len(visible) > 7:
        lines = []
        for mark in ('，', '：', '；', '。', '？', '！', ',', ':', ';'):
            if mark in title:
                left, right = title.split(mark, 1)
                if left.strip() and len(''.join(right.split())) >= 2:
                    lines = [left.rstrip() + mark, right.lstrip()]
                    break
        if not lines:
            raise ValueError('主题超过7字，请按语义提供 meeting.title_lines 两行；第二行至少2字')
    else:
        lines = [title]
    lines = [line for line in lines if line]
    if len(visible) > 7 and (len(lines) != 2 or len(''.join(lines[1].split())) < 2):
        raise ValueError('超过7字的主题必须语义断成两行，且第二行不少于2字')
    return '\n'.join(lines)


BODY_FACE_INDEX = {}


def find_body_face(path, families, style):
    path = Path(path)
    if not path.is_file():
        return None
    for index in range(40 if path.suffix.lower() in ('.ttc', '.otc') else 1):
        try:
            family, weight = ImageFont.truetype(str(path), 52, index=index).getname()
        except OSError:
            break
        if family.lower() in families and weight.lower() == style:
            BODY_FACE_INDEX[str(path)] = index
            return str(path)
    return None


def body_font(path, size):
    return ImageFont.truetype(path, size, index=BODY_FACE_INDEX.get(str(path), 0))


def resolve_font(given=None, *, bold=False):
    if given:
        path = Path(given).expanduser()
        if not path.is_file():
            raise ValueError('指定字体不存在：' + str(path))
        return str(path)
    home_fonts = Path.home() / 'Library/Fonts'
    windows_fonts = Path(os.environ.get('WINDIR', 'C:' + os.sep + 'Windows')) / 'Fonts'
    if not bold:
        pingfang = [home_fonts / 'PingFang SC Regular.ttf', home_fonts / 'PingFang.ttc',
                    Path('/System/Library/Fonts/PingFang.ttc'), Path('/System/Library/Fonts/苹方.ttc')]
        pingfang += sorted(Path('/System/Library/AssetsV2/com_apple_MobileAsset_Font8').glob('*/AssetData/PingFang.ttc'))
        source_han = [home_fonts / name for name in ('思源黑体 CN Medium.otf', 'SourceHanSansCN-Medium.otf', 'SourceHanSansSC-Medium.otf', 'NotoSansCJK-Medium-5.otf')]
        source_han += [windows_fonts / 'SourceHanSansSC-Medium.otf', Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc')]
        yahei = [home_fonts / '微软雅黑.ttc', home_fonts / 'msyh.ttc', windows_fonts / 'msyh.ttc']
        yahei += sorted(Path('/Applications').glob('Microsoft *.app/Contents/Resources/DFonts/msyh.ttc'))
        for candidates, families, style in [
            (pingfang, ('pingfang sc',), 'regular'),
            (source_han, ('source han sans cn', 'source han sans sc', 'noto sans cjk sc'), 'medium'),
            (yahei, ('microsoft yahei',), 'regular'),
        ]:
            for path in candidates:
                selected = find_body_face(path, families, style)
                if selected:
                    return selected
        raise ValueError('缺少默认正文字体：请安装苹方 Regular、思源黑体 Medium 或微软雅黑 Regular，或用 --font 指定字体')
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


BRAND_FACE_INDEX = {}


def find_bold_face(path):
    """Pick a real Bold/Heavy face; TTC files may hold several weights and regions."""
    path = Path(path)
    if not path.is_file():
        return None
    for index in range(40 if path.suffix.lower() in ('.ttc', '.otc') else 1):
        try:
            family, style = ImageFont.truetype(str(path), 74, index=index).getname()
        except OSError:
            break
        if family.startswith('.') or any(region in family for region in (' HK', ' TC', ' MO', ' JP', ' KR')):
            continue
        if any(weight in style.lower() for weight in ('bold', 'heavy', 'black', '粗', 'w6', 'w7', 'w8', 'w9')):
            BRAND_FACE_INDEX[str(path)] = index
            return str(path)
    return None


def brand_face(path, size):
    return ImageFont.truetype(path, size, index=BRAND_FACE_INDEX.get(str(path), 0))


def resolve_brand_bold(given=None):
    """Brand and issue never inherit the regular body font."""
    if given:
        selected = find_bold_face(Path(given).expanduser())
        if not selected:
            raise ValueError('--brand-font 须为中文 Bold/Heavy 字体：' + str(given))
        return selected
    home = Path.home() / 'Library/Fonts'
    win = Path(os.environ.get('WINDIR', 'C:' + os.sep + 'Windows')) / 'Fonts'
    candidates = [home / 'msyhbd_0.ttc', home / 'msyhbd.ttc', win / 'msyhbd.ttc']
    candidates += sorted(Path('/Applications').glob('Microsoft *.app/Contents/Resources/DFonts/msyhbd.ttc'))
    candidates += [home / 'PingFang SC Bold.ttf', Path('/System/Library/Fonts/PingFang.ttc')]
    candidates += sorted(Path('/System/Library/AssetsV2/com_apple_MobileAsset_Font8').glob('*/AssetData/PingFang.ttc'))
    candidates += [Path('/System/Library/Fonts/Hiragino Sans GB.ttc'), home / 'NotoSansCJK-Black-7.otf',
                   Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc')]
    for path in candidates:
        selected = find_bold_face(path)
        if selected:
            return selected
    raise ValueError('顶部名称和期数必须使用粗体字体，请安装微软雅黑 Bold 或通过 --brand-font 指定中文 Bold/Heavy 字体')


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


def render(data, hero, out, fontfile=None, brand_font=None, title_font=None, highlight='', reference_header=False, title_accent=''):
    result = facts(data)
    source = Image.open(SOURCE).convert('RGB')
    if source.width != 2600 or source.height < 3700:
        raise ValueError('完整模板宽度须为 2600px，且高度至少为 3700px')
    def asset(name, width):
        original = Image.open(ROOT / 'assets/complete' / name).convert('RGB')
        return original.resize((width, round(original.height * width / original.width)), Image.Resampling.LANCZOS)

    right_asset = asset('source-r.jpg', 723)
    bottom_asset = asset('source-b.jpg', 2600)
    backstage_asset = asset('muhou.jpg', 260)
    base_height = 3195 + bottom_asset.height
    fontfile = resolve_font(fontfile)
    brand_font = resolve_brand_bold(brand_font)
    if not title_font:
        display_candidate = Path.home() / 'Library/Fonts/Alimama_ShuHeiTi_Bold.ttf'
        heavy_candidates = [
            Path.home() / 'Library/Fonts/NotoSansCJK-Black-7.otf',
            Path.home() / 'Library/Fonts/NotoSansCJK-Black.otf',
            Path('/System/Library/Fonts/Supplemental/NotoSansCJK-Black.otf'),
        ]
        heavy_fallback = next((path for path in heavy_candidates if path.is_file()), None)
        title_font = str(display_candidate) if display_candidate.is_file() else (str(heavy_fallback) if heavy_fallback else brand_font)
    title_font = resolve_font(title_font, bold=True)
    body = body_font(fontfile, 52)
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
    backstage_font = body_font(fontfile, 47)
    backstage_text = wrap(' ｜ '.join(backstage) or '待定', 2155, backstage_font)
    backstage_height = max(85, backstage_asset.height + 28, text_height(backstage_text, backstage_font) + 28)
    backstage_extra = backstage_height - 85
    footer_shift = delta + backstage_extra
    image = Image.new('RGB', (2600, base_height + footer_shift), NAVY)
    image.paste(source.crop((0, 0, 2600, 1046)), (0, 0))
    right_position = (1859, 1034)
    bottom_position = (0, 3195 + footer_shift)
    image.paste(right_asset, right_position)
    image.paste(bottom_asset, bottom_position)
    draw = ImageDraw.Draw(image)

    # Independent assets contain no old backstage edge or QR separator.

    def text(value, box, size=52, fill='#111111', center=False, bold=False, typeface=None):
        font = ImageFont.truetype(typeface, size) if typeface else body_font(fontfile, size)
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
        logo.thumbnail((300, 248))
        image.paste(logo, (66, 300-logo.height), logo)
        headline_font = brand_face(brand_font, 100)
        cn_font = brand_face(brand_font, 77)
        brand_x, baseline = 420, 180
        english = str(m.get('club_heading', 'Super AI Lab'))
        chinese = str(m.get('club_subheading', '头马俱乐部'))
        cn_box = draw.textbbox((0, 0), chinese, font=cn_font)
        # Anchor on the uppercase S glyph bbox, never the lowercase p descender.
        cap_box = draw.textbbox((0, 0), 'S', font=headline_font)
        english_y = baseline-cap_box[3]
        draw.text((brand_x, english_y), english, font=headline_font, fill=NAVY)
        chinese_y = baseline-cn_box[3]
        draw.text((brand_x+draw.textlength(english, font=headline_font), chinese_y), chinese, font=cn_font, fill=NAVY)
        issue = '第' + str(m['number']) + '期例会'
        issue_font = brand_face(brand_font, 74)
        issue_box = draw.textbbox((0, 0), issue, font=issue_font)
        draw.text((brand_x, 300-issue_box[3]), issue, font=issue_font, fill='#772432')
        theme = semantic_title(m)
        visible_theme = ''.join(theme.split())
        is_short_single = len(visible_theme) <= 7 and '\n' not in theme
        theme_size = 224 if is_short_single else (166 if '\n' in theme else 204)
        theme_face = brand_face(title_font, theme_size)
        theme_width = draw.textbbox((0, 0), theme.replace('\n', ''), font=theme_face, stroke_width=6)[2]
        if is_short_single and theme_width > 1685:
            theme_size = max(204, int(theme_size * 1685 / theme_width))
            theme_face = brand_face(title_font, theme_size)
            theme_width = draw.textbbox((0, 0), theme, font=theme_face, stroke_width=6)[2]
        if theme_width > 1685 or '\n' in theme:
            theme_size = 166
            theme_face = brand_face(title_font, theme_size)
            if '\n' not in theme:
                theme = wrap(theme, 1685, theme_face)
        lines = theme.split('\n')
        line_boxes = [draw.textbbox((0, 0), line, font=theme_face, stroke_width=6) for line in lines]
        line_gap = 5
        block_height = sum(box[3] - box[1] for box in line_boxes) + line_gap * (len(lines) - 1)
        title_y = 330 + (800 - 330 - block_height) / 2
        accent = title_accent or str(m.get('title_accent') or '')
        if not accent:
            accent = next((candidate for candidate in ('AI Skill', '小爱好', 'AI') if candidate in theme), '')
        for line, bounds in zip(lines, line_boxes):
            origin_y = title_y - bounds[1]
            draw.text((90, origin_y), line, font=theme_face, fill=NAVY, stroke_width=6, stroke_fill='#fff7e6')
            if accent and accent in line:
                prefix, _ = line.split(accent, 1)
                draw.text((90 + draw.textlength(prefix, font=theme_face), origin_y), accent, font=theme_face,
                          fill='#772432', stroke_width=6, stroke_fill='#fff7e6')
            title_y += bounds[3] - bounds[1] + line_gap
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
    backstage_top = 3095 + delta
    backstage_bottom = backstage_top + backstage_height
    draw.rounded_rectangle((54, backstage_top, 2547, backstage_bottom), 28, fill='white')
    backstage_icon_y = backstage_top + (backstage_height - backstage_asset.height) // 2
    image.paste(backstage_asset, (72, backstage_icon_y))
    text(backstage_text, (352, backstage_top + 14, 2515, backstage_bottom - 14), 47)
    checks = {}
    for name, fixed, (x, y) in [('right', right_asset, right_position), ('bottom', bottom_asset, bottom_position)]:
        checks[name] = ImageChops.difference(fixed, image.crop((x, y, x + fixed.width, y + fixed.height))).getbbox() is None
    if not all(checks.values()):
        raise ValueError('固定区域像素发生变化：' + str(checks))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    image.save(out / 'agenda.png')
    number = str(result['meeting']['number'])
    image.save(out / f'SAL会单第{number}期.png')
    if hero:
        Image.open(hero).convert('RGB').save(out / f'SAL会单主图第{number}期.png', format='PNG')
    result.update(canvas=list(image.size), fixed_pixels=checks, font=fontfile, brand_font=brand_font,
                  title_font=title_font, flow_font_px=52, extension_px=footer_shift, highlight=highlight,
                  body_font_name=body.getname(), body_font_index=BODY_FACE_INDEX.get(fontfile, 0),
                  brand_font_index=BRAND_FACE_INDEX.get(brand_font, 0),
                  backstage_icon_margins=[backstage_icon_y-backstage_top, backstage_bottom-backstage_icon_y-backstage_asset.height],
                  fixed_assets=['source-r.jpg', 'source-b.jpg', 'muhou.jpg'])
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
    parser.add_argument('--title-accent', default='', help='主题标题中使用头马酒红强调的关键词')
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
            result = render(data, args.hero, args.output_dir, args.font, args.brand_font, args.title_font, args.highlight,
                            title_accent=args.title_accent)
        print(json.dumps({'ok': True, 'facts_sha256': digest, 'result': result}, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
