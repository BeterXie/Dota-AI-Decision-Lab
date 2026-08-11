# Dota AI Decision Lab — TI 2026 快速落地开发文档

**目标：在 TI 2026 开赛前形成可运行的独立系统闭环**  
**运行模式：Shadow Decision（只记录建议，不自动执行交易）**  
**项目边界：Standalone，新项目运行时不依赖旧 `dota2-predictor`**

---

## 0. 文档依据与已确认事实

本设计基于现有讨论以及两份实测 HAR：

- DLTV：`3566a1bc-8851-47ab-986d-150cdc99461f.har`
- RayBet：`c2e7d4ab-21b1-46e3-9844-9248f7f4f496.har`

### 0.1 DLTV HAR 已确认

1. 单场页面会请求：

```text
GET /live/{valve_match_id}.json
```

样本：

```text
/live/8940730389.json
```

2. DLTV 使用 Socket.IO / Engine.IO 4：

```text
/socket.io/?EIO=4&transport=polling
wss://dltv.org/socket.io/?EIO=4&transport=websocket&sid=...
```

3. 页面自身监听：

```text
__nd2_match_{valve_match_id}
__nd2_odds_{dltv_series_id}
```

同时 Socket 中还能看到：

```text
__nd2_series
```

以及其他正在进行比赛的 `__nd2_match_*`，说明一条连接可以收到多场比赛的广播数据。

4. `/live/{match_id}.json` 样本包含：

```text
match_id
radiant_score
dire_score
first_blood
radiant_lead
game_time
is_picks_ended
draft_supreme_complete
fast_picks
charts
full_stats
players
live_league_data
db
```

5. `players[]` 样本中包含：

```text
account_id
hero_id
team_slot
team
```

样本每边的 `team_slot` 完整覆盖 1–5，因此它可以作为第一版 Hero + Position 识别的主路径。但在工程上仍要对更多比赛做一致性验证，不能把一场样本直接当成永久协议保证。

6. 样本中的 `live_league_data.stream_delay_s = 900`。同一时刻根级字段 `game_time / score / radiant_lead` 已经更新，而 `full_stats` 的个人统计仍大量为 0。后续 `__nd2_match_*` Socket 消息中没有携带 `players/full_stats/live_league_data`。因此第一版必须把：

```text
DLTV_FAST
```

和：

```text
DLTV_DELAYED_DETAIL
```

分开处理。

7. 当前比赛的 Socket transport 大约每几秒广播一次，但很多消息是重复状态；有效 `game_time / score / radiant_lead` 更新比 transport 粒度粗得多。因此不能把“5 秒收到一条消息”理解为“比赛状态每 5 秒更新”。

### 0.2 RayBet HAR 已确认

1. 当前网页使用 HTTP Host：

```text
https://iminfo.esportsworldlink.com/v2
```

主要接口：

```text
/v2/game
/v2/match
/v2/odds
```

2. 当前网页使用 SocketCluster：

```text
wss://cfsocket.365raylinks.com/socketcluster/
```

握手后订阅：

```json
{"event":"#subscribe","data":{"channel":"match"},"cid":2}
```

3. 服务端在 `match` channel 发布赔率增量：

```json
{
  "event": "#publish",
  "data": {
    "channel": "match",
    "data": {
      "source": "odds",
      "odds": [
        {
          "id": 75240285,
          "match_id": 38423651,
          "odds": "3.32",
          "last_update": "1786467681",
          "status": 1
        }
      ]
    }
  }
}
```

4. `/v2/odds?match_id=...` 是赔率元数据 Bootstrap。它能够把 `odds_id` 映射到：

```text
match_stage
group_short_name
team_id
team name
match_id
status
price
```

例如样本中：

```text
75240285 → Map r2 Winner → Yellow Submarine
75240286 → Map r2 Winner → Zero Tenacity
```

5. RayBet Socket 的 `last_update` 是 Unix 秒级时间戳。HAR 中接收时间与 `last_update` 通常很接近，因此应同时保存：

```text
provider_updated_at
socket_received_at
stored_at
```

6. RayBet 当前样本没有发现可靠的 Dota `game_time_seconds` 字段。因此 RayBet 与 DLTV 的比赛时钟不能直接字段对字段对齐，必须做 Timeline Calibration。

7. RayBet 的 `status` 数值存在多个取值，但本 HAR 还不足以可靠定义每个数字的业务语义。第一版数据库必须保留 `raw_status`，归一化状态必须在完成样本验证后再固定。

### 0.3 当前仍未解决、必须通过运行时验证的问题

两份 HAR 的时间窗口没有真正重叠，因此目前不能计算真实的：

```text
RayBet ↔ DLTV relative lag
```

这不是文档设计问题，而是上线后第一个必须自动测量的运行时指标。

---

# 1. 项目目标

本项目是一个：

> **Dota 2 市场情报、阵容情报、历史情报、Live 状态与多 AI 决策统一编排平台。**

不是重新开发一个 Dota 数据网站，也不是重新实现 STRATZ/OpenDota，更不是把旧项目拼接到新项目。

系统最终要完成：

```text
RayBet
  ↓
比赛发现 + 实时赔率

DLTV
  ↓
Valve Match ID + Draft + Hero/Player/Position + Live Team State

STRATZ / OpenDota
  ↓
Team / Player / Player×Hero Historical Features

Draft Intelligence
  ↓
分钟级 R.O.S.H. Curve

Temporal Aligner
  ↓
DecisionSnapshot @ exact T

GPT / Claude / Gemini / ...
  ↓
独立 Decision

Future Odds + Map Result
  ↓
Evaluation
```

---

# 2. 项目不可破坏的原则

## 2.1 Standalone

新项目自己完成：

```text
RayBet HTTP
RayBet WebSocket
比赛发现
赔率时间序列
DLTV Socket.IO
DLTV Draft/Live
STRATZ 历史同步
分钟级 Draft Intelligence
历史特征
DecisionSnapshot
AI 调用
Evaluation
```

旧项目仅作为参考实现，不是运行依赖。

## 2.2 Raw First

所有第三方数据先写 Raw，再 Normalize：

```text
Provider Raw
   ↓
Parser Version
   ↓
Normalized Observation
```

不能只保存当前值。

## 2.3 Append Only

赔率、Live 状态、Historical Feature、Draft Curve、AI Decision 全部采用时间序列/快照方式。

禁止：

```text
UPDATE current_score = ...
```

代替历史。

## 2.4 Unknown != Zero

缺失数据：

```text
null / UNKNOWN
```

绝不能默认：

```text
0
```

## 2.5 Same Snapshot For Every AI

所有模型必须看到同一个 `snapshot_hash`。

## 2.6 Unsafe Live Data Cannot Become Decision Evidence

如果 DLTV 与 RayBet 时间同步无法证明安全：

```text
LIVE → POST_DRAFT
```

而不是继续让 AI 使用可能错位的 Live 数据。

---

# 3. 推荐技术栈

## Backend

```text
Python 3.11+
FastAPI
Pydantic v2
SQLAlchemy 2
Alembic
PostgreSQL 16+
asyncio
httpx
websockets
python-socketio[asyncio_client]
```

## Frontend

TI 前建议尽量轻：

```text
FastAPI + Jinja/HTMX
```

或如果团队已经习惯 React：

```text
React + Vite
```

不要为了 Dashboard 引入复杂前端架构。

## Optional

```text
Redis
```

第一版不是必须。单实例情况下可直接 PostgreSQL + asyncio Queue。

---

# 4. 推荐目录

```text
dota-ai-decision-lab/

app/
  main.py
  config.py

  domain/
    identity.py
    market.py
    draft.py
    live.py
    history.py
    snapshot.py
    decision.py

  providers/
    raybet/
      http.py
      socket.py
      parser.py
      models.py

    dltv/
      bootstrap.py
      socket.py
      parser.py
      reducer.py

    stratz/
      client.py
      draft_queries.py
      history_queries.py

    opendota/
      client.py

  identity/
    resolver.py
    aliases.py

  market/
    discovery.py
    odds_registry.py
    collector.py
    fair_probability.py
    trajectory.py

  draft/
    identity.py
    engine.py
    minute_curve.py
    features.py

  history/
    team.py
    player.py
    player_hero.py
    sync.py

  live/
    collector.py
    synchronizer.py
    quality.py

  snapshots/
    builder.py
    gates.py
    canonical_json.py

  ai/
    schema.py
    prompt.py
    coordinator.py
    providers/
      openai.py
      anthropic.py
      gemini.py

  evaluation/
    future_odds.py
    settlement.py
    metrics.py

  runtime/
    supervisor.py
    health.py

  web/
    api.py
    dashboard.py

migrations/
tests/
tools/
  record_timeline.py
  dltv_probe.py
  raybet_probe.py
```

