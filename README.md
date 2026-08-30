# 市场航图 · Marketor

一个可直接交给 Codex 继续开发的本地 Python 多指数行情分析项目。默认使用随项目附带的沪深300历史 CSV，同时已经具备多标的和多统计方法扩展接口，提供：

- 2005-01-04 至 2026-08-28 历史行情查询
- MA60/MA250/MA500/MA1250（图表均线，另计算 5/10/20/180 供 API 使用）
- 各均线乖离率
- RSI14（Wilder）与 RSI 75/70 高位回落信号
- 250日高点回撤、5日/20日涨跌幅
- 当前加仓辅助提醒
- 当前减仓辅助提醒
- 任意日期区间历史查询
- 1/7/30/365/730/1095/1825自然日持有收益统计
- FastAPI HTTP API 与网页仪表盘
- Typer 命令行工具
- JSON 标的目录（新增行情无需修改服务代码）
- 可注册的持有收益统计方法（内置 `summary`、`distribution`）
- 二十二个内置指数（16 只随包附带数据，6 只已配置待拉取），覆盖沪深宽基、上证系列、创业板、科创板、双创、红利与北交所风格
- 多指数相对便宜排名、长期乖离/RSI/回撤历史分位
- 独立的 0～100 加仓分与减仓分（不改变原有策略信号）
- 年线低位事件去重回测及事件后 1/3/5 年收益
- “主源 + 备用源 + 本地 CSV”三层在线数据源结构，来源记录写入 CSV 旁的 `.meta.json`

## 1. 安装

### Windows 桌面应用（推荐）

双击项目根目录的 `launch-app.cmd` 即可。应用会打开独立的 Windows 窗口，不需要浏览器或本地网址。首次启动会在项目内创建 `.venv` 并安装依赖。

桌面应用包含关键指标卡、长期均线图、加减仓信号解释、指数切换和历史收益表。点击“指数排名”可横向比较；双击排名中的指数可查看 `MA250 乖离≤-10%` 的独立历史事件。右上角可即时切换“墨绿夜色、深海蓝、石墨紫、象牙日光”四套主题，选择会自动保存。应用已适配 Windows Per-Monitor 高分屏缩放，带标签的下拉栏会随 DPI 自动调整尺寸。FastAPI 网页与 HTTP API 仍作为可选开发接口保留。

右上角数据源默认选择“自动”：按 `data/instruments.json` 中每只指数配置的优先级尝试在线源（中国指数主源为东方财富 `index_zh_a_hist` 代码直查，备用源为腾讯），全部失败后回退本地 CSV。“刷新本地”不访问网络。

### 手动安装

Windows PowerShell：

