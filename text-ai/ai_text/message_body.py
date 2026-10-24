"""Deterministic body extraction for light SMS/Kakao screenshots.

Uses image geometry/color and OCR boxes only. No IDs, labels, transcriptions,
classifier scores, or keyword-based risk decisions enter region selection.
"""
from pathlib import Path
import re
import unicodedata

import cv2
import numpy as np
from PIL import Image, ImageOps

VERSION = 'light-bubble-geometry-v1'

UI_EXACT = re.compile(r'^(?:MMS|SMS|채널\s*추가|알림톡\s*차단|수신\s*차단|연락처에\s*추가|신고|'
                      r'문자\s*메시지|채팅이\s*불가능한\s*채널입니다\.?|오전|오후|[<>×+&]|[Oo])$', re.I)
TIME = re.compile(r'^(?:(?:오전|오후)\s*)?\d{1,2}\s*:\s*\d{2}$')
DATE = re.compile(r'^\d{1,4}(?:년|월|[./-])\s*\d{1,2}(?:월|일|[./-])(?:\s*\d{1,2}일)?\s*(?:[월화수목금토일]요일)?$')

def rect(line):
    points = np.asarray(line['box'])
    return [float(points[:, 0].min()), float(points[:, 1].min()),
            float(points[:, 0].max()), float(points[:, 1].max())]

def is_ui(text):
    value = unicodedata.normalize('NFKC', text).strip()
    return bool(UI_EXACT.fullmatch(value) or TIME.fullmatch(value) or DATE.fullmatch(value))

def regions(image):
    width, height = image.size
    scale = min(1.0, 360 / width)
    small = image.resize((round(width * scale), round(height * scale)))
    pixels = np.asarray(small).astype(np.int16)
    red, green, blue = pixels[..., 0], pixels[..., 1], pixels[..., 2]
    spread = pixels.max(axis=-1) - pixels.min(axis=-1)
    mean = pixels.mean(axis=-1)
    masks = {'gray': (spread < 14) & (mean >= 220) & (mean <= 249),
             'teal': (green > 85) & (blue > 55) & (red < 130) & (green - red > 35),
             'yellow': (red > 175) & (green > 130) & (blue < 145)}
    # White message cards are separable only on a colored screen background.
    gutters = np.concatenate((pixels[:, :max(1, round(small.width * .05))].reshape(-1, 3),
                              pixels[:, -max(1, round(small.width * .05)):].reshape(-1, 3)))
    colored_background = np.mean(gutters.max(-1) - gutters.min(-1) > 16) > .25
    if colored_background:
        edge = max(1, round(small.width * .05))
        colored_rows = np.mean(np.concatenate((spread[:, :edge], spread[:, -edge:]), axis=1) > 16, axis=1) > .3
        # Toolbars/footer can touch a white card. Split them where the colored
        # viewport disappears in the gutters, retaining only card body rows.
        masks['white'] = (mean > 246) & (spread < 12) & colored_rows[:, None]
    candidates = []
    for kind, mask in masks.items():
        mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for x, y, w, h, area in stats[1:count]:
            bounds = [x / scale, y / scale, (x + w) / scale, (y + h) / scale]
            if w < small.width * .16 or h < small.height * .027 or area < small.width * small.height * .003:
                continue
            if w > small.width * .91:
                continue  # full-width toolbar, navigation, or screen background
            if kind == 'white' and (h < small.height * .06 or w / max(1, h) > 5):
                continue
            candidates.append({'kind': kind, 'box': bounds, 'area': int(area / scale ** 2)})
    return candidates

def ordered_text(lines):
    if not lines:
        return ''
    # OCR detectors sometimes return separate words on one visual line.
    # Reconstruct visual rows before joining lines; never guess masked content.
    heights = [rect(line)[3] - rect(line)[1] for line in lines]
    tolerance = max(2.0, float(np.median(heights)) * .45)
    ordered = sorted(lines, key=lambda line: ((rect(line)[1] + rect(line)[3]) / 2, rect(line)[0]))
    rows = []
    for line in ordered:
        center = (rect(line)[1] + rect(line)[3]) / 2
        if rows and abs(center - rows[-1]['center']) <= tolerance:
            rows[-1]['lines'].append(line)
        else:
            rows.append({'center': center, 'lines': [line]})
    return '\n'.join(' '.join(line['text'].strip() for line in sorted(row['lines'], key=lambda line: rect(line)[0])) for row in rows)