---

# 5. 配置

所有 Provider Host 都配置化。

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str

    raybet_info_base_url: str = "https://iminfo.esportsworldlink.com/v2"
    raybet_socket_url: str = "wss://cfsocket.365raylinks.com/socketcluster/"
    raybet_dota_game_id: int = 151

    dltv_base_url: str = "https://dltv.org"

    stratz_token: str | None = None

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None

    # Initial safety thresholds; must be configurable and later calibrated.
    live_sync_safe_seconds: float = 3.0
    live_sync_caution_seconds: float = 8.0

    ai_checkpoint_minutes: str = "5,10,15,20,25,30,35,40,45,50,55,60"
```

`.env`：

```dotenv
DATABASE_URL=postgresql+asyncpg://...
STRATZ_TOKEN=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...
```

---

# 6. Canonical Identity

Provider ID 绝不能成为系统全局 ID。

需要：

```text
CanonicalEvent
CanonicalSeries
CanonicalMap
CanonicalTeam
CanonicalPlayer
CanonicalHero
```

## 6.1 Provider Mapping

```text
provider_team_mapping
provider_match_mapping
provider_player_mapping
```

例如：

```text
RayBet Match ID 38423651
        ↕
Canonical Series
        ↕
DLTV Series ID 427609
        ↕
Valve Match ID 8940756672
```

真正 authoritative map identity 优先使用 Valve Match ID，一旦 DLTV 暴露该 ID，就写入 Canonical Map。

## 6.2 Match Resolver

匹配顺序：

```text
1. 已有 explicit provider mapping
2. Valve Match ID
3. 双方 Canonical Team + Event + Map/Series context
4. Team aliases + start-time window
5. Ambiguous → 不强行匹配
```

不允许只靠 fuzzy team name 强制映射。

---

# 7. RayBet Provider

## 7.1 RayBet HTTP

用途：

```text
比赛发现
赔率完整 Bootstrap
赔率 ID 元数据
赛事/队伍信息
```

接口：

```python
class RayBetHttpClient:
    async def get_games(self): ...
    async def get_matches(self, match_type: int, page: int = 1): ...
    async def get_odds(self, match_id: int): ...
```

实现：

```python
import httpx


class RayBetHttpClient:
    def __init__(self, base_url: str):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=8.0,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://www.ray086.com",
                "Referer": "https://www.ray086.com/",
            },
        )

    async def get_matches(self, match_type: int, page: int = 1) -> dict:
        r = await self._client.get(
            "/match",
            params={"match_type": match_type, "page": page},
        )
        r.raise_for_status()
        return r.json()

    async def get_odds(self, match_id: int) -> dict:
        r = await self._client.get("/odds", params={"match_id": match_id})
        r.raise_for_status()
        return r.json()
```

> Header 不要过拟合 HAR。只保留实际需要的最小集合，并通过集成测试验证匿名访问是否足够。

## 7.2 Match Discovery

当前 HAR 中出现 `match_type=0/1/2`。不要把数字语义硬编码成永远正确的业务定义。

业务判断使用：

```text
game_id == 151
match.status
start_time
series score
WebSocket 是否持续出现该 match_id
```

Discovery 输出：

```python
class ProviderMatch(BaseModel):
    provider_match_id: int
    tournament_id: int | None
    tournament_name: str | None
    team_a_id: int
    team_a_name: str
    team_b_id: int
    team_b_name: str
    round: str | None
    provider_status: int | None
    scheduled_at: datetime | None
    observed_at: datetime
```

## 7.3 Odds Registry

HTTP `/odds` 建立：

```text
odds_id → market metadata
```

模型：

```python
class OddsMeta(BaseModel):
    odds_id: int
    match_id: int
    team_id: int | None
    team_name: str | None
    group_short_name: str | None
    match_stage: str | None
    raw_status: int | None
```

Registry 必须支持热更新，因为新 Map / 新 Market 会产生新 `odds_id`。

## 7.4 RayBet SocketCluster

建议第一版直接实现 protocol，而不是启动浏览器。

```python
import asyncio
import json
import websockets


class RayBetSocketClient:
    def __init__(self, url: str):
        self.url = url

    async def run(self, on_publish):
        while True:
            try:
                async with websockets.connect(
                    self.url,
                    origin="https://www.ray086.com",
                    ping_interval=None,
                ) as ws:
                    await ws.send(json.dumps({
                        "event": "#handshake",
                        "data": {"authToken": None},
                        "cid": 1,
                    }))

                    await self._wait_for_rid(ws, 1)

                    await ws.send(json.dumps({
                        "event": "#subscribe",
                        "data": {"channel": "match"},
                        "cid": 2,
                    }))

                    await self._wait_for_rid(ws, 2)

                    async for raw in ws:
                        if raw == "#1":
                            await ws.send("#2")
                            continue

                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        if msg.get("event") != "#publish":
                            continue

                        data = msg.get("data", {})
                        if data.get("channel") != "match":
                            continue

                        await on_publish(data.get("data", {}))

            except Exception:
                await asyncio.sleep(1.5)

    async def _wait_for_rid(self, ws, rid: int):
        while True:
            raw = await ws.recv()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("rid") == rid:
                return
```

`on_publish`：

```python
async def handle_raybet_publish(payload: dict):
    if payload.get("source") != "odds":
        return

    for item in payload.get("odds", []):
        await raw_store.save("RAYBET_SOCKET_ODDS", item)
        await odds_reducer.apply_delta(item)
```

## 7.5 OddsObservation

```python
class OddsObservation(BaseModel):
    provider: Literal["raybet"] = "raybet"

    provider_match_id: int
    odds_id: int

    canonical_series_id: UUID | None
    canonical_map_id: UUID | None

    market_type: str | None
    match_stage: str | None

    selection_team_id: UUID | None
    price: Decimal

    raw_status: int | None
    normalized_status: str | None

    provider_updated_at: datetime | None
    received_at: datetime
    stored_at: datetime
```

## 7.6 Fair Probability

对于二元 Winner Market：

```python
def remove_vig(odds_a: float, odds_b: float) -> tuple[float, float]:
    ia = 1.0 / odds_a
    ib = 1.0 / odds_b
    total = ia + ib
    return ia / total, ib / total
```

保存：

```text
raw odds
raw implied probability
fair probability
overround
```

---

# 8. DLTV Provider

## 8.1 两层数据源

必须明确区分：

```text
DLTV_BOOTSTRAP
DLTV_FAST_SOCKET
DLTV_DELAYED_DETAIL
```

### Bootstrap

```text
GET /live/{valve_match_id}.json
```

主要用于：

```text
Draft identity
Player account_id
hero_id
team_slot
team
fast_picks
历史 charts
live_league_data 元信息
```

### Fast Socket

```text
__nd2_match_{valve_match_id}
```

当前样本可用：

```text
game_time
radiant_score
dire_score
radiant_lead
first_blood
charts
fast_picks
...
```

### Delayed Detail

`full_stats/live_league_data.scoreboard` 可以包含个人详细数据，但当前样本暴露了 `stream_delay_s=900`，因此其数据不能默认作为当前市场状态证据。

## 8.2 Socket.IO Client

使用官方协议库，不需要浏览器：

```python
import socketio


class DltvSocketClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,
            reconnection_delay=1,
        )

    async def connect(self):
        await self.sio.connect(
            self.base_url,
            transports=["websocket", "polling"],
            socketio_path="socket.io",
        )

    def watch_match(self, valve_match_id: int, callback):
        event = f"__nd2_match_{valve_match_id}"
        self.sio.on(event, callback)

    def watch_series(self, callback):
        self.sio.on("__nd2_series", callback)
```

如果 Python Socket.IO 客户端在某些网络下不稳定，保留 polling fallback。

## 8.3 Bootstrap Client

```python
class DltvBootstrapClient:
    def __init__(self, base_url: str):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=8.0)

    async def get_live(self, valve_match_id: int) -> dict:
        r = await self.client.get(f"/live/{valve_match_id}.json")
        r.raise_for_status()
        return r.json()
```

## 8.4 Draft Identity

主路径：

```text
players[]
  account_id
  hero_id
  team
  team_slot
