# theme_radar — Operations

## 설치

```bash
# 1. 의존성 (Python)
pip install openai yt-dlp youtube-transcript-api finance-datareader rapidfuzz pyyaml requests

# 2. 환경변수 설정
cp $PROJECT_ROOT/.env.example $PROJECT_ROOT/.env
# .env 편집해서 실제 키 입력

# 3. KRX 종목 화이트리스트 빌드 (1회)
python3 $PROJECT_ROOT/scripts/build_krx_whitelist.py

# 4. launchd agent 설치 (자동 실행 활성화)
bash $PROJECT_ROOT/scheduler/install.sh
```

## 일일 운영

### 자동 (launchd, 매일 06:00)
- `pipeline.sh` 가 자동 실행
- 모든 stage 순차 실행 (idempotent)
- 로그: `logs/pipeline_YYYYMMDD.log`

### 수동 실행

```bash
# 전체 파이프라인
bash $PROJECT_ROOT/scripts/pipeline.sh

# 특정 단계만 (신속 테스트)
bash pipeline.sh --skip-fetch          # 다운로드 스킵
bash pipeline.sh --skip-extract        # 추출 스킵
bash pipeline.sh --skip-catalysts --skip-wiki  # 보고서만 재생성
bash pipeline.sh --dry-run             # plan만 출력

# v1.2 신규 stage 토글
bash pipeline.sh --skip-themes         # theme normalize + pages 스킵
bash pipeline.sh --skip-methodology    # 채널 메소돌로지 LLM 합성 스킵
bash pipeline.sh --skip-dashboard      # 대시보드 갱신 스킵
bash pipeline.sh --force-methodology   # 7일 게이트 무시하고 재합성
```

### Vault 질문 (v1.6 Query)

```bash
# 질문 → 답변 + decisions/{date}_{slug}.md 자동 저장
python3 scripts/query.py "한균수와 86번가의 원전 view 차이?"
python3 scripts/query.py --top=12 "AI 반도체 종목 중 어디가 가장 강한가?"
python3 scripts/query.py --no-save "..."     # 저장 안 함

# 비용 ~$0.003/회 (router + synth)
```

### Vault 정합성 검사 (v1.6 Lint Static)

```bash
# 기본: 콘솔 요약 (broken_link / orphan / schema_drift / dictionary_gap / stale_methodology)
python3 scripts/lint.py

# 발견 항목을 questions/{date}_{cat}_{slug}.md 로 자동 등록
python3 scripts/lint.py --apply

# severity 필터
python3 scripts/lint.py --severity=high
```

매일 06:00 파이프라인의 stage 5c에서 자동 실행 (`--skip-lint` 가능). 자동 등록은 `--lint-apply` 플래그.

### 스키마 변경 후 재추출 (v1.5)

```bash
# 1. dry-run으로 누락 필드 가진 추출 카운트
python3 scripts/reextract_missing_field.py                          # event_type 기본
python3 scripts/reextract_missing_field.py --field=tickers          # 다른 필드
python3 scripts/reextract_missing_field.py --channel=86bunga        # 한 채널만

# 2. 삭제 (--apply 명시 필요)
python3 scripts/reextract_missing_field.py --apply

# 3. 재추출 (idempotent — 삭제된 것만 다시 처리)
bash scripts/pipeline.sh --skip-fetch --skip-catalysts --skip-reports \
    --skip-themes --skip-methodology --skip-wiki --skip-dashboard

# 또는 한 줄로 (Stage 0에서 정리 + Stage 2 재추출 + 후속 stage 모두):
bash scripts/pipeline.sh --reextract-missing=event_type
```

### v1.2/v1.3 모듈 단독 실행

```bash
# canonical theme 사전 (LLM 태깅 + fuzzy, 증분 5초·일회성 ~5분 ~$0.50)
python3 scripts/theme_normalizer.py                      # 증분
python3 scripts/theme_normalizer.py --rebuild            # 처음부터
python3 scripts/theme_normalizer.py --rebuild-tags       # 태그만 재계산
python3 scripts/theme_normalizer.py --no-llm             # 디버그용 (클러스터링 효과 미약)

# theme×stock 매트릭스 (사전 필요)
python3 scripts/theme_to_stock.py

# theme 페이지 자동 생성 (사전 + 매트릭스 활용)
python3 scripts/theme_pages_gen.py

# 대시보드만 재계산
python3 scripts/theme_dashboard.py

# 채널 메소돌로지 합성 (LLM, 7일 게이트)
python3 scripts/methodology_synth.py --force                # 4채널 모두
python3 scripts/methodology_synth.py --channel=86bunga      # 한 채널만

# 채널 cross-comparison 합성 (v1.4, 7일 게이트, ~$0.001)
python3 scripts/comparative_synth.py --force
```

