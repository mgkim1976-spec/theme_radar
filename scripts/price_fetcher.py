"""price_fetcher — KRX + 주요 외국주 가격 데이터 캐시.

저장: data/prices/{ticker}.csv  (Date, Open, High, Low, Close, Volume)
증분 갱신: 마지막 행 + 1일부터 fetch.

Ticker 형식:
  - KRX: 6자리 코드 (예: '005930')  — FDR이 자동 인식
  - US:  알파벳 심볼 (예: 'TSLA')   — FDR이 yfinance 백엔드로 fetch

사용:
  python3 price_fetcher.py 005930 TSLA NVDA      # 명시
  python3 price_fetcher.py --from-extractions    # 모든 추출 ticker 자동 fetch
  python3 price_fetcher.py --start=2020-01-01 005930  # 시작일 지정
"""
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA, REFERENCE, CHANNELS, channel_paths

PRICES_DIR = DATA / "prices"
ALIAS_PATH = REFERENCE / "ticker_alias.json"

# 외국주 한국어→US ticker (수동 큐레이션)
DEFAULT_FOREIGN_ALIAS = {
    "엔비디아": "NVDA", "NVIDIA": "NVDA", "엔비디아(NVDA)": "NVDA",
    "테슬라": "TSLA",
    "마이크로소프트": "MSFT", "MS": "MSFT", "Microsoft": "MSFT",
    "메타": "META", "메타플랫폼": "META",
    "마이크론": "MU",
    "아마존": "AMZN",
    "팔란티어": "PLTR",
    "TSMC": "TSM", "TSM": "TSM",
    "애플": "AAPL", "Apple": "AAPL",
    "브로드컴": "AVGO",
    "구글": "GOOGL", "Google": "GOOGL",
    "알파벳": "GOOGL", "Alphabet": "GOOGL",
    "알리바바": "BABA",
    "넷플릭스": "NFLX",
    "쿠팡": "CPNG",
    "AMD": "AMD",
    "텐센트": "TCEHY",
    "포드": "F",
    "인텔": "INTC",
    "JD": "JD", "JD닷컴": "JD",
    "디즈니": "DIS",
    "페이팔": "PYPL",
    "스타벅스": "SBUX",
    "나이키": "NKE",
    "맥도날드": "MCD",
    "S&P500": "SPY", "SPX": "SPY", "S&P": "SPY",
    "나스닥": "QQQ", "Nasdaq": "QQQ",
    "다우": "DIA", "Dow": "DIA",
    "Tesla": "TSLA", "Palantir": "PLTR", "Nvidia": "NVDA",
    "오라클": "ORCL", "Oracle": "ORCL",
    "JP모건": "JPM", "JPMorgan": "JPM",
    "월마트": "WMT", "Walmart": "WMT",
    "페이스북": "META", "Facebook": "META",
    "샌디스크": "SNDK", "씨게이트": "STX",
    "마이크론 테크놀로지": "MU", "마이크론테크놀로지": "MU",
    "바이두": "BIDU", "Baidu": "BIDU",
    "버크셔": "BRK-B", "버크셔 해서웨이": "BRK-B",
    "보잉": "BA", "Boeing": "BA",
    "록히드마틴": "LMT",
    "비자": "V", "Visa": "V",
    "마스터카드": "MA",
    "씨티그룹": "C",
    "골드만삭스": "GS",
    "BYD": "BYDDY",
    "샤오미": "XIACY",
    "NIO": "NIO", "니오": "NIO",
    "리비안": "RIVN",
    "퀄컴": "QCOM",
    "AMAT": "AMAT", "어플라이드머티리얼즈": "AMAT",
    "LRCX": "LRCX", "램리서치": "LRCX",
    "ASML": "ASML",
    "ARM": "ARM",
    "스포티파이": "SPOT",
    "AMC": "AMC",
    "바이오엔테크": "BNTX",
    "모더나": "MRNA",
    "화이자": "PFE",
    "존슨앤존슨": "JNJ",
    "P&G": "PG",
    "코카콜라": "KO",
    "펩시": "PEP",
    "엑손모빌": "XOM", "엑슨모빌": "XOM", "엑손 모빌": "XOM",
    "셰브론": "CVX", "쉐브론": "CVX", "쉐브런": "CVX",
    # v3.1 추가 외국주
    "캐터필러": "CAT", "카터필러": "CAT",
    "일라이 릴리": "LLY", "일라이릴리": "LLY", "Eli Lilly": "LLY",
    "텍사스 인스트루먼트": "TXN",
    "퍼스트 솔라": "FSLR", "퍼스트솔라": "FSLR",
    "록히드 마틴": "LMT", "로키드 마틴": "LMT", "로키드마틴": "LMT",
    "도쿄일렉트론": "TOELY",
    "어도비": "ADBE",
    "암젠": "AMGN",
    "길리어드 사이언스": "GILD", "길리어드": "GILD",
    "라인메탈": "RNMBY",
    "혼다": "HMC",
    "암 홀딩스": "ARM",
    "마이크로칩 테크놀로지": "MCHP",
    "트럼프 미디어": "DJT",
    "마이크론 테크놀러지": "MU", "마이크론 테크놀로지": "MU",
    "마이크론 테크": "MU", "마이크로테크놀로지": "MU",
    "마이크로 테크놀로지": "MU", "마이크로 테크놀러지": "MU",
    "마이크로테크놀러지": "MU", "마이크론테크놀러지": "MU",
    "슈퍼마이크로": "SMCI", "슈퍼 마이크로": "SMCI",
    "슈퍼마이크로컴퓨터": "SMCI", "슈퍼 마이크로 컴퓨터": "SMCI",
    "슈퍼 마이크로(슈퍼마이크로)": "SMCI",
    "비디아": "NVDA",
    "코어위브": "CRWV",
    "블룸에너지": "BE",
    "서비스나우": "NOW",
    "달러 제네럴": "DG",
    "베스트바이": "BBY",
    "홈디포": "HD",
    "유나이티드 헬스": "UNH",
    "유나이티드 항공": "UAL",
    "무디스": "MCO",
    "달러트리": "DLTR",
    "월트 디즈니": "DIS",
    "3M": "MMM",
    "JP 모건": "JPM", "JPMorgan": "JPM",
    "골드만 삭스": "GS",
    "뱅크 오브 아메리카": "BAC",
    "모건 스탠리": "MS",
    "어플라이드 머티리얼즈": "AMAT",
    "시어스 테크놀로지": "AMAT",
    "토요타": "TM",
    "유나이티드헬스": "UNH",
    "US 스틸": "X",
    "팔란티어(팔란티어 테크놀로지스)": "PLTR",
    "Palantir Technologies(팔란티어)": "PLTR",
    "MS(마이크로소프트)": "MSFT",
    "Meta Platforms": "META",
    "엔비디아(미국)": "NVDA",
    "프로드컴": "AVGO",  # 브로드컴 오타
    "브러드컴": "AVGO",  # 브로드컴 오타
    "Broadcom": "AVGO",
    "브로드컴(미국)": "AVGO",
    # KR 추가
    "메리츠금융": "008560",
    "포스코 홀딩스": "005490", "포스크홀딩스": "005490", "포스코그룹": "005490",
    "동진세미켐": "005290", "동진세미캠": "005290", "동시세미캠": "005290",
    "동진세미케": "005290",
    "한국투자증권": "071050",
    "아프리카TV": "067160",
    "한미마이크론": "042700",
    "현대미포조선": "298050",
    "에이치피에스피": "403870",
    "S-OIL": "010950",
    "세아베스틸": "001430",
    "현대인프라코어": "267270",  # 현대두산인프라코어 area
    "레인보우로봇": "277810", "레인보우로보틱스": "277810",
    "레고켐바이오": "141080",
    "이오테크니스": "039030",
    "파크시스템즈": "140860",
    "로보스타": "090360",
    "로보티즈": "108490",
    "고스트 로보틱스": "108490",  # 로보티즈와 관련된 매핑
    "이수페타시스": "007660",
    "엘앤에프(에이치디대에너지솔루션)": "066970",
    "리벨리온": "461560",  # 리벨리온은 비상장 — skip ideal
    "오클로": "OKLO",  # 미국 SMR
    "고형": "002820",  # 고형주식 (제일제당 등 가능성, default skip)
    "성지건설": "005980",
    "한라퀘스트": "060980",  # 한라홀딩스 area
    # v2.2 — 외국주 매핑 보강
    "웰스파고": "WFC", "웰스 파고": "WFC", "WFC": "WFC",
    "타겟": "TGT",
    "도요타": "TM",
    "스냅": "SNAP",
    "소프트뱅크": "SFTBY", "소프트뱅크그룹": "SFTBY", "소프트뱅크 그룹": "SFTBY",
    "마벨": "MRVL", "마벨 테크놀로지": "MRVL", "마벨테크놀로지": "MRVL",
    "MP 머티리얼스": "MP", "MP Materials": "MP", "MP머티리얼스": "MP",
    "폭스바겐": "VWAGY",
    "뱅크오브아메리카": "BAC", "Bank of America": "BAC",
    "IBM": "IBM",
    "게임스탑": "GME", "게임스톱": "GME", "GameStop": "GME",
    "코인베이스": "COIN", "Coinbase": "COIN", "COIN": "COIN",
    "Spotify": "SPOT",
    "Meta": "META", "메타플랫폼즈": "META", "메타(페이스북)": "META", "페이스북(메타)": "META",
    "구글(알파벳)": "GOOGL", "알파벳(구글)": "GOOGL",
    "팔란티어 테크놀로지": "PLTR", "Palantir Technologies": "PLTR", "팔란티어 테크놀로지스": "PLTR",
    "딥시크": "BIDU",  # 중국 AI, public proxy로 BIDU
    "Tempus AI": "TEM", "템퍼스 AI": "TEM",
    "MSFT(마이크로소프트)": "MSFT", "Microsoft(마이크로소프트)": "MSFT",
    "Amazon": "AMZN",
    "Sony": "SONY",
    "JP모간": "JPM", "JPMorgan Chase": "JPM", "JPM": "JPM",
    "모건스탠리": "MS",
    "골드만삭스": "GS",
    "노무라": "NMR", "노무라 홀딩스": "NMR",
    "닌텐도": "NTDOY",
    "BMW": "BMWYY",
    "벤츠": "MBGYY",
    "GM": "GM",
    "닛산": "NSANY",
    "FedEx": "FDX", "페덱스": "FDX",
    "AT&T": "T",
    "버라이즌": "VZ",
    "비자": "V",
    "마스터카드": "MA",
    "엑센추어": "ACN",
    "세일즈포스": "CRM", "세일즈포스닷컴": "CRM",
    "AMC": "AMC",
    "월트디즈니": "DIS",
    "스타벅스": "SBUX",
    "맥도날드": "MCD",
    "나이키": "NKE", "NIKE": "NKE",
    "아디다스": "ADDYY",
    "유니레버": "UL",
    "P&G": "PG", "프록터앤갬블": "PG",
    "코카콜라": "KO",
    "펩시": "PEP", "펩시코": "PEP",
    "콘코필립스": "COP",
    "BP": "BP",
    "엑손": "XOM",
    "버크셔": "BRK-B", "버크셔해서웨이": "BRK-B", "버크셔 헤서웨이": "BRK-B",
    "Berkshire Hathaway": "BRK-B",
    "블랙록": "BLK", "블랙락": "BLK",
    "씨티그룹": "C", "시티그룹": "C",
    "ARM": "ARM", "Arm Holdings": "ARM",
    "AT&T": "T",
    "넥스원": "NOC",  # Northrop Grumman? 또는 LIG넥스원? 한국 LIG넥스원 가능성 → 079550로 매핑
    "샤오펑": "XPEV",
    "BIDU(바이두)": "BIDU",
    "BYD": "BYDDY",
    "샤오미": "XIACY",
    "JD": "JD",
    "JD닷컴": "JD",
    "징동닷컴": "JD",
    "디디추싱": "DIDI",
    "텐센트뮤직": "TME", "텐센트 뮤직": "TME",
    "헝다": "EVERY",  # delisted, but track
    "헝다 그룹": "EVERY", "헝다그룹": "EVERY",
    "CATL": "CATL.SZ",  # actually 300750.SZ
    "노보노디스크": "NVO",
    "Glencore": "GLEN.L",
    "라스베가스 샌즈": "LVS",
    "MGM": "MGM",
    "하얏트": "H",
    "힐튼": "HLT",
    "라이브네이션": "LYV",
    "로블록스": "RBLX",
    "Stray Kids": "352820",  # JYP 소속이지만 일단 patent fix
    "로빈후드": "HOOD",
    "리비안": "RIVN", "Rivian": "RIVN",
    "루시드": "LCID",
    "포드": "F",
    "RTX": "RTX",
    "록히드마틴": "LMT", "락히드 마틴": "LMT",
    "에어캐나다": "ACDVF",
    "델타항공": "DAL",
    "아메리칸항공": "AAL",
    "유나이티드항공": "UAL",
    "BBVA": "BBVA",
    "SVB": "SIVBQ",  # delisted
    "신한금융": "SHG",
    "신한금융지주": "SHG",
    "노발티스": "NVS",
    "노바백스": "NVAX",
    "모더나": "MRNA",
    "화이자": "PFE",
    "머크": "MRK",
    "존슨앤드존슨": "JNJ", "존슨앤존슨": "JNJ",
    "바이오엔테크": "BNTX",
    "셀리버리": "268600",
    "동원F&B": "049770",
    "한라홀딩스": "060980",
    "아모레퍼시픽그룹": "002790",
    "더보이즈": "352820",  # 그룹·HYBE 소속
    "엔하이픈": "352820",  # HYBE
    "트와이스": "035900",  # JYP
    "엔시티": "041510",  # SM
    "엑소": "041510",  # SM
    "레드벨벳": "041510",  # SM
    # 한국 추가 통상명
    "포스코케미칼": "003670",  # → 포스코퓨처엠
    "엘앤에프": "066970", "L&F": "066970", "LNF": "066970",
    "현대엔지니어링": "267260",  # HD현대일렉트릭 → 별도 미상장
    "대우조선해양": "329180",  # → HD현대중공업 (합병)
    "삼성엔지니어링": "028050",
    "현대마린엔진": "071970",  # HD현대마린엔진
    "ABL바이오": "298380",
    "한미사이언스": "008930",
    "에이치엘비": "028300", "HLB": "028300",
    "롯데에너지머티리얼즈": "020150",
    "동신장비": "065450",
    "TXT": "352820",  # 투바투, HYBE
    "투모로우바이투게더": "352820",
    "투바투": "352820",
    "위버스": "352820",
    "HYBE": "352820",
    "빅히트": "352820",
    "빅히트엔터테인먼트": "352820",
    "빅히트 엔터테인먼트": "352820",
    "빅히트(빅히트엔터테인먼트)": "352820",
    "신업시스": "060720",  # 임시
    "넥스온": "225570",  # 넥슨게임즈
    "JYP엔터": "035900",
    "JYP 엔터테인먼트": "035900",
    "JYP Entertainment": "035900",
    "JYP엔터테인먼트": "035900",
    "JYP": "035900",
    "SM Entertainment": "041510",
    "SM 엔터테인먼트": "041510",
    "SM 엔터": "041510",
    "에스엠": "041510",
    "YG (엔터)": "122870",
    "와이지": "122870",
    "와이지플러스": "037270",
    "한국전력공사": "015760",
    "메리츠그룹": "008560",
    "메리츠지주": "008560",
    "메리츠금융그룹": "008560",
    "현대미포에이치엔": "298050",  # HD현대미포
    "현대미포": "298050",
    "Wal-Mart": "WMT",
    "S&P 500": "SPY", "S&P500(간접)": "SPY", "미국 S&P500": "SPY", "미국S&P500": "SPY",
    "TSLA": "TSLA",
    "QTUM": "QTUM",
    "EWY": "EWY", "iShares MSCI Korea ETF": "EWY",
    # v2.5 — 추가 외국주
    "SMIC": "0981.HK",
    "메이시스": "M",
    "아이온Q": "IONQ", "IONQ": "IONQ",
    "웨스턴 디지털": "WDC", "Western Digital": "WDC",
    "카니발": "CCL",
    "도요타자동차": "TM",
    "엔비디아(NVDA)": "NVDA",
    "GOOG": "GOOGL", "GOOGL": "GOOGL",
    "AMZN": "AMZN",
    "META": "META",
    "AAPL": "AAPL",
    "Activision Blizzard": "ATVI",  # delisted post-MSFT acq, but historical
    "액티비전 블리자드": "ATVI",
    "엑손": "XOM",
    "QCOM": "QCOM", "퀄컴": "QCOM",
    "BA": "BA", "보잉": "BA",
    "NFLX": "NFLX",
    "PYPL": "PYPL", "페이팔": "PYPL",
    "쉐브론": "CVX",
    "마벨테크": "MRVL",
    "SQ": "SQ", "Square": "SQ", "Block": "SQ",
    "GME": "GME",
    # v2.5 — KR 추가 (KRX 화이트리스트에 별칭 미포함)
    "보스턴 다이내믹스": "005380",  # 현대차 자회사
    "포스코퓨처엠": "003670", "포스코케미칼": "003670",
    "하나엔진": "071970",
    "삼성sds": "018260", "삼성 SDS": "018260",
    "ICTK": "188260",
    "APR": "278470",
    "성광벤드": "014620", "성광밴드": "014620",
    "ST팜": "237690", "에스티팜": "237690",
    "한미약품": "128940",
    "SK이노베이션": "096770",
    "SK텔레콤": "017670",
    "두산": "000150",
    "현대로템": "064350",
    "교보생명": "020560",
    "롯데건설": "003490",  # 일부 지주 매핑 — historical proxy
    "한국항공우주": "047810",
    "삼성SDS": "018260",
    "LG디스플레이": "034220",
}