```

第一版映射：

```text
team_slot 1 → Pos1
team_slot 2 → Pos2
team_slot 3 → Pos3
team_slot 4 → Pos4
team_slot 5 → Pos5
```

但必须通过 `DraftIdentityValidator` 检查：

```text
10 players
10 non-zero hero_id
两边各 5 人
每边 slot == {1,2,3,4,5}
10 hero unique
```

如果不满足：

```text
DRAFT_PARTIAL
```

不直接运行 R.O.S.H.。

交叉验证：

```text
fast_picks hero↔player
Canonical Roster
Player historical role
```

## 8.5 Draft Slot Model

```python
class DraftSlot(BaseModel):
    side: Literal["radiant", "dire"]
    position: Literal[1, 2, 3, 4, 5]

    account_id: int | None
    canonical_player_id: UUID | None

    hero_id: int

    source: Literal[
        "DLTV_SLOT",
        "DLTV_PLAYER_HERO",
        "INFERRED",
        "MANUAL",
    ]

    confidence: float
```

## 8.6 Fast Live State

```python
class DltvFastState(BaseModel):
    valve_match_id: int

    game_time_seconds: int | None
    radiant_kills: int | None
    dire_kills: int | None
    radiant_nw_lead: int | None
    first_blood: str | None

    received_at: datetime
    payload_hash: str
```

注意：

```text
radiant_lead
```

在样本中表现为 Radiant 经济领先/落后值。

## 8.7 State Reducer

Socket 会重复广播相同状态，所以 Normalized 表不要每条都写一行。

Raw 全保存；Normalized 只在状态变化时 append。

```python
class DltvStateReducer:
    def __init__(self):
        self._last_hash: dict[int, str] = {}

    def changed(self, match_id: int, payload: dict) -> bool:
        key = {
            "game_time": payload.get("game_time"),
            "radiant_score": payload.get("radiant_score"),
            "dire_score": payload.get("dire_score"),
            "radiant_lead": payload.get("radiant_lead"),
        }
        digest = hashlib.sha256(
            json.dumps(key, sort_keys=True).encode()
        ).hexdigest()

        if self._last_hash.get(match_id) == digest:
            return False

        self._last_hash[match_id] = digest
        return True
```

## 8.8 Charts

`charts` 可以作为中途接入后的历史补偿，但不能替代我们的实时 append-only 记录。

存储：

```text
game_times
net_worth
radiant_scores
dire_scores
radiant_kills
dire_kills
```

---

# 9. RayBet ↔ DLTV Temporal Aligner

这是整个 Live Decision 最重要的模块。

## 9.1 为什么不能简单按 received_at join

RayBet：

```text
价格变化可以是秒级
有 provider last_update
```

DLTV：

```text
Socket transport 几秒级
但有效比赛状态更新更粗
```

因此：

```text
latest RayBet
+
latest DLTV
```

不等于同一比赛瞬间。

## 9.2 所有 observation 保存三个时间

RayBet：

```text
provider_updated_at
received_at
stored_at
```

DLTV：

```text
source_game_time
received_at
stored_at
```

历史数据：

```text
event_time
first_usable_at
calculated_at
```

## 9.3 Calibration Signal

第一版主要使用事件相关：

```text
RayBet:
- 赔率大幅变化
- status 变化
- 市场重新定价

DLTV:
- kills 变化
- radiant_lead 大幅变化
- game_time snapshot 更新
```

不要以单个事件得出固定 lag。

使用多个事件估计：

```text
median relative lag
P90 relative lag
jitter
support count
confidence
```

## 9.4 LiveSynchronizationEstimate

```python
class LiveSynchronizationEstimate(BaseModel):
    canonical_map_id: UUID

    estimated_lag_seconds: float | None
    p50_seconds: float | None
    p90_seconds: float | None
    jitter_seconds: float | None

    sample_size: int
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    status: Literal["SAFE", "CAUTION", "UNSAFE", "UNKNOWN"]

    calculated_at: datetime
```

## 9.5 Gate

初始阈值可设：

```text
SAFE      <= 3s
CAUTION   3–8s
UNSAFE    > 8s
```

但这里只是默认配置，不能当永久事实。真正阈值应由 TI 实测数据调整。

## 9.6 Timeline Recorder

TI 前第一件事就是同时录两条流：

```text
same machine monotonic/wall clock
├── RayBet WS
└── DLTV Socket.IO
```

输出：

```text
provider
provider_event_time
received_at
canonical_map_id
event_type
payload_hash
```

---

# 10. Draft Intelligence / Minute R.O.S.H.

R.O.S.H. 是新项目原生模块。

它的职责不是识别比赛，不负责找玩家，不负责猜 Market。

输入必须是：

```text
Radiant Pos1–5 Hero
Dire Pos1–5 Hero
可选 Player Identity
statistics_cutoff
```

## 10.1 Provider

第一版继续利用 STRATZ 已验证的数据思路：

```text
Hero × Position
Hero × Time
Synergy
Counter/Matchup
Player × Hero
```

## 10.2 输出两条曲线

```text
Pure Draft Curve
Player-Adjusted Draft Curve
```

Pure：

```text
Hero
Position
Meta
Synergy
Counter
Minute
```

Player-adjusted：

```text
Pure
+
Player × Hero familiarity/performance
```

## 10.3 Minute Curve Model

```python
class DraftMinutePoint(BaseModel):
    minute: int
    pure_radiant_probability: float | None
    adjusted_radiant_probability: float | None
    support: int | None
    confidence: float | None
```

建议先覆盖：

```text
20–60 分钟
```

与已有成熟数据区间保持一致。

## 10.4 Derived Features

AI 不应该自己阅读 41 个点后计算。

程序提前生成：

```text
current_minute_edge
next_5m_average_edge
next_10m_average_edge
peak_minute
peak_edge
cross_over_minute
early/mid/late/ultra-late average
curve_slope_5m
curve_slope_10m
```

```python
class DraftDerivedFeatures(BaseModel):
    current_minute: int | None
    current_edge: float | None
    next_5m_edge: float | None
    next_10m_edge: float | None
    peak_minute: int | None
    peak_edge: float | None
    cross_over_minute: int | None
```

## 10.5 `statistics_cutoff`

R.O.S.H. 每次计算必须带：

```text
statistics_cutoff
model_version
data_version
```

避免未来泄漏。

---

# 11. Historical Intelligence — 队伍 / 选手 / Player×Hero 完整实现

这一层的目标不是重新建设 STRATZ/OpenDota，而是把第三方提供的**比赛事实**加工为因果正确、可追溯、可在某一时刻冻结的决策特征。

核心原则：

```text
第三方 Provider 负责：发生了什么
我们负责：这些事实在当前时点意味着什么
```

Historical Intelligence 必须最终回答四个问题：

```text
1. 这支队伍长期大概有多强？
2. 这支队伍最近状态如何？
3. 今天实际上场的 5 名选手当前状态如何？
4. 这 5 名选手拿到当前英雄后，熟练度和可信度如何？
```

并且每个答案都必须带：

```text
value
sample_size
confidence
knowledge_cutoff
model_version
```

不能只保存一个裸分数。

---

## 11.1 数据来源与职责边界

V1 固定优先级：

```text
DLTV
  ↓
确认“今天实际上场的人”
account_id + hero_id + team_slot

STRATZ
  ↓
Historical Primary Provider
职业比赛历史 / Player / Hero / Position / Advanced Performance

OpenDota
  ↓
Fallback + Verification + Post-match Enrichment
```

DLTV 不负责 Historical Rating。

STRATZ/OpenDota 不负责决定今天真正上场的 roster。

今天实际参赛人员优先来自当前 Map 的 DLTV Draft Identity：

```text
DLTV players[]
  account_id
  hero_id
  team_slot
        ↓
CanonicalPlayer
        ↓
Historical Intelligence
```

这样可以自然处理：

```text
stand-in
临时替补
roster change
同队选手临时换位
```

而不是盲目信任一个静态 Team Roster 页面。

---

## 11.2 Provider Contract

Historical Layer 不允许业务代码直接依赖 STRATZ/OpenDota 原始 JSON。

统一接口：

```python
from datetime import datetime
from typing import Protocol