def extract_message_body(image_path, lines):
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
    width, height = image.size
    candidates = regions(image)
    footer = height
    bottom = np.asarray(image.resize((360, max(1, round(height * 360 / width))))).astype(np.int16)
    band = bottom[-max(5, round(bottom.shape[0] * .05)):]
    means, spreads = band.mean(-1), band.max(-1) - band.min(-1)
    paper = (means > 235) & (spreads < 14)
    ink = (means > 90) & (means < 230) & (spreads < 18)
    icon_zones = [np.count_nonzero(ink[:, int(360*(x-.07)):int(360*(x+.07))]) >= 4 for x in (.18, .5, .82)]
    has_android_navigation = float(paper.mean()) > .91 and sum(icon_zones) >= 2
    for line in lines:
        box = rect(line)
        if box[1] > height * .65 and re.search(r'채팅이\s*불가능한|문자\s*메시지', line['text']):
            footer = min(footer, box[1] - height * .008)
    # Separate the central rounded composer from pale source annotations.
    bmean, bspread = bottom.mean(-1), bottom.max(-1)-bottom.min(-1)
    composer_mask = ((bmean >= 231) & (bmean <= 251) & (bspread < 15)).astype(np.uint8)
    composer_mask[:round(bottom.shape[0] * .68)] = 0
    composer_mask = cv2.morphologyEx(composer_mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(composer_mask, connectivity=8)
    for x, y, w, h, area in stats[1:count]:
        if (x > 360*.28 and x+w < 360*.96 and w > 360*.20
                and h < bottom.shape[0]*.17 and h > bottom.shape[0]*.025
                and h/max(1,w) < .65 and area/max(1,w*h) > .45):
            footer = min(footer, y * width / 360)
    footer_fallback = has_android_navigation and footer == height
    if footer_fallback:
        footer = height * .84
    candidates = [region for region in candidates if region['box'][1] < footer]
    messages, excluded = [], []
    grouped = {}
    for index, line in enumerate(lines):
        x1, y1, x2, y2 = rect(line)
        cx, cy = (x1+x2)/2, (y1+y2)/2
        reason = 'screen_ui_text' if is_ui(line['text']) else 'input_or_navigation_area' if cy >= footer else None
        inside = [region for region in candidates if region['box'][0] <= cx <= region['box'][2]
                  and region['box'][1] <= cy <= min(footer, region['box'][3])]
        if not inside and reason is None:
            reason = 'outside_detected_message_region'
        if reason:
            excluded.append({'line_index': index, 'text': line['text'], 'reason': reason})
            continue
        # A white notification card can contain colored action buttons.
        white = [region for region in inside if region['kind'] == 'white']
        region = min(white or inside, key=lambda item: item['area'])
        identity = tuple(region['box'])
        if identity not in grouped:
            grouped[identity] = {'region': region, 'lines': [], 'line_indices': []}
        grouped[identity]['lines'].append(line)
        grouped[identity]['line_indices'].append(index)
    for item in sorted(grouped.values(), key=lambda item: (item['region']['box'][1], item['region']['box'][0])):
        region = item['region']
        role = 'sent' if region['kind'] in ('teal', 'yellow') else 'received'
        messages.append({'role': role, 'role_basis': 'bubble color heuristic, not verified sender identity',
                         'box': region['box'], 'text': ordered_text(item['lines']),
                         'lines': item['lines'], 'line_indices': item['line_indices']})
    kept = [line for message in messages for line in message['lines']]
    text = '\n\n'.join(message['text'] for message in messages)
    received_text = '\n\n'.join(message['text'] for message in messages if message['role'] == 'received')
    return {'version': VERSION, 'width': width, 'height': height, 'footer_y': footer,
            'android_navigation_detected': bool(has_android_navigation),
            'conservative_footer_fallback': bool(footer_fallback),
            'regions': candidates, 'messages': messages, 'text': text, 'received_text': received_text,
            'body_lines': kept, 'excluded_lines': excluded, 'raw_line_count': len(lines),
            'kept_line_count': len(kept), 'poor_confidence': any(line['confidence'] < .75 for line in kept),
            'empty_body': not text.strip(), 'selection_inputs': 'pixels, OCR boxes and UI-only patterns; no label or score',
            'layout_support': 'light SMS bubbles and light Kakao notification cards; heuristic prototype'}