```powershell
cd 你的项目目录
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## 2. 在线行情数据源（主源 + 备用源 + 本地 CSV）

默认配置无需账户或 Token。每个指数通过 `data/instruments.json` 配置自己的优先级，结构为三层：

```text
主源  → 东方财富（AKShare index_zh_a_hist 代码直查，自动识别 sh/sz/csi/bj 市场）
备用源 → AKShare/腾讯（stock_zh_index_daily_tx）
兜底   → 本地 CSV（所有在线源失败时继续使用本地数据）
```

`source_priority` 示例：`["eastmoney", "tencent", "baostock", "tushare"]`——按顺序尝试，第一个成功的源接管；东方财富优先使用 `ak.index_zh_a_hist(symbol="000300")` 这种纯代码直查方式，接口内部自行判断指数市场，只有该代码不在其覆盖范围时才回退到带前缀的 `stock_zh_index_daily_em`。

桌面窗口提供“自动 / BaoStock / 腾讯 / 东方财富 / Tushare / 仅本地”下拉框，并显示当前数据源、在线状态和最新交易日。**每次在线源接管前**，程序都会用最近至少 10 个重叠交易日的收盘价做一致性校验（默认 1% 容差），通过后才允许拼接新数据；冲突或网络异常不会改写原 CSV。

**来源记录**：每次在线更新成功后，会在 CSV 旁边写入 `data/<文件名>.csv.meta.json`，记录 `source`、`source_priority`、`download_time`、`latest_date`、`overlap_records`、`new_records` 等字段，可用 `csi300 source-meta --symbol <代码>` 查看。

腾讯的 `amount` 文档口径为“手”，东方财富成交额为人民币元。程序不会混写这两个单位：腾讯成交量只保留在 `LOTS` 标的，东方财富成交额只在 `CNY_THOUSAND` 标的中换算成千元。

当前目录中的22个指数为：沪深300、中证500、中证1000、创业板指、中证800、中证红利、上证综指、深证成指、上证50、上证180、上证380、中证100、中证A500、中证全指、科创50、上证红利（16 只随包附带数据），以及科创100、双创50、红利低波100、创业板50、北证50、中证2000（已配置，执行下方 `bootstrap` 命令拉取数据）。

Tushare 只是可选备用源。如需启用，将 `.env.example` 复制为 `.env`，填写：

```text
TUSHARE_TOKEN=你的_token
```

`.env` 已加入 `.gitignore`，不要把它提交到 Git 或发送给他人。也可以只在当前 PowerShell 会话设置：

```powershell
$env:TUSHARE_TOKEN = "你的_token"
```

BaoStock 已是默认依赖。如需单独安装：

```powershell
pip install baostock
```

如需安装可选 Tushare 适配器：

```powershell
pip install -e ".[tushare]"
```

## 3. 命令行

```powershell
csi300 latest
csi300 latest --symbol csi300
csi300 signal
csi300 indicators --days 30
csi300 history --start 2026-08-01 --end 2026-08-28
csi300 holding-returns --symbol csi300 --method distribution --days 30,365,1825
csi300 instruments
csi300 statistics-methods
python -m csi300 compare
python -m csi300 events --symbol csi300 --threshold -0.10 --cooldown 60
python -m csi300 update --source auto
python -m csi300 update --source baostock
python -m csi300 update --symbol sse_composite --source tencent
python -m csi300 update --symbol star50 --source auto
python -m csi300 update --source eastmoney
python -m csi300 update --source local
python -m csi300 status
python -m csi300 source-meta --symbol csi300
python -m csi300 bootstrap --symbol star100 --source eastmoney
python -m csi300 bootstrap --symbol csi2000 --source eastmoney
```

`update` 会从本地最后日期之前至少 10 个交易日开始下载，以重叠收盘价验证数据口径。验证通过后只追加新交易日，并通过临时文件原子替换 CSV；数据冲突或网络异常不会改写原文件。`bootstrap` 用于给尚无本地 CSV 的指数初始化完整历史（如科创100、中证2000 等 6 只新指数），默认主源为东方财富。需要让失败返回非零退出码时使用：

```powershell
python -m csi300 update --source baostock --strict
```

## 4. 启动 API

```powershell
uvicorn csi300_service.api:app --reload
```

然后浏览：

- `http://127.0.0.1:8000/` — 本地行情分析仪表盘
- `http://127.0.0.1:8000/docs` — Swagger API 文档
- `/api` — API 端点索引
- `/latest` — 最新完整指标
- `/instruments` — 已配置标的及数据范围
- `/comparison` — 全部指数的历史分位、加减仓评分与相对便宜排名
- `/events?symbol=csi300&threshold=-0.10&cooldown=60` — 去重信号事件及后续收益
- `/indicators?days=30` — 最近30交易日指标
- `/history?start=2026-08-01&end=2026-08-28` — 历史行情
- `/signal` — 当前加减仓辅助提醒
- `/holding-returns?symbol=csi300&method=distribution&days=30,365,1825` — 可选方法与周期的持有收益统计
- `/statistics/methods` — 可用统计方法

所有原有端点不传 `symbol` 时仍默认使用 `csi300`，因此旧调用保持兼容。

## 5. 多指数排名、评分与事件模式

“相对便宜排名”综合长期位置历史分位和加减仓评分，并对过热信号扣分。它是横向筛选工具，不是收益预测。历史分位表示历史上小于等于当前值的观测占比。