class HistoricalProvider(Protocol):
    name: str

    async def get_team_pro_maps(
        self,
        team_id: str,
        *,
        before: datetime,
        limit: int,
    ) -> list["HistoricalMap"]:
        ...

    async def get_player_pro_maps(
        self,
        account_id: int,
        *,
        before: datetime,
        limit: int,
    ) -> list["PlayerHistoricalMap"]:
        ...

    async def get_player_hero_maps(
        self,
        account_id: int,
        hero_id: int,
        *,
        before: datetime,
        limit: int,
    ) -> list["PlayerHeroHistoricalMap"]:
        ...

    async def get_match_basic(self, match_id: int):
        ...

    async def get_match_advanced(self, match_id: int):
        ...
```

Provider 返回的对象必须先 Normalize 成我们的内部模型。

---

## 11.3 Historical Match Fact

所有评分的基础不是某个网站显示的“Rating”，而是我们保存的比赛事实。

推荐统一模型：

```python
from pydantic import BaseModel
from datetime import datetime


class HistoricalMap(BaseModel):
    canonical_map_id: str | None
    provider_match_id: str

    event_id: str | None
    event_name: str | None
    patch_id: str | None

    started_at: datetime
    ended_at: datetime | None

    radiant_team_id: str | None
    dire_team_id: str | None
    winner_team_id: str | None

    duration_seconds: int | None

    provider: str
    first_usable_at: datetime
    fetched_at: datetime
```

Player map：

```python
class PlayerHistoricalMap(BaseModel):
    provider_match_id: str
    account_id: int

    team_id: str | None
    opponent_team_id: str | None

    hero_id: int
    position: int | None
    patch_id: str | None

    started_at: datetime
    first_usable_at: datetime

    won: bool

    kills: int | None
    deaths: int | None
    assists: int | None

    gpm: float | None
    xpm: float | None
    last_hits: int | None
    hero_damage: float | None
    tower_damage: float | None
    networth: float | None

    # Provider-specific advanced metric，例如 STRATZ IMP。
    impact: float | None
```

关键字段是：

```text
first_usable_at
```

它表示：

> 这条历史事实最早什么时候已经可以被我们的系统可靠知道。

回测时必须满足：

```text
first_usable_at <= decision_at
```

否则属于未来数据泄漏。

---

## 11.4 Historical 数据不是“实时每次现查”

不要在每个 AI DecisionSnapshot 时临时对 STRATZ 发几十个请求。

正确结构：

```text
Provider
   ↓
Historical Sync Worker
   ↓
本地 Historical Store
   ↓
Feature Builder
   ↓
Feature Snapshot
```

TI 开始前先预热所有参赛队：

```text
每支 Team 最近 100–200 张职业 Map
每名当前 Roster Player 最近 100–200 张职业 Map
Player×Hero 按需缓存
```

比赛过程中大部分 Decision 都直接读取本地 PostgreSQL。

第三方 API 抖动不能影响已经进行中的 AI Decision。

---

## 11.5 数据同步状态

每条 Provider 数据保存：

```text
provider
provider_object_id
event_time
first_usable_at
fetched_at
raw_event_id
normalizer_version
```

同步状态：

```text
BASIC_PENDING
BASIC_READY
ADVANCED_PENDING
ADVANCED_READY
FAILED_TEMPORARY
FAILED_PERMANENT
```

这样 BO3 中 Map 1 结束后，不需要等全部 Replay 高级数据齐全才更新。

---

# 11.6 Team Intelligence

Team 不应该只有一个 `rating`。

统一拆成：

```text
Team Base Strength
Team Recent Form
Current Roster Strength
Roster Stability
Opponent/Context Support
```

最终：

```python
class TeamStrengthSnapshot(BaseModel):
    canonical_team_id: str

    base_rating: float | None
    base_rating_percentile: float | None

    recent_form: float | None

    last_5_wins: int
    last_5_maps: int
    last_10_wins: int
    last_10_maps: int
    last_20_wins: int
    last_20_maps: int

    current_roster_strength: float | None
    roster_stability: float | None
    exact_roster_map_count: int

    confidence: float

    knowledge_cutoff: datetime
    calculated_at: datetime
    model_version: str
```

---

## 11.7 Team Base Rating：V1 使用 Map-level Elo

TI 前不需要复杂模型。

V1 自己维护 Map-level Elo 即可。

期望胜率：

```text
E_A = 1 / (1 + 10 ^ ((R_B - R_A) / 400))
```

更新：

```text
R_A_new = R_A + K × (S_A - E_A)
```

其中：

```text
S_A = 1 win
S_A = 0 loss
```

Python：

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class EloUpdate:
    rating_a: float
    rating_b: float
    expected_a: float
    expected_b: float


def update_elo(
    rating_a: float,
    rating_b: float,
    winner: str,
    *,
    k: float = 24.0,
) -> EloUpdate:
    expected_a = 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))
    expected_b = 1.0 - expected_a

    score_a = 1.0 if winner == "A" else 0.0
    score_b = 1.0 - score_a

    return EloUpdate(
        rating_a=rating_a + k * (score_a - expected_a),
        rating_b=rating_b + k * (score_b - expected_b),
        expected_a=expected_a,
        expected_b=expected_b,
    )
```

V1 默认：

```text
initial rating = 1500
K = configurable, default 24
```

不允许把 Rating 直接覆盖在 `teams.current_rating` 后丢失历史。

保存：

```text
team_rating_snapshots
```

每张 Map 结束生成新 Snapshot。

---

## 11.8 Team Rating 的历史回放

必须能够问：

```text
在 2026-08-13 10:00 UTC 之前，Team Spirit 的 rating 是多少？
```

SQL 语义：

```sql
SELECT *
FROM team_rating_snapshots
WHERE canonical_team_id = :team_id
  AND knowledge_cutoff <= :decision_at
ORDER BY knowledge_cutoff DESC
LIMIT 1;
```

这条原则同样适用于：

```text
player_form_snapshots
player_strength_snapshots
player_hero_snapshots
team_form_snapshots
```

---

## 11.9 Team Recent Form

不要把最近状态等于 Last 20 Win Rate。

V1 同时保留原始窗口：

```text
Last 5
Last 10
Last 20
```

并生成一个归一化 `recent_form`。

第一版权重：

```text
最近 5 Maps      50%
Maps 6–10        30%
Maps 11–20       20%
```

简单实现：

```python
def weighted_recent_win_form(results: list[bool]) -> float | None:
    if not results:
        return None

    recent = results[:20]

    groups = [
        (recent[0:5], 0.50),
        (recent[5:10], 0.30),
        (recent[10:20], 0.20),
    ]

    weighted = 0.0
    used_weight = 0.0

    for maps, weight in groups:
        if not maps:
            continue
        win_rate = sum(maps) / len(maps)
        weighted += win_rate * weight
        used_weight += weight

    if used_weight == 0:
        return None

    # 转换到约 [-1, +1]
    return ((weighted / used_weight) - 0.5) * 2.0
```

输出保留：

```text
raw last5/10/20
normalized recent_form
sample size
```

AI 必须能够区分：

```text
5-0 / sample 5
```

与：

```text
16-4 / sample 20
```

---

## 11.10 后续可升级为时间衰减，但 V1 不强制

后续可用指数衰减：

```text
weight(age_days) = 0.5 ^ (age_days / half_life_days)
```

建议半衰期：

```text
14–21 days
```

但 TI V1 优先稳定和可解释性，不要求先完成复杂参数调优。

---

## 11.11 Current Roster Strength

Team Rating 是组织层面的历史。

但是今天实际上场的人可能发生变化。

DLTV 当前 Map 给：

```text
5 × account_id
```

Canonical Resolver 得到当前 5 人：

```text
CurrentRosterSnapshot
```

然后读取每名选手的最新：

```text
Player Base Strength
Player Recent Form
```

形成：

```text
current_roster_strength
```

V1 可以先采用位置等权平均：

```text
Roster Strength = mean(Player Combined Strength × 5)
```

后续才考虑不同位置权重。

重要的是：

```text
Team Base Rating
```

和：

```text
Current Roster Strength
```

必须分开给 AI。

---

## 11.12 Roster Stability

Roster Stability 衡量：

> 当前这五个人作为完整阵容一起打职业比赛的样本有多少。

建议同时输出：

```text
exact_roster_maps_30d
exact_roster_maps_90d
exact_roster_maps_all_recent
same_4_of_5_maps
```

V1 简化评分：

```python
def roster_stability(exact_maps: int) -> float:
    # 20张以后基本视为高稳定；不要无限增长。
    return min(exact_maps / 20.0, 1.0)
```

但数据库仍保存原始 map count。