def load_alias_map() -> dict[str, str]:
    """기본 alias + 사용자 추가 alias 병합."""
    out = dict(DEFAULT_FOREIGN_ALIAS)
    if ALIAS_PATH.exists():
        try:
            user = json.loads(ALIAS_PATH.read_text())
            out.update(user)
        except Exception:
            pass
    return out


def save_alias_map(alias: dict):
    REFERENCE.mkdir(parents=True, exist_ok=True)
    # 사용자 추가분만 저장
    user_only = {k: v for k, v in alias.items() if k not in DEFAULT_FOREIGN_ALIAS}
    ALIAS_PATH.write_text(json.dumps(user_only, ensure_ascii=False, indent=2))


def resolve_ticker(name: str, alias: dict, krx_lookup: dict) -> tuple[str, str] | None:
    """name → (resolved_ticker, market) 또는 None.
    market ∈ {KRX, US, None}"""
    if not name:
        return None
    name = name.strip()
    if name in alias:
        return (alias[name], "US")
    if name in krx_lookup:
        # krx_lookup[name] = '005930' 같은 코드
        return (krx_lookup[name], "KRX")
    return None


def fetch_one(ticker: str, market: str, start: str = "2020-01-01") -> int:
    """단일 ticker fetch + 캐시 갱신. 신규 row 수 반환."""
    import FinanceDataReader as fdr  # lazy import

    PRICES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PRICES_DIR / f"{ticker}.csv"

    # 증분: 기존 last date + 1일부터
    if out_path.exists():
        try:
            import pandas as pd
            existing = pd.read_csv(out_path, parse_dates=["Date"])
            if len(existing) > 0:
                last_date = existing["Date"].max().date()
                start = (last_date + timedelta(days=1)).isoformat()
                if datetime.fromisoformat(start).date() > date.today():
                    return 0  # 이미 최신
        except Exception:
            pass  # 캐시 손상 시 처음부터

    df = fdr.DataReader(ticker, start)
    if df is None or len(df) == 0:
        return 0
    df = df.reset_index()  # Date 컬럼화
    # 중복 제거 후 append
    if out_path.exists():
        try:
            import pandas as pd
            existing = pd.read_csv(out_path, parse_dates=["Date"])
            df = pd.concat([existing, df], ignore_index=True)
            df = df.drop_duplicates(subset=["Date"], keep="last").sort_values("Date")
        except Exception:
            pass
    df.to_csv(out_path, index=False)
    return len(df) if not out_path.exists() else len(df)


