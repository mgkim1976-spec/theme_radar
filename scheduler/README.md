# scheduler

> theme_radar 자동화 (macOS launchd)

## 파일

| 파일 | 용도 |
|---|---|
| `com.theme_radar.daily.plist` | launchd 설정 (매일 06:00 실행) |
| `install.sh` | 설치 (~/Library/LaunchAgents/ 에 등록) |
| `uninstall.sh` | 제거 |

## 설치

```bash
bash install.sh
```

## 제거

```bash
bash uninstall.sh
```

## 상태 확인

```bash
launchctl list | grep com.theme_radar.daily
```

## 즉시 실행

```bash
launchctl start com.theme_radar.daily
tail -f $PROJECT_ROOT/logs/pipeline_$(date +%Y%m%d).log
```

## 스케줄 변경

`com.theme_radar.daily.plist` 의 `StartCalendarInterval` 수정 후 재설치:
```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key>
    <integer>6</integer>     <!-- 시간 변경 -->
    <key>Minute</key>
    <integer>0</integer>
</dict>
```

```bash
bash uninstall.sh && bash install.sh
```