例：

```text
Current exact roster maps: 2
Roster Stability: 0.10 LOW
```

AI 就知道历史 Team Elo 的适用性下降。

---

# 11.13 Player Intelligence

每名 Player 拆成：

```text
Player Base Strength
Recent Professional Form
Current Role
Player × Current Hero
```

不要把它们压成一个不可解释的数字。

最终：

```python
class PlayerFeatureSnapshot(BaseModel):
    canonical_player_id: str
    account_id: int
    position: int

    base_strength: float | None
    recent_form: float | None

    recent_5: float | None
    recent_10: float | None
    recent_20: float | None

    maps_5: int
    maps_10: int
    maps_20: int

    confidence: float

    knowledge_cutoff: datetime
    calculated_at: datetime
    model_version: str
```

---

## 11.14 Player Base Strength

V1 不建议自己训练复杂 Player Rating Model。

可以从该 Player 过去较长窗口的**位置标准化比赛表现**生成 EWMA / weighted mean。

例如：

```text
最近 50–100 张职业 Map
```

而 Recent Form 使用最近 20 张。

这样：

```text
Base Strength = 长期能力背景
Recent Form   = 当前状态偏移
```

两者不能混成一个。

---

## 11.15 为什么必须 Role-adjusted

不能直接比较：

```text
Carry GPM 650
Support GPM 330
```

然后认为 Carry 表现更好。

我们需要针对：

```text
patch + position
```

计算基准分布。

例如：

```text
Patch X Pos1 GPM mean/std
Patch X Pos2 GPM mean/std
...
Patch X Pos5 GPM mean/std
```

然后计算标准化：

```text
z = (value - role_mean) / role_std
```

最好使用 robust clipping：

```text
z clipped to [-3, +3]
```

---

## 11.16 Role Baseline 表

建议定期构建：

```text
role_metric_baselines
```

字段：

```text
patch_id
position
metric
sample_size
mean
std
median
p25
p75
knowledge_cutoff
```

V1 指标：

Core：

```text
gpm
xpm
kda
networth
hero_damage
tower_damage
last_hits
death_rate
```

Support：

```text
kda
assists
assist_share / participation if available
death_rate
impact
xpm relative to role
```

如果 Provider 没有某个高级字段：

```text
UNKNOWN
```

不是 0。

---

## 11.17 单张 Map Player Performance Score

V1 可以先用线性可解释模型。

示例：

```python
from statistics import mean


def weighted_metric_score(
    metric_z: dict[str, float | None],
    weights: dict[str, float],
) -> float | None:
    values: list[float] = []
    used_weights: list[float] = []

    for name, weight in weights.items():
        value = metric_z.get(name)
        if value is None:
            continue
        values.append(value * weight)
        used_weights.append(abs(weight))

    if not used_weights:
        return None

    return sum(values) / sum(used_weights)
```

Pos1 示例权重只作为初始配置：

```python
POS1_WEIGHTS = {
    "gpm": 0.22,
    "xpm": 0.12,
    "kda": 0.16,
    "networth": 0.18,
    "hero_damage": 0.12,
    "tower_damage": 0.08,
    "last_hits": 0.08,
    "death_rate": -0.04,
}
```

Pos5 完全使用另一套配置。

所有权重必须：

```text
versioned
configurable
```

不要写死在数据库里。

---

## 11.18 Player Recent Form

对每张 Map 先得到：

```text
role_adjusted_map_performance
```

然后再应用窗口：

```text
Last 5        50%
6–10          30%
11–20         20%
```

不是先把原始 GPM 等指标横跨 20 场平均。

伪代码：

```python
def recent_player_form(scores: list[float]) -> float | None:
    if not scores:
        return None

    groups = [
        (scores[:5], 0.50),
        (scores[5:10], 0.30),
        (scores[10:20], 0.20),
    ]

    total = 0.0
    weight_sum = 0.0

    for group, weight in groups:
        if not group:
            continue
        total += (sum(group) / len(group)) * weight
        weight_sum += weight

    return total / weight_sum if weight_sum else None
```

---

## 11.19 Player Recent Form Confidence

Confidence 不能等于 Form Score。

V1 可以由：

```text
sample completeness
recency
provider quality
role certainty
```

组成。

例如：

```python
def sample_confidence(sample: int, target: int = 20) -> float:
    return min(sample / target, 1.0)
```

最终：

```text
confidence =
0.55 × sample_confidence
+ 0.25 × data_completeness
+ 0.20 × role_identity_confidence
```

所有权重同样版本化。

---

# 11.20 Player × Hero Intelligence

这是 Draft Intelligence 最重要的个性化信号之一。

Current Map 已经由 DLTV 得到：

```text
account_id
hero_id
position
```

所以可以直接建立：

```text
PlayerHeroKey(account_id, hero_id, position)
```

Historical Provider 查询三个窗口：

```text
LONG TERM
RECENT 180 DAYS
CURRENT PATCH
```

输出：

```python
class PlayerHeroSnapshot(BaseModel):
    canonical_player_id: str
    account_id: int
    hero_id: int
    position: int

    historical_maps: int
    historical_win_rate: float | None
    historical_performance: float | None

    recent_180d_maps: int
    recent_180d_win_rate: float | None
    recent_180d_performance: float | None

    current_patch_maps: int
    current_patch_win_rate: float | None
    current_patch_performance: float | None

    position_fit: float | None

    raw_strength: float | None
    adjusted_strength: float | None
    confidence: float

    knowledge_cutoff: datetime
    calculated_at: datetime
    model_version: str
```

---

## 11.21 Player × Hero 不能只使用胜率

例如：

```text
Player A Morphling
3 maps
3 wins
```

不能直接：

```text
100% → 极强
```

需要同时看：

```text
sample
role
performance
patch
recency
```

而且小样本必须收缩。

---

## 11.22 Beta-Binomial Shrinkage

V1 可以用非常简单稳定的 Beta Prior。

例如某 Hero/Position population baseline：

```text
prior mean = 50%
prior strength = 12 maps
```

则：

```python
def beta_adjusted_win_rate(
    wins: int,
    matches: int,
    *,
    prior_mean: float = 0.50,
    prior_strength: float = 12.0,
) -> float | None:
    if matches < 0 or wins < 0 or wins > matches:
        return None

    alpha = prior_mean * prior_strength
    beta = (1.0 - prior_mean) * prior_strength

    return (wins + alpha) / (matches + alpha + beta)
```

于是：

```text
3-0 raw 100%
```

不会变成 100% 的 adjusted value。

长期应该把 prior 改成：

```text
Hero × Position × Patch baseline
```

而不是固定 50%。

---

## 11.23 PlayerHero 多窗口组合

V1 推荐：

```text
Historical      30%
Recent 180d     40%
Current Patch   30%
```

但是某窗口没有足够样本时，自动重新归一化权重。

例如当前 Patch 只有 1 张 Map：

```text
Current Patch confidence 很低
```

不要让它支配最终结果。

示例：

```python
def combine_supported(values: list[tuple[float | None, float]]) -> float | None:
    available = [(v, w) for v, w in values if v is not None]
    if not available:
        return None

    weight_sum = sum(w for _, w in available)
    return sum(v * w for v, w in available) / weight_sum
```

---

## 11.24 Position Fit

PlayerHero 还要回答：

> 这个选手在这个英雄上有经验，但是否是在当前这个位置？

例如：

```text
Tiny overall 40 maps
但 Pos2 只有 3 maps
Pos4 有 31 maps
```

当前被分配为 Pos2 时：

```text
position_fit != HIGH
```

V1：

```text
position_fit =
current_position_maps /
all_recent_player_hero_maps
```

保留原始 numerator/denominator。

---

## 11.25 PlayerHero Confidence

建议综合：

```text
sample_size
recent_sample
patch_sample
position_fit sample
data completeness
identity confidence
```

粗略 V1：

```python
def player_hero_confidence(
    historical_maps: int,
    recent_maps: int,
    patch_maps: int,
    identity_confidence: float,
) -> float:
    hist = min(historical_maps / 40.0, 1.0)
    recent = min(recent_maps / 15.0, 1.0)
    patch = min(patch_maps / 8.0, 1.0)

    return (
        0.30 * hist
        + 0.35 * recent
        + 0.20 * patch
        + 0.15 * identity_confidence
    )
```

这不是永久算法，但足够可解释、可版本化、可回测。

---

# 11.26 Team × Roster × Player 的关系

AI Snapshot 不要只给：

