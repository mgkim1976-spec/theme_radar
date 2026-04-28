# theme_radar — Quickstart

> 본인 정보 소스(추적할 YouTube 채널 리스트)에 맞춰 5분 안에 가동.

## 무엇을 하는 시스템인가

YouTube 투자 채널의 **메소돌로지를 추출·축적**해서:
- 채널별 분석 패턴(LLM 자동 합성)
- 자주 등장하는 테마 사전화
- 종목 매트릭스 (theme × ticker)
- 미래 N일 수익률 검증 (forward validation)
- Obsidian Vault에 wiki 형태로 자동 갱신

자세한 아키텍처는 [SPECIFICATIONS.md](./SPECIFICATIONS.md) 참고.

## 5단계 부트스트랩

### 1. 종속성 설치

```bash
pip install openai yt-dlp youtube-transcript-api finance-datareader \
            rapidfuzz pyyaml requests pandas
```

### 2. 채널 리스트 준비

`my_channels.txt` 파일에 한 줄에 한 채널 (whitespace 구분):

```
# channel_id            subdir         lens       name
UCadSWH0pDXxEatvLHEHCWlg  han_gyunsoo  top-down   한균수의 주식사용설명서
UCR6Z2_Zg3M9lpot90vpZGdw  86bunga      macro      86번가
```

**lens 값** (방법론 분류, theme×stock 가중치 기본값에 영향):
- `macro` — 거시·정책·시장 환경 위주 (기본 가중치 0.6)
- `top-down` — 정책·산업·실적 (기본 0.8)
- `sector` — 산업 사이클 전문 (기본 0.9)
- `bottom-up` — 개별 종목·트레이딩 (기본 1.2)

> 가중치는 매주 forward returns 기반 [auto_tune_weights](./scripts/auto_tune_weights.py)가 자동 재조정합니다 (기본값은 부트스트랩용).

### 3. 프로젝트 초기화

```bash
python3 scripts/init_project.py \
    --channels=my_channels.txt \
    --vault=/path/to/your/obsidian/vault \
    --region=KR
```

**region 값**:
- `KR` — 한국 시장 (KRX 화이트리스트 사용)
- `US` — 미국 시장 (외국주 alias만)
- `OTHER` — 기타

이 명령이 만드는 것:
- `config/channels.yaml` — 채널 리스트
- `config/project.yaml` — vault 경로·region·integrations
- `config/lens_presets.yaml` — lens별 기본값
- `data/youtube/<subdir>/transcripts·extractions_v2/` 디렉터리

### 4. 환경변수 + KRX 화이트리스트

```bash
# .env
OPENAI_API_KEY=sk-...
WEBSHARE_PROXY_URL=http://...:p1@proxy.webshare.io:80
```

KR region이면:
```bash
python3 scripts/build_krx_whitelist.py
```

### 5. 실행

```bash
# 첫 실행 (전체 파이프라인)
bash scripts/pipeline.sh

# 다음 단계가 자동 실행됨:
# 1.  Fetch        YouTube 자막 다운로드
# 2.  Extract      LLM 추출 (~$0.002/영상)
# 3.  Catalysts    catalysts.yaml 자동 변환 (옵션)
# 4.  Reports      methodology, comparative
# 4b. Themes       canonical 사전 + theme×stock 매트릭스 + multi-axis 분류
# 4c. Methodology  채널별 + 비교 LLM 합성
# 5.  Wiki         Obsidian 페이지 갱신
# 5b. Dashboard    신규/가속/소멸 시그널
# 5c. Lint         정합성 자동 검사
# 6.  Validation   가격 데이터 + forward returns + scorecard + 가중치 자동 갱신

# 매일 06:00 자동 실행 (macOS launchd)
bash scheduler/install.sh
```

## 채널 추가 (운영 중)

```bash
# CLI 헬퍼
python3 scripts/add_channel.py UC22자ID my_channel top-down "채널명" --apply

# 또는 init_project로 일괄
python3 scripts/init_project.py --channels=more_channels.txt
```

## 외부 의존성

- **필수**: OpenAI API, FinanceDataReader (가격), Webshare proxy (YouTube IP 차단 우회)
- **선택**: 
  - `geopolitical_investor` 프로젝트 — catalysts.yaml 단방향 작성. 없으면 `config/project.yaml` 의 `integrations.geopolitical_investor.enabled: false` 로 비활성
  - `investment_ontology` 프로젝트 — macro/corporate event vocabulary. 없으면 `vocabulary_snapshots.enabled: false`

## 비용 (기본 4채널 기준)

| 항목 | 월 비용 |
|---|---:|
| Webshare proxy (1GB) | $3.50 |
| OpenAI 추출 (gpt-5.4-nano) | $1-3 |
| Theme 태깅 (LLM, 1회성+증분) | <$0.10 |
| Methodology 합성 (주1) | $0.02 |
| Forward validation | $0 |
| **합계** | **$5-7/월** |

## 다음 읽을 것

- [SPECIFICATIONS.md](./SPECIFICATIONS.md) — 시스템 설계
- [OPERATIONS.md](./OPERATIONS.md) — 운영 가이드
- [CHANGELOG.md](./CHANGELOG.md) — 버전 이력
- Vault 안 `_schema/`, `methodologies/4_lens_framework.md` — 분석 프레임워크
