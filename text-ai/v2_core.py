import hashlib
import re
import unicodedata
from urllib.parse import urlparse

def canonical(text):
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'[\u200b-\u200f\u2060\ufeff]', '', text).lower()
    text = re.sub(r'(?:https?://|www\.)\S+', '<url>', text)
    text = re.sub(r'\d+', '<num>', text)
    return re.sub(r'\s+', '', text)

def preprocess(text):
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'[\u200b-\u200f\u2060\ufeff]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def explicit_request(text):
    t = re.sub(r'\s+','',text)
    patterns = [
        r'(인증번호|비밀번호|보안카드|신분증|주민등록).{0,45}(알려줘|알려주(?!지)|보내줘|보내주(?!지)|전달해|입력해|입력하(?!지))',
        r'(원격|팀뷰어|애니데스크|anydesk|apk).{0,45}(설치해|설치하(?!지)|다운로드)',
        r'(송금|입금|이체|돈|상품권|기프트).{0,35}(해줘|해주세요|해주|부탁|보내|구매|요청)',
    ]
    return any(re.search(p,t,re.I) for p in patterns)

def ambiguity_reasons(text):
    t=re.sub(r'\s+','',text)
    reasons=[]
    url=bool(re.search(r'https?://|www\.',t,re.I))
    family=bool(re.search(r'엄마|아빠|딸|아들',t))
    broken=bool(re.search(r'폰.*고장|휴대폰.*고장|액정|새번호|번호바뀌',t))
    if family and broken and not explicit_request(text):
        reasons.append('가족/기기 고장 정황만으로 사기 여부 확인 불가')
    if url and re.search(r'환급|지원금|금융안내|공동인증서|보안업데이트|정부',t) and not explicit_request(text):
        reasons.append('기관/혜택 링크 안내의 진위는 문자만으로 확인 불가')
    return reasons

def selective_metrics(labels, scores, low, high, forced=None):
    forced=forced or [False]*len(labels)
    records=[]
    for y,p,f in zip(labels,scores,forced):
        decision='defer' if f or low<p<high else ('phishing' if p>=high else 'normal')
        records.append((y,decision))
    n0=sum(y==0 for y,_ in records);n1=sum(y==1 for y,_ in records)
    fp=sum(y==0 and d=='phishing' for y,d in records)
    fn=sum(y==1 and d=='normal' for y,d in records)
    d0=sum(y==0 and d=='defer' for y,d in records)
    d1=sum(y==1 and d=='defer' for y,d in records)
    decided0=n0-d0;decided1=n1-d1
    return dict(samples=len(records),normal=n0,phishing=n1,fp=fp,fn=fn,
                deferred_normal=d0,deferred_phishing=d1,
                deferral_rate=(d0+d1)/len(records) if records else 0,
                fpr_all=fp/n0 if n0 else None, fnr_all=fn/n1 if n1 else None,
                fpr_decided=fp/decided0 if decided0 else None,
                fnr_decided=fn/decided1 if decided1 else None,
                phishing_not_alerted=(fn+d1)/n1 if n1 else None)