```text
Team Strength = 0.63
```

而应给：

```text
TEAM
Base Elo                 1638
Recent Form              +0.34 HIGH
Current Roster Strength  +0.27 HIGH
Roster Stability         0.95 HIGH

PLAYERS
Pos1 Base +0.42 / Recent +0.31
Pos2 Base +0.55 / Recent +0.08
Pos3 Base +0.37 / Recent -0.12
Pos4 Base +0.20 / Recent +0.26
Pos5 Base +0.31 / Recent +0.18
```

这样 AI 可以看到证据之间是否矛盾。

例如：

```text
Team Elo 很强
但是当前 roster 是新阵容
```

与：

```text
Team Elo 很强
且五人长期稳定
```

含义完全不同。

---

# 11.27 Map End 后如何更新

不是每天固定更新时间。

事件链：

```text
DLTV / RayBet detect Map End
        ↓
Postmatch Resolver
        ↓
等待 Provider Basic Match
        ↓
BASIC_READY
        ↓
立即更新：
  Team Elo
  Team W/L Form
  Player W/L
  PlayerHero W/L / sample
  Roster map count
        ↓
继续检查高级数据
        ↓
ADVANCED_READY
        ↓
更新：
  Player role-adjusted performance
  Player recent form
  PlayerHero performance
  Advanced confidence
```

这条链必须自动运行。

---

## 11.28 BO3 / BO5 的 Map 间更新

这是 TI 非常重要的场景。

例如：

```text
18:40 Map 1 End
18:42 Basic result available
18:48 Map 2 Draft Complete
18:52 Advanced replay stats available
```

则：

### 18:42

可以更新：

```text
Team Elo
Team recent W/L
Player basic W/L
PlayerHero basic sample
```

### 18:48 Map 2 Snapshot

允许使用 18:42 已经可知的 Basic 信息。

不能使用 18:52 才出现的 Advanced 信息。

### 18:52 之后的新 Snapshot

才允许加入 Advanced Player Form。

过去 18:48 的 Snapshot 永远不修改。

---

## 11.29 Feature Knowledge Cutoff

每个 Feature Snapshot 必须有：

```text
knowledge_cutoff
```

定义：

> 这个 Feature 所使用的所有输入数据中，最晚的 first_usable_at。

构建 DecisionSnapshot 时必须：

```text
feature.knowledge_cutoff <= decision_at
```

否则 Gate 直接拒绝。

---

# 11.30 Provider Fallback 策略

STRATZ 是 Primary，但系统不能把 STRATZ 当单点故障。

建议：

```text
Basic Match Result
STRATZ available → use STRATZ
else OpenDota available → use OpenDota
else keep PENDING
```

Advanced：

```text
STRATZ advanced available
→ preferred

OpenDota parsed available
→ supplement / fallback
```

如果两个 Provider 都有：

```text
match identity
winner
hero
player
```

出现冲突：

```text
DATA_CONFLICT
```

不要默默选择一个。

---

## 11.31 Provider Provenance

每个 Feature 必须能够追溯：

```text
Feature Snapshot
      ↓
Input Match IDs
      ↓
Normalized Facts
      ↓
Raw Provider Events
```

建议中间表：

```text
feature_snapshot_sources
```

字段：

```text
feature_type
feature_snapshot_id
provider
provider_match_id
raw_event_id
first_usable_at
```

---

# 11.32 Historical 数据库表

## `historical_maps`

```text
id
canonical_map_id
provider
provider_match_id
patch_id
started_at
ended_at
winner_team_id
first_usable_at
basic_ready_at
advanced_ready_at
raw_event_id
```

唯一约束建议：

```text
(provider, provider_match_id)
```

---

## `historical_player_maps`

```text
id
historical_map_id
canonical_player_id
account_id
canonical_team_id
opponent_team_id
hero_id
position
won
kills
deaths
assists
gpm
xpm
networth
last_hits
hero_damage
tower_damage
impact
basic_first_usable_at
advanced_first_usable_at
```

---

## `team_rating_snapshots`

```text
id
canonical_team_id
rating
rating_before
opponent_rating_before
expected_probability
result
source_map_id
knowledge_cutoff
calculated_at
model_version
```

---

## `team_form_snapshots`

```text
id
canonical_team_id
last_5_maps
last_5_wins
last_10_maps
last_10_wins
last_20_maps
last_20_wins
recent_form
exact_roster_maps
roster_stability
knowledge_cutoff
calculated_at
model_version
```

---

## `player_performance_maps`

```text
id
canonical_player_id
canonical_map_id
position
metric_payload JSONB
role_adjusted_score
knowledge_cutoff
model_version
```

---

## `player_form_snapshots`

```text
id
canonical_player_id
position
base_strength
recent_5
recent_10
recent_20
recent_form
sample_size
confidence
last_included_map_id
knowledge_cutoff
calculated_at
model_version
```

---

## `player_hero_snapshots`

```text
id
canonical_player_id
hero_id
position
historical_maps
historical_win_rate
recent_180d_maps
recent_180d_win_rate
current_patch_maps
current_patch_win_rate
position_fit
raw_strength
adjusted_strength
confidence
last_included_map_id
knowledge_cutoff
calculated_at
model_version
```

---

# 11.33 Historical Service API（内部）

Snapshot Builder 不应该自己拼 SQL。

统一 Service：

```python
class HistoricalIntelligenceService:
    async def get_team_snapshot(
        self,
        team_id: str,
        *,
        roster_player_ids: list[str],
        as_of: datetime,
    ) -> TeamStrengthSnapshot:
        ...

    async def get_player_snapshot(
        self,
        player_id: str,
        *,
        position: int,
        as_of: datetime,
    ) -> PlayerFeatureSnapshot:
        ...

    async def get_player_hero_snapshot(
        self,
        player_id: str,
        *,
        hero_id: int,
        position: int,
        as_of: datetime,
    ) -> PlayerHeroSnapshot:
        ...
```

所有方法都是：

```text
as_of aware
```

不能返回“数据库最新值”而不看 Decision 时间。

---

# 11.34 Startup Prewarm

`python -m app.main` 启动后：

```text
1. 获取 TI active/upcoming teams
2. Resolve canonical teams
3. 拉每队最近职业 maps
4. 拉当前/预计 roster players
5. 拉每人最近 100–200 pro maps
6. 计算 Team / Player Feature Snapshot
7. PlayerHero 不全量拉所有英雄
8. Draft 出现后按当前10个 Hero on-demand refresh
```

这样避免启动时请求：

```text
16 teams × 5 players × 130 heroes
```

这种无意义数据爆炸。

---

## 11.35 PlayerHero Cache

Cache Key：

```text
(account_id, hero_id, position, statistics_cutoff_bucket)
```

例如：

```text
cutoff bucket = 当前 UTC 小时
```

同一张 Map Draft 中，多次 Decision 不需要重复向 Provider 拉历史。

Map 结束有新数据后主动 invalidate 相关 PlayerHero Key。

---

# 11.36 Historical Refresh Worker

Worker 不需要高频循环全量同步。

触发：

```text
STARTUP
UPCOMING_MATCH_DISCOVERED
ROSTER_CHANGED
MAP_ENDED
MANUAL_REFRESH
PERIODIC_SAFETY_REFRESH
```

建议周期安全刷新：

```text
15–30 分钟
```

而不是每秒。

---

# 11.37 Provider Rate Limit / Error Handling

第三方历史 Provider 返回：

```text
429
5xx
timeout
partial payload
```

时：

```text
不要删除已有 Feature
不要把旧值改成 0
```

保留最新已知 Feature，并增加：

```text
stale_age
provider_health
refresh_failed_at
```

Decision Gate 决定是否仍允许使用。

例如赛前 2 小时生成的 Team Rating：

```text
通常仍然可用
```

而 PlayerHero 如果刚刚 Map 1 打完但还没更新：

```text
可以标记 STALE_RELATIVE_TO_PREVIOUS_MAP
```

供 AI/系统识别。

---

# 11.38 Historical Quality Gate

建议输出：

```python
class HistoricalQuality(BaseModel):
    team_strength_ready: bool
    roster_confirmed: bool
    player_form_ready_count: int
    player_hero_ready_count: int

    oldest_feature_age_seconds: float | None

    blockers: list[str]
    warnings: list[str]
```

典型 warning：