def collect_extracted_tickers() -> dict[str, int]:
    """모든 채널 추출에서 ticker_normalized name 빈도."""
    from collections import Counter
    out: Counter = Counter()
    for ch in CHANNELS:
        base = channel_paths(ch)["extractions"]
        if not base.exists():
            continue
        for f in base.glob("*_gpt-5.4-nano.json"):
            try:
                e = json.loads(f.read_text())
            except Exception:
                continue
            for t in e.get("themes", []):
                for tk in t.get("tickers_normalized", []) or []:
                    name = (tk.get("name") or "").strip()
                    if name:
                        out[name] += 1
            for tk in e.get("tickers_mentioned", []) or []:
                name = (tk.get("name_normalized") or tk.get("name") or "").strip()
                if name:
                    out[name] += 1
    return dict(out)


def load_krx_lookup() -> dict[str, str]:
    """{한국명/영문명/alias: 6자리 코드}. 모든 alias를 lookup 키로."""
    p = REFERENCE / "krx_tickers.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except Exception:
        return {}
    out: dict[str, str] = {}
    items = data if isinstance(data, list) else []
    for it in items:
        if not isinstance(it, dict):
            continue
        code = it.get("code") or it.get("Code") or it.get("Symbol")
        if not code:
            continue
        name = it.get("name") or it.get("Name")
        if name:
            out[name] = str(code)
        for a in it.get("aliases", []) or []:
            if a:
                out[a] = str(code)
    # 통상 한국어명 보강 — KRX 공식 alias에 없는 일반 호칭
    KOREAN_COMMON = {
        "네이버": "035420",
        "엔씨소프트": "036570",
        "엔씨": "036570",
        "현대자동차": "005380",
        "현차": "005380",
        "기아": "000270",
        "기아자동차": "000270",
        "삼성SDS": "018260",
        "삼성SDI": "006400",
        "LG화학": "051910",
        "LG생활건강": "051900",
        "LG생건": "051900",
        "LIG넥스원": "079550",
        "삼성바이오로직스": "207940",
        "셀트리온": "068270",
        "포스코": "005490",
        "POSCO": "005490",
        "포스코홀딩스": "005490",
        "현대모비스": "012330",
        "한국전력": "015760",
        "한전": "015760",
        "KT": "030200",
        "SK텔레콤": "017670",
        "SKT": "017670",
        "두산에너빌리티": "034020",
        "효성중공업": "298040",
        "HD현대일렉트릭": "267260",
        "메리츠증권": "008560",
        "메리츠금융지주": "008560",
        "메리츠": "008560",
        "메리츠화재": "000060",
        "SM엔터테인먼트": "041510",
        "에스엠": "041510",
        "JYP엔터테인먼트": "035900",
        "JYP": "035900",
        "하이브": "352820",
        "와이지엔터테인먼트": "122870",
        "YG": "122870",
        "카카오": "035720",
        "카카오뱅크": "323410",
        "카카오페이": "377300",
        "넷마블": "251270",
        "크래프톤": "259960",
        "한화에어로스페이스": "012450",
        "한국항공우주": "047810",
        "KAI": "047810",
        "현대로템": "064350",
        "한화솔루션": "009830",
        "롯데에너지머티리얼즈": "020150",
        "엘앤에프": "066970",
        "에코프로": "086520",
        "에코프로비엠": "247540",
        "포스코퓨처엠": "003670",
        "삼성중공업": "010140",
        "한국조선해양": "009540",
        "HD한국조선해양": "009540",
        "현대중공업": "329180",
        "HD현대중공업": "329180",
        "한미반도체": "042700",
        "DB하이텍": "000990",
        "솔브레인": "357780",
        "동진쎄미켐": "005290",
        "리노공업": "058470",
        "이수페타시스": "007660",
    }
    for k, v in KOREAN_COMMON.items():
        out.setdefault(k, v)
    return out


