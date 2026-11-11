"""Text-only message spans; no risk words, label lookups or sender guesses."""
import re
import unicodedata

VERSION = 'text-spans-context-v1'
ACTION_NAMES = ['money_or_voucher', 'sensitive_information', 'app_installation',
                'remote_permission_or_id', 'link_or_callback', 'financial_document_or_account']

def normalize(text):
    text = unicodedata.normalize('NFKC', text or '')
    text = re.sub(r'[\u200b-\u200f\u2060\ufeff]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def message_spans(text, limit=240, context_chars=90):
    """Partition all normalized text; short captures stay whole. Roles unknown.

    Cuts use whitespace close to the limit, never keyword/speaker/risk rules.
    A long indivisible token (e.g. URL) remains intact instead of being dropped.
    """
    text = normalize(text)
    if not text:
        return []
    result, start = [], 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            split = text.rfind(' ', start + limit // 2, end + 1)
            if split < 0:
                split = text.find(' ', end)
            end = split if split >= 0 else len(text)
        focus = text[start:end].strip()
        context = text[max(0,start-context_chars):start].strip()
        if focus:
            result.append({'focus': focus, 'context': context,
                'input_text': format_input(focus, context), 'start': start, 'end': end,
                'speaker': 'unknown', 'boundary_basis': 'text_length_whitespace_not_verified_message_turn'})
        start = end + (1 if end < len(text) and text[end] == ' ' else 0)
    assert normalize(' '.join(r['focus'] for r in result)) == text
    return result

def format_input(focus, context=''):
    return '[앞선 문맥] ' + (normalize(context) or '없음') + ' [현재 메시지] ' + normalize(focus)

def weak_action_labels(text):
    """Auxiliary training annotations ONLY. Never used to change predictions.
    Phrase presence is weak evidence of topic/action, not authenticated intent.
    """
    t = re.sub(r'\s+', '', normalize(text)).lower()
    patterns = [r'송금|입금|이체|상품권|기프트|돈.{0,12}(보내|빌려|갚)',
                r'비밀번호|비번|인증번호|주민등록|신분증|보안카드|카드.{0,12}(사진|앞뒤)',
                r'앱|어플|apk|설치|다운로드|다운받|play\.google|appstore',
                r'원격|팀뷰어|teamviewer|anydesk|권한|허용|동의|아이디|started|연결번호',
                r'https?://|www\.|\.(?:com|kr|net|xyz|me|wtf|art|hair|la|ly|gd|su)/?|연락|문의|전화|링크|접속',
                r'계좌|서류|재직|소득|대출|증명서|등록|신청|보상|환급']
    return [int(bool(re.search(p,t))) for p in patterns]

def visible_request(text):
    t = re.sub(r'\s+', '', normalize(text)).lower()
    return bool(re.search(r'설치|다운로드|알려|보내|송금|이체|입력|구매|구입|허용|동의|연결|클릭|확인|문의|접속|연락|부탁|인증|번호|계좌|신청|청구|통지|보고서', t))