```text
LOW_PLAYER_SAMPLE
LOW_PLAYER_HERO_SAMPLE
NEW_ROSTER
ADVANCED_STATS_PENDING
PLAYER_ROLE_UNCERTAIN
PROVIDER_STALE
```

典型 blocker：

```text
ROSTER_IDENTITY_AMBIGUOUS
HISTORICAL_DATA_FUTURE_LEAK
```

一般 Historical 小样本不应直接阻断整个 Decision，而应该降低 confidence。

---

# 11.39 给 AI 的 Historical Payload

不要直接塞数据库对象。

最终序列化成：

```json
{
  "team_a": {
    "base_rating": 1638,
    "recent_form": 0.34,
    "recent_form_confidence": 0.92,
    "last_10": "7-3",
    "last_20": "13-7",
    "current_roster_strength": 0.28,
    "roster_stability": 0.95,
    "exact_roster_maps": 31
  },
  "players_a": [
    {
      "position": 1,
      "base_strength": 0.42,
      "recent_form": 0.31,
      "recent_form_confidence": 0.90,
      "current_hero": 10,
      "player_hero_strength": 0.48,
      "player_hero_sample": 17,
      "player_hero_confidence": 0.74,
      "position_fit": 0.88
    }
  ]
}
```

AI不需要知道 STRATZ/OpenDota 的字段名。

---

# 11.40 Historical Snapshot 与 Draft Intelligence 的边界

避免重复计算。

Historical Intelligence 负责：

```text
Player Base Strength
Player Recent Form
PlayerHeroStrength
PlayerHeroConfidence
```

Draft Intelligence 负责：

```text
Hero × Position Minute Curve
Synergy
Counter
Pure Draft
Player-adjusted Draft Curve
```

Player-adjusted Draft 可以消费：

```text
PlayerHeroStrength
```

但是 Historical 本身不能反过来读取 Draft 最终胜率。

保持单向：

```text
Historical
   ↓
Draft Player Adjustment
```

---

# 11.41 Historical 模块的最小验收

TI 开赛前至少需要自动证明：

```text
给定一场已知职业比赛：

1. 从 DLTV 得到10个 account_id
2. Canonical Resolver 得到10个 Player
3. Historical Provider 找到最近职业比赛
4. 生成两个 TeamStrengthSnapshot
5. 生成10个 PlayerFeatureSnapshot
6. Draft完成后生成10个 PlayerHeroSnapshot
7. 所有 Feature 都有 knowledge_cutoff
8. as_of 查询不会读到未来 Map
9. Provider 临时失败时可以使用最后一个合格 Snapshot
10. Map End Basic Ready 后能增量更新
```

---

# 11.42 必须写的 Historical Tests

至少：

```text
test_elo_upset_moves_more_than_expected_win

test_team_rating_snapshot_is_append_only

test_as_of_query_does_not_return_future_snapshot

test_recent_form_window_weights

test_support_not_compared_to_carry_raw_gpm

test_missing_metric_is_unknown_not_zero

test_player_hero_small_sample_is_shrunk

test_player_hero_position_fit

test_new_roster_lowers_roster_stability

test_map1_basic_can_affect_map2

test_map1_advanced_cannot_rewrite_old_map2_snapshot

test_stratz_failure_falls_back_without_erasing_previous_feature

test_provider_conflict_is_flagged
```

这套测试比追求一个复杂算法更重要。

---

# 11.43 V1 Historical Intelligence 最终定义

TI V1 不追求“最先进 Rating”。

我们只需要一个：

```text
稳定
可解释
可回放
无未来泄漏
能够 Map 间增量更新
```

的 Historical Engine。

因此第一版明确采用：

```text
Team Base       = Map Elo
Team Form       = Last 5/10/20 weighted form
Roster          = 当前 DLTV account_id roster
Roster Stability= exact-roster map sample

Player Base     = long-window role-adjusted performance
Player Form     = last 5/10/20 role-adjusted map scores
PlayerHero      = historical + recent180d + current patch
                  + position fit
                  + Beta shrinkage
                  + confidence
```

所有内容最终以 Append-only Feature Snapshot 进入 DecisionSnapshot。

---

# 12. Decision Modes

## PREMATCH

```text
RayBet
Team Strength
Player Strength
Recent Form
```

## POST_DRAFT

增加：

```text
10 Heroes
Positions
Minute R.O.S.H.
Player × Hero
```

## LIVE_BASIC

增加：

```text
DLTV_FAST:
game_time
kills
team NW lead
```

前提：

```text
sync SAFE
```

## LIVE_FULL

未来如果确认个人详细数据足够新鲜，再增加：

```text
10 player NW
GPM/XPM
KDA
items
```

`LIVE_FULL` 绝不能因为字段“存在”就开启，必须通过 freshness/sync gate。

---

# 13. DecisionSnapshot

这是系统核心资产。

```python
class DecisionSnapshot(BaseModel):
    snapshot_id: UUID
    created_at: datetime
    mode: Literal[
        "PREMATCH",
        "POST_DRAFT",
        "LIVE_BASIC",
        "LIVE_FULL",
    ]

    identity: dict
    market: dict
    draft: dict | None
    history: dict
    live: dict | None
    quality: dict

    snapshot_hash: str
```

Canonical JSON：

```python
import hashlib
import json


def snapshot_hash(payload: dict) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()
```

过去 Snapshot 永不修改。

---

# 14. Deterministic Gate

AI 之前必须先程序判断：

```text
identity complete?
market available?
market fresh?
draft complete?
historical feature cutoff valid?
live fresh?
live sync safe?
```

输出：

```python
class GateResult(BaseModel):
    eligible: bool
    mode: str
    blockers: list[str]
    warnings: list[str]
```

典型 blocker：

```text
IDENTITY_AMBIGUOUS
MARKET_MISSING
MARKET_STALE
DRAFT_PARTIAL
LIVE_SYNC_UNKNOWN
LIVE_DATA_DESYNC
LIVE_STALE
```

如果 Live Gate 失败：

```text
LIVE → POST_DRAFT
```

而不是阻塞整个系统。

---

# 15. Multi-AI Layer

第一版模型不能自行联网找比赛资料。

每个模型只看：

```text
同一个 DecisionSnapshot
```

统一 Schema：

```python
class AiDecision(BaseModel):
    action: Literal[
        "BUY_A",
        "BUY_B",
        "NO_BUY",
        "INSUFFICIENT_DATA",
    ]

    fair_probability_a: float | None
    confidence: float

    market_assessment: Literal[
        "UNDERPRICED",
        "FAIR",
        "OVERPRICED",
        "UNKNOWN",
    ]

    max_acceptable_odds_a: float | None

    primary_reasons: list[str]
    counter_arguments: list[str]
    data_quality_concerns: list[str]
    blockers: list[str]
```

强制要求：

```text
counter_arguments
```

避免只生成单向解释。

---

# 16. AI Coordinator

```python
class AiCoordinator:
    def __init__(self, providers):
        self.providers = providers

    async def run_all(self, snapshot):
        async def one(provider):
            try:
                return await provider.decide(snapshot)
            except Exception as exc:
                return {
                    "provider": provider.name,
                    "status": "FAILED",
                    "error": str(exc),
                }

        return await asyncio.gather(
            *(one(p) for p in self.providers)
        )
```

一个 Provider timeout 不允许拖死其他模型。

保存：

```text
snapshot_hash
provider
model
model_version
prompt_version
request_started_at
response_received_at
latency
raw_response
normalized_decision
```

---

# 17. Decision Trigger

不要每秒调用 AI。

V1：

```text
PREMATCH
DRAFT_COMPLETE
5m
10m
15m
20m
25m
...
SIGNIFICANT_ODDS_MOVE
MARKET_REOPEN
```

显著赔率变化需要 cooldown，避免一分钟调用几十次。

---

# 18. Future Odds / Evaluation

每个 Decision 自动挂：

```text
+30s odds
+1m odds
+3m odds
+5m odds
closing odds
map result
```

评价：

```text
Result Accuracy
Brier
Log Loss
Calibration
Future Odds Direction
CLV
Decision Stability
Model Agreement
Latency
Cost
```

不要只用“比赛最后赢没赢”评价一个 Live Decision。

---

# 19. 数据库表

## Identity

```text
canonical_events
canonical_teams
canonical_players
canonical_series
canonical_maps
provider_team_mappings
provider_player_mappings
provider_match_mappings
```

## Raw

```text
provider_raw_events
```

建议字段：

```text
id
provider
event_type
provider_key
request_started_at
provider_event_at
received_at
stored_at
payload JSONB
payload_hash
parser_version
```

