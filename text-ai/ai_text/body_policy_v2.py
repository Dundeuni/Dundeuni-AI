"""A layout fallback must not become a confident normal result."""
from .encoder_classifier import decide

def decide_body(score,low,high,body):
    result=decide(score,low,high,body.get('poor_confidence',False))
    if body.get('layout_uncertain',False) and result['decision']=='normal':
        result={'decision':'defer','basis':'unverified_body_layout_preserved_ocr'}
    return {**result,'layout_uncertain':body.get('layout_uncertain',False),
            'fallback_used':body.get('fallback_used',False)}