### 즉시 실행 (launchd 큐에 즉시 트리거)

```bash
launchctl start com.theme_radar.daily
# 진행 상황: tail -f logs/pipeline_$(date +%Y%m%d).log
```

## 모니터링

```bash
# 시스템 전체 상태
bash $PROJECT_ROOT/scripts/status.sh

# launchd agent 상태
launchctl list | grep theme_radar

# 최근 로그
tail -f $PROJECT_ROOT/logs/pipeline_$(date +%Y%m%d).log

# 채널별 데이터 카운트
for d in han_gyunsoo 86bunga seo_jaehyung supergaemi; do
  echo "$d: $(ls data/youtube/$d/extractions_v2 2>/dev/null | wc -l) extractions"
done
```

## 트러블슈팅

### IP 차단 (HTTP 429)
- yt_fetch_channel.py가 자동 backoff (60s → 16m)
- 5번 연속 차단 시 자동 중단
- 해결: 1) Webshare proxy 회전 모드 확인 (`-rotate` suffix), 2) jitter 늘림 (4-7초)

### OpenAI API 에러
- pipeline.sh가 stage별로 격리됨 — 추출 실패해도 다른 stage 계속
- 재시도: `bash pipeline.sh --skip-fetch --skip-catalysts --skip-wiki` (추출만)

### 디스크 공간
- 트랜스크립트: ~50KB/영상 (압축 없음)
- 4개 채널 × 1년치 = ~500MB 예상
- 정리: `data/youtube/<channel>/transcripts/` 오래된 것은 archive 가능

### Wiki 동기화 충돌
- iCloud sync 충돌 발생 시: `*.md (1) (2)` 파일 생기면 수동 머지
- 권장: pipeline 실행 중 Obsidian 닫기

### catalysts 자동 머지가 안 됨
- pipeline은 `catalysts_from_youtube.yaml` 만 생성 (별도 파일)
- 본 catalysts.yaml에 머지는 **수동 검토** 후 (안전 목적)
- 머지 스크립트: `youtube_to_catalysts.py` 끝부분에 머지 로직 있음

## 자주 하는 작업

### 새 채널 추가 (v1.4 — 1-step)

```bash
# 1. CLI 헬퍼로 검증·디렉터리 생성·config.py 자동 삽입
python3 scripts/add_channel.py UC<22자> <subdir> <lens> "[채널명]" --apply

# 예시
python3 scripts/add_channel.py UCabcdef...xyz min_baksa bottom-up "민박사 주식끝까지" --apply

# 2. dry-run으로 5채널 인식 확인
bash scripts/pipeline.sh --dry-run

# 3. 다음 06:00 실행 또는 즉시
launchctl start com.theme_radar.daily
```

`<lens>` 는 `macro` / `top-down` / `sector` / `bottom-up` 중 선택. lens만 지정하면 `config.LENS_PRESETS`가 stock_weight·max_videos_per_run 자동 적용.

수동 편집 시: `scripts/config.py` 의 `CHANNELS` dict에만 entry 추가하면 모든 모듈이 자동 흡수 (pipeline.sh가 이를 동적으로 읽음).

### 신호 enum 변경

### 신호 enum 변경

1. `yt_extract_v2.py` 의 `SIGNAL_ENUM` 수정
2. `PROMPT` 의 가이드 텍스트 갱신
3. **모든 채널 추출 결과 폐기** + 재추출 (일관성 위해)
4. 비용: 채널수 × ~1000편 × $0.002 = ~$2/1000편

### 새 lens 프리셋 추가

`scripts/config.py LENS_PRESETS` 에 항목 추가:
```python
LENS_PRESETS = {
    ...,
    "quant": {"stock_weight": 1.0, "max_videos_per_run": 20},
}
```
이후 `add_channel.py ... quant ...` 로 사용.

### 추출 모델 변경

`yt_extract_batch.py` 호출 시 첫 인자:
```bash
python3 yt_extract_batch.py gpt-5-nano       # 더 저렴
python3 yt_extract_batch.py gpt-4.1-nano     # 비교용
```

`pipeline.sh` 의 stage 2 호출도 변경 필요.

## 제거

```bash
# launchd agent만 제거 (데이터·코드 보존)
bash $PROJECT_ROOT/scheduler/uninstall.sh

# 완전 삭제 (주의!)
# rm -rf $PROJECT_ROOT/
```