加仓分按 MA250 负乖离、RSI 超卖、一年回撤及 MA1250 长周期低位累计；减仓分按 MA500 正乖离、RSI 过热、接近一年高点及 MA1250 长周期过热累计。分数分档为正常、轻度、明显、重度和极端，但不会改变原有 `1.0x～3.0x` 与 `0%～40%` 策略输出。

事件模式只在条件由未触发变为触发时记录一次，再应用默认 60 个交易日冷却期，避免把同一轮连续低位按天重复统计。CLI/API 可修改指标、阈值、方向和冷却期。

## 6. 增加其他行情

把至少包含 `date,close` 的 CSV 放入 `data/`。OHLC、成交额、收益率和净值列是可选列；若提供，列名使用 `open,high,low,close,amount,return,net_value`。然后在 `data/instruments.json` 增加一项：

```json
{
  "symbol": "sp500",
  "name": "S&P 500",
  "asset_class": "index",
  "currency": "USD",
  "provider_code": "SPX",
  "amount_unit": "USD",
  "data_file": "sp500.csv"
}
```

随后 CLI 使用 `--symbol sp500`，HTTP API 使用 `?symbol=sp500`。目录会校验重复代码及越界文件路径。

## 7. 增加统计方法

持有收益内置两种汇总：

- `summary`：均值、中位数、正收益率、最小值、最大值。
- `distribution`：在 summary 基础上增加标准差及 P10/P25/P75/P90 分位数。

扩展模块可调用 `register_statistics_method(name, callable)` 注册新算法；回调接收 NumPy 收益率数组并返回可 JSON 序列化的指标字典。服务、CLI 和 API 会自动使用注册后的方法。

## 8. 默认策略

### 加仓侧

以 **250日线负乖离** 为主：

| 条件 | 基础投入倍数 |
|---|---:|
| 250日线上 | 1.0x |
| 0~-5% | 1.2x |
| -5~-10% | 1.5x |
| -10~-15% | 2.0x |
| <=-15% | 2.5x |

辅助：

- RSI14 < 35：+0.5x
- RSI14 < 30：+1.0x
- 低于1250日线10%以上：+0.5x
- 最终上限：3.0x

### 减仓侧

以 **500日线正乖离** 为主：

| 条件 | 基础累计减仓参考 |
|---|---:|
| <+10% | 0% |
| +10~15% | 10% |
| +15~20% | 15% |
| +20~25% | 25% |
| >=+25% | 30% |

辅助确认：

- 1250日线正乖离 >=20%：+5%
- >=30%：+10%
- RSI从75以上回落：+10%
- RSI从70以上回落：+5%
- 总减仓上限40%，避免仅凭技术指标清空核心仓位

## 9. 当前数据末日示例

项目自带 CSV 最后日期为 **2026-08-28**。运行：

```powershell
csi300 signal
```

即可根据项目内统一计算口径得到最新辅助信号。

## 10. 后续开发建议

项目根目录已包含 `AGENTS.md`。可以直接在 Codex 中继续要求：

1. 为已配置但尚未拉取的科创100、双创50、红利低波100、创业板50、北证50、中证2000 执行 `python -m csi300 bootstrap --symbol <代码> --source eastmoney`；接入全收益及海外指数时需提供可验证的可靠数据源；不以 ETF 静默冒充指数。
2. 增加策略 vs 买入持有面板，输出 CAGR、最大回撤、Sharpe、Calmar、现金占用与换手率。
3. 增加组合目标权重、再平衡、相关性矩阵和风险贡献。
4. 仅在信号档位变化时提醒，并为同类提醒设置冷却时间。
5. 增加历史相似行情与多指数轮动，并做 walk-forward / 样本外验证。

## 风险说明

本项目输出为历史统计和辅助决策信号，不构成收益保证或自动交易指令。价格指数也不等于包含完整分红再投资的沪深300全收益指数，长期基金回报研究应进一步加入全收益指数或真实基金净值对照。