def main():
    args = list(sys.argv[1:])
    from_extr = "--from-extractions" in args
    args = [a for a in args if a != "--from-extractions"]
    start = "2020-01-01"
    cleaned = []
    for a in args:
        if a.startswith("--start="):
            start = a.split("=", 1)[1]
        else:
            cleaned.append(a)

    alias = load_alias_map()
    krx = load_krx_lookup()

    if from_extr:
        names = collect_extracted_tickers()
        print(f"[price_fetcher] 추출에서 {len(names)} 고유 ticker name 수집")
        # 이름→ticker 매핑
        resolved: dict[str, tuple[str, str]] = {}
        unmapped = []
        for name, count in sorted(names.items(), key=lambda x: -x[1]):
            r = resolve_ticker(name, alias, krx)
            if r:
                resolved[r[0]] = (name, r[1])  # ticker → (one of names, market)
            else:
                unmapped.append((name, count))
        print(f"[price_fetcher] 매핑된 unique ticker: {len(resolved)} "
              f"(KRX: {sum(1 for _,m in resolved.values() if m=='KRX')}, "
              f"US: {sum(1 for _,m in resolved.values() if m=='US')})")
        print(f"[price_fetcher] 매핑 실패: {len(unmapped)} (top 5: "
              f"{[n for n,_ in unmapped[:5]]})")

        # 실제 fetch
        n_ok = 0
        n_fail = 0
        for i, (ticker, (name, market)) in enumerate(resolved.items(), 1):
            try:
                added = fetch_one(ticker, market, start=start)
                n_ok += 1
                if i % 50 == 0:
                    print(f"  ...{i}/{len(resolved)} fetched (ok={n_ok}, fail={n_fail})")
            except Exception as ex:
                n_fail += 1
                if n_fail <= 5:
                    print(f"  ! {ticker} ({name}) 실패: {ex}")
            time.sleep(0.05)
        print(f"[price_fetcher] 완료 — ok={n_ok}, fail={n_fail}")
        return

    if not cleaned:
        print("Usage: price_fetcher.py [TICKER...] [--from-extractions] [--start=YYYY-MM-DD]")
        return

    for ticker in cleaned:
        market = "KRX" if ticker.isdigit() else "US"
        try:
            added = fetch_one(ticker, market, start=start)
            print(f"  ✓ {ticker} ({market}): {added} rows total")
        except Exception as ex:
            print(f"  ✗ {ticker}: {ex}")


if __name__ == "__main__":
    main()