## Market

```text
raybet_matches
raybet_odds_registry
odds_observations
```

## Draft

```text
draft_snapshots
draft_slots
draft_minute_curves
```

## History

```text
historical_maps
historical_player_maps
role_metric_baselines
team_rating_snapshots
team_form_snapshots
player_performance_maps
player_form_snapshots
player_hero_snapshots
feature_snapshot_sources
```

这些表必须支持 `knowledge_cutoff <= decision_at` 的 as-of 查询；不允许只维护一个 current 值。

## Live

```text
dltv_live_observations
live_sync_estimates
```

## Decisions

```text
decision_snapshots
ai_decisions
decision_future_odds
map_results
decision_evaluations
```

---

# 20. Raw Store 示例

```python
async def save_raw_event(
    session,
    *,
    provider: str,
    event_type: str,
    provider_key: str | None,
    payload: dict,
    provider_event_at: datetime | None,
    received_at: datetime,
):
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    session.add(ProviderRawEvent(
        provider=provider,
        event_type=event_type,
        provider_key=provider_key,
        provider_event_at=provider_event_at,
        received_at=received_at,
        payload=payload,
        payload_hash=hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest(),
        parser_version="v1",
    ))
```

---

# 21. Runtime

只能有一个启动入口：

```bash
python -m app.main
```

启动：

```text
RayBetDiscoveryWorker
RayBetSocketWorker
DltvSocketWorker
HistoricalSyncWorker
DraftCoordinator
TemporalAligner
SnapshotCoordinator
AiCoordinator
FutureOddsWorker
SettlementWorker
WebServer
```

---

# 22. Supervisor

所有 Worker 统一状态：

```text
STARTING
RUNNING
DEGRADED
RESTARTING
FAILED
```

记录：

```text
last_attempt_at
last_success_at
consecutive_failures
last_error
messages_received
last_message_at
```

Socket 断线必须自动重连。

DLTV HAR 已经出现连接重建和 polling 502，因此这一点不是“以后优化”，而是 V1 必须有。

---

# 23. Business Readiness

系统不是只有 `/health = 200`。

Dashboard 顶部显示：

```text
RAYBET_HTTP        READY
RAYBET_SOCKET      READY
DLTV_SOCKET        READY
DLTV_DRAFT         READY
LIVE_SYNC          UNKNOWN / SAFE / UNSAFE
STRATZ             READY
DRAFT_ENGINE       READY
HISTORY            READY
GPT                READY
CLAUDE             READY
GEMINI             READY
```

整体：

```text
READY
DEGRADED
ACTION_REQUIRED
```

DLTV Live 不安全时仍可 POST_DRAFT。

---

# 24. Dashboard V1

一场 Map 卡片：

```text
TI 2026
Spirit vs Xtreme
Map 1

MARKET
Spirit 2.18
Xtreme 1.72
1m move +3.2%
Market freshness 0.4s

DRAFT
Pure current +6.1%
Player-adjusted +8.4%
Next 5m +9.2%
Peak 36m +11.1%

LIVE
Game 17:41
Kills 10-10
Radiant NW -6643
DLTV state age 18s

SYNC
UNKNOWN / SAFE / UNSAFE
P50 ...
P90 ...

GPT
BUY A / 72%

Claude
NO BUY / 81%

Gemini
BUY A / 67%
```

必须把 Data Quality 放在最终判断旁边。

---

# 25. TI 前的验收链

一次启动后必须自动形成：

```text
python -m app.main
        ↓
RayBet HTTP发现 Dota比赛
        ↓
RayBet /odds Bootstrap
        ↓
RayBet Socket实时写 Odds Timeline
        ↓
DLTV __nd2_series / Match Resolver
        ↓
获得 Valve Match ID
        ↓
DLTV /live/{id}.json
        ↓
Player + Hero + Position
        ↓
Draft Intelligence Minute Curve
        ↓
Historical Feature Snapshot
        ↓
DLTV Fast State
        ↓
Temporal Gate
        ↓
DecisionSnapshot
        ↓
GPT / Claude / Gemini
        ↓
Decision Log
        ↓
Future Odds
        ↓
Map Result
        ↓
Evaluation
```

如果 DLTV 时间轴不安全：

```text
POST_DRAFT Snapshot
```

仍然正常工作。

---

# 26. 必须写的自动化测试

## RayBet

```text
HAR fixture → match parser
HAR fixture → odds registry
Socket publish → odds delta
unknown odds_id → trigger metadata refresh
reconnect
raw status preservation
```

## DLTV

```text
bootstrap fixture → 10 draft slots
slots 1–5 validation
fast socket state parser
repeated socket payload dedup
socket reconnect
delayed full_stats cannot pass live freshness gate
```

## Identity

```text
exact mapping
team alias mapping
ambiguous mapping → reject
Valve Match ID authoritative mapping
```

## Snapshot

```text
same input → same hash
past snapshot immutable
UNKNOWN preserved as null
future feature cutoff rejected
```

## AI

```text
same snapshot hash sent to all models
one provider timeout does not block others
invalid JSON response → parse failure, not fabricated decision
```

---

# 27. 需要保留的待验证项

下面这些不能在 TI 前被“猜成事实”：

1. RayBet raw `status` 1/2/4/5 的完整业务映射。
2. DLTV `team_slot=1..5` 是否在所有职业比赛始终严格对应 Pos1..5。
3. DLTV FAST 相对 RayBet 的真实 lag 和 jitter。
4. DLTV `full_stats` 在不同赛事中是否始终来自高延迟 feed。
5. `__nd2_series` 的全站广播覆盖范围是否稳定。
6. RayBet `match` channel 的广播覆盖范围、重连后是否需要额外状态恢复。

设计必须允许这些结论变化，而不需要重写业务层。

---

# 28. TI 期间真正要积累的核心资产

优先级从高到低：

```text
1. RayBet Odds Timeline
2. Raw RayBet Socket Events
3. DLTV Fast State Timeline
4. RayBet ↔ DLTV Sync Estimates
5. Draft Minute Curves
6. Historical Feature Snapshots
7. DecisionSnapshots
8. AI Decisions
9. Future Odds
10. Map Results
```

UI 不是核心资产。

---

# 29. V1 明确不做

```text
自动下注
资金管理
Kelly
Replay Parser
Vision OCR
地图坐标
复杂 Deep Learning
AI 辩论
多数票自动执行
训练自己的 LLM
```

第一目标只有：

> **数据完整、时间正确、决策可审计。**

---

# 30. 最终架构

```text
                       RayBet
                HTTP             SocketCluster
                 │                    │
          Match Discovery        Odds Delta
                 │                    │
                 └──────────┬─────────┘
                            ↓
                    Market Intelligence
                            │

                       DLTV
              Bootstrap          Socket.IO
                 │                    │
           Draft Identity         Fast State
                 │                    │
                 ↓                    ↓
          Draft Intelligence     Live Intelligence
                 │                    │
                 └──────────┬─────────┘
                            │
                     STRATZ/OpenDota
                            │
                   Historical Intelligence
                            │
                            ↓
                    Temporal Aligner
                            ↓
                    Deterministic Gate
                            ↓
                   DecisionSnapshot @ T
                            │
              ┌─────────────┼─────────────┐
              ↓             ↓             ↓
             GPT          Claude        Gemini
              │             │             │
              └─────────────┼─────────────┘
                            ↓
                    Decision Evaluation
                            ↓
              Future Odds / Closing / Result
```

---

# 31. 最终工程判断

根据当前 HAR，我们已经不需要再把“怎么抓数据”当成未知问题：

- RayBet：HTTP Bootstrap + SocketCluster 增量流。
- DLTV：`/live/{ValveMatchID}.json` Bootstrap + Socket.IO 快状态流。
- Draft：DLTV `account_id + hero_id + team_slot + team` 是第一主路径。
- R.O.S.H.：新项目自己生成分钟级阵容曲线。
- Live：第一版只信 `game_time + kills + team NW lead`，个人详细数据必须经过 freshness 验证。
- 最大剩余未知：RayBet ↔ DLTV 的真实时间偏移。

因此 TI 前最关键的工程目标已经非常明确：

> **把两个实时流稳定录下来、建立统一 Map Identity、生成不可变 Snapshot，并让多个 AI 在相同 Snapshot 上做独立判断。**

这条链一旦跑通，系统就已经可以进入 TI 2026 Shadow 实战。
