import re
import unicodedata


def normalize(text: str) -> str:
    text = unicodedata.normalize('NFKC', text)
    return re.sub(r'[\u200b-\u200f\u2060\ufeff]', '', text).strip()


def evaluate_rules(text: str) -> dict:
    text = normalize(text)
    compact = re.sub(r'\s+', '', text).lower()
    evidence = []

    def add(code, points, reason, pattern):
        match = re.search(pattern, compact)
        if match:
            evidence.append(dict(code=code, points=points, reason=reason,
                                 excerpt=match.group(0)))

    add('money_word', 5, '금전 관련 표현', r'송금|입금|이체|계좌')
    request = r'(?:송금|입금|이체)(?:해|하|부탁|요청|바랍|해주세요)|(?:보내|보내주)(?:줘|세요|십시오|시면)|납부(?:해|하|바랍)'
    money_request = bool(re.search(request, compact))
    account = bool(re.search(r'계좌.{0,30}\d[\d-]{7,}|\d{2,6}-\d{2,6}-\d{2,8}', compact))
    if money_request and account:
        evidence.append(dict(code='account_request', points=15,
                             reason='계좌 후보와 금전 전달 요청이 함께 있음', excerpt='계좌/송금 요청 조합'))
    if money_request:
        add('urgent_payment', 15, '시간 압박과 금전 요청', r'지금(?:바로)?|즉시|긴급|급하게|오늘까지|서둘러')
    add('credential_request', 25, '인증정보를 전달하거나 입력하도록 요청',
        r'(?:인증번호|비밀번호|보안카드|otp).{0,30}(?:알려(?:줘|주세요|주십시오)|보내(?:줘|주세요|주십시오)|전달해|입력해|입력하(?!지))')
    add('app_install', 25, '원격제어 또는 APK 설치 유도',
        r'(?:원격(?:제어)?|팀뷰어|anydesk|애니데스크|apk).{0,35}(?:설치해|설치하(?!지)|설치부탁|다운로드해|다운로드하(?!지))')
    if money_request:
        add('family_impersonation', 20, '가족·기기 고장 정황과 금전 요청',
            r'(?:엄마|아빠|아들|딸).{0,60}(?:폰고장|휴대폰고장|액정|새번호|번호바뀌|전화안)')
    urls = re.findall(r'(?:https?://|www\.)[^\s<>]+', text, flags=re.I)
    if urls:
        add('short_url', 10, '단축 URL 포함: 추가 확인 신호', r'(?:bit\.ly|tinyurl\.com|t\.co|vo\.la)/')
        add('lure_link', 15, '혜택·배송·결제 관련 표현과 링크가 함께 있음',
            r'환급금|미수령|지원금|배송주소|주소확인|결제취소')
    return dict(score=min(100, sum(item['points'] for item in evidence)),
                evidence=evidence, urls=urls,
                account_candidate=account)
