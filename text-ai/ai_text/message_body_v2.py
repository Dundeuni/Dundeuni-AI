"""Conservative extraction across light/dark captures and partial message crops.

Region misses retain OCR content and mark layout uncertainty. Selection uses
pixels, OCR geometry and structural UI patterns, never risk words, labels,
source identity, human/AI transcriptions or model scores.
"""
import re
import unicodedata

import cv2
import numpy as np
from PIL import Image, ImageOps
from .message_body import regions as light_regions, rect, ordered_text

VERSION = 'adaptive-regions-preserve-ocr-v2'
UI = re.compile(r'^(?:MMS|SMS|(?:Ch?\+?)?채널추가|알림톡차단|수신차단|연락처(?:에)?추가|'
                r'알림톡도착|(?:kakao|akao|cakao|kako)|'
                r'문자메(?:시|지)지(?:[·•-]?SMS)?|채팅이불가능한채널입니다\.?|'
                r'상담원과의?대화가불가능한프로필입니다\.?|메시지를입력하세요|'
                r'문자보내기|챗봇시작|모두보기|전체보기)$', re.I)
TIME = re.compile(r'^(?:(?:오전|오후|AM|PM)\s*)?\d{1,2}[:.]\d{2}(?:\s*(?:AM|PM))?$',re.I)
DATE = re.compile(r'^(?:\((?:오늘|어제|[월화수목금토일]요일)\)\s*)?'
    r'(?:\d{4}[년./-]\s*)?\d{1,2}[월./-]\s*\d{1,2}(?:일)?'
    r'(?:\s*[월화수목금토일]요일|\s*\([월화수목금토일]\))?'
    r'(?:\s*\((?:오늘|어제)\))?(?:\s*(?:오전|오후)?\s*\d{1,2}[:.]\d{2})?\s*[>›]?$')
CAPTION = re.compile(r'^\s*(?:\[\s*그림\s*\d+\s*\]|\(?\s*Figure\s+\d+\s*\)?)', re.I)
SYSTEM_WARNING = ('저장되지않은번호', '스미싱이나피싱에유의')
HEADER_PHONE = re.compile(r'^[<←]?\+?(?:82\s*)?[\d\s()-]{3,20}[>›v√]?$')

