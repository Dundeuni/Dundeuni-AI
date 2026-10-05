# Dundeuni AI

스마트폰 사용 중 발견한 이미지의 AI 생성 여부와 변조 신호를 분석하는 디지털 안전 서비스 **든든이**의 AI 파트 저장소입니다.

```text
사용자가 이미지 선택 또는 화면 캡처 → BE를 통한 분석 요청
→ AI 생성 탐지·변조 탐지 → 모델별 결과·의심 영역·분석 한계 반환
```

AI 생성·변조 분석과 이미지 내용의 사기 위험 판단은 별도 문제입니다. 현재 이미지 분석 작업은 AI 생성 여부와 변조 신호 평가에 집중합니다.

## 기본 구조

```text
src/                        AI 분석 기능 코드
├── common/                 공통 결과 형식, 오류 처리
├── config/                 모델 경로와 실행 환경 설정
└── domains/
    └── image-analysis/     AI 생성 탐지, 변조 탐지, 판정 처리
scripts/                    데이터 준비, 모델 추론, 평가 실행
requirements/               모델별 Python 설치 환경
tests/                      입력 처리, 판정 기준, 평가 계산 검증
reports/                    테스트 결과, 오류 분석, 모델 선정 근거
handoff/                    실험 재현 안내와 고정 입력 목록
docs/api/                   BE와 합의할 AI 요청·응답 문서
.github/                    이슈, PR 템플릿과 라벨 정의
```

## 기술 스택

- Python, PyTorch
- NumPy, Pillow, scikit-learn
- AI 생성 탐지 비교 후보: B-Free
- 변조 탐지 비교 후보: TruFor, Mesorch, Mesorch-P
- NVIDIA CUDA 기반 GPU 추론
- BE와의 요청·응답 계약을 통한 AI 분석 연동

후보 모델은 비교·검증 대상이며 서비스 적용 모델로 확정된 것은 아닙니다. 모델별 의존성을 분리하고, AI 서버 프레임워크와 배포 방식은 연동 요구사항을 정한 뒤 선정합니다.

## 시작하기

```bash
git clone https://github.com/Dundeuni/Dundeuni-AI.git
cd Dundeuni-AI
```

- [팀원용 실험 재현 가이드](handoff/TEAM_REPRODUCIBILITY_20261004.md): 환경·고정 입력·가중치 확보와 실행 명령
- [v0.1 B-Free 결과](reports/BFREE_ORIGINAL_RESULTS_20261002.md) / [v0.1 TruFor 결과](reports/ORIGINAL_BASELINE_RESULTS_20261001.md) / [v0.2 결과](reports/FOLLOWUP_BASELINE_RESULTS_20261004.md)
- 모델 실행에는 해당 모델의 공식 코드·가중치와 호환되는 Python 환경이 필요합니다.
- 실험에는 고정된 평가 이미지·정답·분할 목록이 추가로 필요합니다.
- 이미지·가중치·가상환경·대용량 추론 결과는 Git에서 제외합니다.

기존 검증 실험은 수행했으나 서비스에 적용할 모델·판정 기준·지원 입력 범위는 아직 확정하지 않았습니다.

## 협업

BE·FE와 같은 방식으로 이슈를 생성하고 작업 브랜치와 PR을 통해 변경 사항을 공유합니다.

```text
main: 검토된 배포·데모 기준
dev: 개발 통합
feature/*, fix/*, chore/*, docs/*, refactor/*: dev를 대상으로 PR
experiment/*: 모델 비교·검증 작업, dev를 대상으로 PR
```

- 작업 브랜치에는 이슈 번호를 포함합니다.
- 커밋과 PR 제목은 영문 타입과 한글 설명을 사용합니다.
- 일반 작업은 최소 1명 승인 후 Squash merge합니다.
- 모델·전처리·판정 기준 변경은 테스트 결과와 함께 기록합니다.
- AI 입력·출력이 바뀌면 FE·BE 담당자와 공유합니다.


## MVP 범위

우선 이미지 입력에 대한 AI 생성 탐지·변조 탐지 성능을 검증하고, 서비스에 적용할 모델과 판정 기준을 검토합니다. 평가 결과를 바탕으로 처리 상태·모델별 판정·판별 보류·지원 입력 범위를 정의하며, 변조 위치 표시의 적용 가능성도 확인합니다.

AI 생성 탐지와 변조 탐지 결과는 구분하여 제공합니다. 모델 점수를 실제 확률로 단정하지 않으며, 낮은 점수도 원본 인증을 의미하지 않습니다. 변조 탐지 결과만으로 AI를 사용한 편집인지 확정하지 않습니다.

이미지 내용의 사기 여부 판단, 영상·통화 분석, 모델 학습·파인튜닝과 서비스 배포는 현재 이미지 Baseline 검증 범위에 포함하지 않습니다.
