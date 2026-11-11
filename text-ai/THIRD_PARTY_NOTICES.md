# 원본 모델·의존성 고지

## SKT A.X-Encoder-base

원본 모델: https://huggingface.co/skt/A.X-Encoder-base

기존 캐시에 보존된 모델카드 revision: 9708f9c404ace91efd25c06fac2d73413616f4ef. 카드에는 Apache 2.0으로 표시되며 라이선스 링크는 https://huggingface.co/skt/A.X-3.1/blob/main/LICENSE 입니다. 원본 카드 사본과 해당 링크의 라이선스 텍스트를 licenses 안에 보존했습니다. 라이선스 텍스트의 다운로드 출처·해시는 NOTICE_PROVENANCE.json에 기록했습니다.

로컬 모델은 encoder 위에 위험 분류·행동 보조 head를 추가하고 별도 자료로 미세 조정한 결과입니다. 이번 포장 작업은 그 가중치를 다시 변경하지 않았습니다. SKT가 이 서비스나 로컬 미세 조정 결과를 보증한다는 의미는 아닙니다.

## PaddleOCR

소프트웨어 출처: https://github.com/PaddlePaddle/PaddleOCR

공식 저장소의 Apache 2.0 라이선스 사본을 동봉했습니다. PaddleOCR 실행 패키지나 OCR 가중치 캐시는 이 폴더에 포함하지 않았습니다. 실제 설치 시 각 의존 패키지와 다운로드하는 모델의 고지를 유지합니다.

## 이 프로젝트 코드와 데이터

팀 자체 코드 전체에 대한 새 오픈소스 라이선스는 이 준비 작업에서 선택하지 않았습니다. 팀 저장소의 라이선스 정책에 맞춥니다. 기반 모델 라이선스가 학습 원문·캡처의 제3자 권리까지 해결하는 것은 아닙니다. 특히 공개 캡처 후보는 학습/평가 파일로 동봉하지 않았습니다.