def norm(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',value)).strip()

def adaptive_regions(image):
    """Find bounded flat-color panels without restricting bubble colors."""
    width,height = image.size
    scale = min(1.0,480/width)
    pixels = np.asarray(image.resize((round(width*scale),round(height*scale))))
    smooth = cv2.medianBlur(pixels,5).astype(np.int16)
    quant = (smooth//24).astype(np.uint8)
    colors,counts = np.unique(quant.reshape(-1,3),axis=0,return_counts=True)
    candidates = []
    for color,count in sorted(zip(colors,counts),key=lambda row:int(row[1]),reverse=True)[:12]:
        if count < smooth.shape[0]*smooth.shape[1]*.006: continue
        center = color.astype(np.int16)*24+12
        mask = (np.max(np.abs(smooth-center),axis=-1)<=17).astype(np.uint8)
        mask = cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        total,_,stats,_ = cv2.connectedComponentsWithStats(mask,connectivity=8)
        for x,y,w,h,area in stats[1:total]:
            if w < pixels.shape[1]*.14 or h < pixels.shape[0]*.018: continue
            if area < pixels.shape[0]*pixels.shape[1]*.002: continue
            if w > pixels.shape[1]*.97 or area > pixels.shape[0]*pixels.shape[1]*.76: continue
            if area/max(1,w*h) < .48: continue
            candidates.append({'kind':'adaptive_color_panel','box':[x/scale,y/scale,(x+w)/scale,(y+h)/scale],
                               'area':int(area/scale**2),'color':center.tolist()})
    return candidates

def contains(region,line):
    x1,y1,x2,y2 = rect(line)
    cx,cy = (x1+x2)/2,(y1+y2)/2
    a,b,c,d = region['box']
    return a<=cx<=c and b<=cy<=d

def content_hint(text):
    # Single OCR guesses on camera/keyboard/navigation icons do not establish
    # a message region. Short genuine replies are still kept as fallback.
    return (len(re.findall(r'[가-힣]',text))>=2 or bool(re.search(r'[A-Za-z]{3,}|\d{4,}',text)))

def column_order(lines,candidates,width,height):
    # Two tall, horizontally disjoint panels can be joined screenshots. A
    # single full conversation with left/right bubbles does not meet this.
    panels = [r for r in candidates if r['box'][3]-r['box'][1]>.46*height
              and .25*width<r['box'][2]-r['box'][0]<.52*width]
    cut = None
    for left in panels:
        for right in panels:
            if left['box'][2]>=right['box'][0]: continue
            overlap = min(left['box'][3],right['box'][3])-max(left['box'][1],right['box'][1])
            if overlap>.35*height:
                possible=(left['box'][2]+right['box'][0])/2
                if .35*width<possible<.65*width: cut=possible;break
        if cut is not None: break
    if cut is None:
        return ordered_text(lines),False
    left=[line for line in lines if (rect(line)[0]+rect(line)[2])/2<cut]
    right=[line for line in lines if (rect(line)[0]+rect(line)[2])/2>=cut]
    return '\n\n'.join(filter(None,(ordered_text(left),ordered_text(right)))),True

def extract_message_body(image_path,lines):
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
    width,height = image.size
    candidates = light_regions(image)+adaptive_regions(image)
    # Ignore redundant copies of substantially identical masks.
    unique=[]
    for region in candidates:
        if any(max(abs(a-b) for a,b in zip(region['box'],known['box']))<width*.015 for known in unique): continue
        unique.append(region)
    candidates=unique
    inside={i:[r for r in candidates if contains(r,line)] for i,line in enumerate(lines)}
    content_in_region={id(r):sum(contains(r,line) and content_hint(line['text'])
                       and not UI.fullmatch(norm(line['text'])) and not TIME.fullmatch(line['text'].strip())
                       for line in lines) for r in candidates}
    heights=[rect(line)[3]-rect(line)[1] for line in lines if line['text'].strip()]
    median_height=float(np.median(heights)) if heights else height*.03
    has_ui=any(UI.fullmatch(norm(line['text'])) for line in lines)
    region_tops=[r['box'][1] for r in candidates if content_in_region[id(r)]>=1]
    first_region=min(region_tops) if region_tops else None
    def paragraph_date(index):
        box=rect(lines[index]);center=(box[1]+box[3])/2
        return any(j!=index and content_hint(other['text']) and not UI.fullmatch(norm(other['text']))
                   and not DATE.fullmatch(other['text'].strip()) and not TIME.fullmatch(other['text'].strip())
                   and abs(rect(other)[0]-box[0])<width*.075
                   and abs((rect(other)[1]+rect(other)[3])/2-center)<max(3*median_height,height*.04)
                   for j,other in enumerate(lines))
    kept,kept_indices,excluded,fallback=[],[],[],[]
    for index,line in enumerate(lines):
        text=line['text'].strip();value=norm(text)
        x1,y1,x2,y2=rect(line);cy=(y1+y2)/2
        matches=inside[index]
        text_region=any(content_in_region[id(r)]>=1 for r in matches)
        reason=None
        if not text: reason='empty_ocr_detection'
        elif UI.fullmatch(value): reason='structural_ui_template'
        elif CAPTION.match(text): reason='figure_caption_not_message'
        elif re.search(r'(?:©|All\s*Rights\s*Reserved)',text,re.I): reason='copyright_watermark'
        elif any(phrase in value for phrase in SYSTEM_WARNING) and not matches:
            reason='app_unknown_sender_warning'
        elif value in ('유의하세요.','유의하세요') and not matches and cy<height*.5:
            reason='app_warning_continuation'
        elif value in ('메시지신고','신고','편집','HD','LTE','Voice','Ch','Ch+','오전','오후') and not text_region:
            reason='toolbar_or_status_label'
        elif (TIME.fullmatch(text) or (DATE.fullmatch(text) and not paragraph_date(index))) and not text_region:
            reason='timestamp_or_date_separator'
        elif cy<height*.15 and (re.match(r'^(?:SKT|KT|LG)\s+\d{1,2}:\d{2}',text)
                or (not text_region and re.fullmatch(r'\d+\s*%',text))):
            reason='status_bar'
        elif first_region is not None and cy<min(first_region,height*.22) and not text_region and HEADER_PHONE.fullmatch(text):
            reason='sender_toolbar_phone_not_body'
        elif not matches and not re.search(r'[가-힣A-Za-z0-9]',text):
            reason='isolated_nontext_icon'
        elif not matches and len(value)<=2 and re.fullmatch(r'[A-Za-z0-9]+',value) and cy>height*.79:
            reason='isolated_footer_icon'
        if reason:
            excluded.append({'line_index':index,'text':line['text'],'reason':reason})
            continue
        kept.append(line);kept_indices.append(index)
        if not text_region:
            fallback.append(index)
    text,columns=column_order(kept,candidates,width,height)
    fallback_text=ordered_text([lines[index] for index in fallback])
    return {'version':VERSION,'width':width,'height':height,'text':text,'received_text':None,
        'body_lines':kept,'kept_line_indices':kept_indices,'excluded_lines':excluded,'regions':candidates,
        'raw_line_count':len(lines),'kept_line_count':len(kept),
        'poor_confidence':any(line['confidence']<.75 for line in kept),'empty_body':not text.strip(),
        'layout_uncertain':bool(fallback),'fallback_used':bool(fallback),
        'fallback_line_indices':fallback,'fallback_text':fallback_text,
        'raw_ocr_text':'\n'.join(line['text'] for line in lines),
        'column_order_applied':columns,'arbitrary_footer_cutoff':False,
        'selection_inputs':'pixels, OCR geometry and structural UI patterns only; no labels, source IDs, transcriptions or scores',
        'layout_support':'bounded adaptive light/dark regions, joined panels, conservative OCR retention for unknown/cropped layouts',
        'speaker_attribution':'not inferred; all retained sides in visual order'}
