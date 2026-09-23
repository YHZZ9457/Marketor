const state = { symbol: "csi300", days: 250, instruments: [], generation: 0 };
let symbolDropdown = null;
let methodDropdown = null;

const $ = (id) => document.getElementById(id);
const formatNumber = (value, digits = 2) => value == null ? "—" : Number(value).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const formatPct = (value, digits = 2) => value == null ? "—" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;

function setDirection(element, value) {
  element.classList.remove("positive", "negative");
  if (value > 0) element.classList.add("positive");
  if (value < 0) element.classList.add("negative");
}

/* ---- status bar ---- */
let statusTimer = null;

function showStatus(message, kind = "info") {
  const wrap = $("status-wrap");
  const status = $("status");
  $("status-text").textContent = message || "";
  status.classList.toggle("success", kind === "success");
  status.classList.toggle("error", kind === "error");
  status.querySelector(".status-icon").textContent = kind === "success" ? "✓" : kind === "error" ? "!" : "";
  wrap.classList.toggle("visible", Boolean(message));
  clearTimeout(statusTimer);
  if (kind === "success") {
    statusTimer = setTimeout(() => {
      if (!$("status").classList.contains("error")) $("status-wrap").classList.remove("visible");
    }, 2200);
  }
}

/* ---- custom dropdown ---- */
function createDropdown({ options, value, onChange, ariaLabel }) {
  const CHECK = '<svg class="dropdown-check" viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const host = document.createElement("div");
  host.className = "dropdown";
  host.innerHTML = `
    <button type="button" class="dropdown-trigger" aria-haspopup="listbox" aria-expanded="false" aria-label="${ariaLabel}">
      <span class="dropdown-value"></span>
      <svg class="dropdown-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m4.2 6.2 3.8 3.8 3.8-3.8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <ul class="dropdown-menu" role="listbox" aria-label="${ariaLabel}"></ul>`;

  const trigger = host.querySelector(".dropdown-trigger");
  const menu = host.querySelector(".dropdown-menu");
  const valueEl = host.querySelector(".dropdown-value");
  const items = new Map();
  let committed = value;
  let preview = value;
  let activeIndex = -1;

  function renderOptions() {
    menu.replaceChildren();
    items.clear();
    options.forEach((option, index) => {
      const li = document.createElement("li");
      li.className = "dropdown-option";
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");
      li.tabIndex = -1;
      li.innerHTML = `<span class="option-label"></span>${CHECK}`;
      li.querySelector(".option-label").textContent = option.label;
      li.addEventListener("click", () => choose(option.value));
      li.addEventListener("mousemove", () => highlight(li, index));
      menu.append(li);
      items.set(option.value, li);
    });
    activeIndex = Math.max(0, options.findIndex((option) => option.value === committed));
  }

  function render() {
    const current = options.find((option) => option.value === preview) || options[0];
    valueEl.textContent = current ? current.label : "";
    items.forEach((li, optionValue) => {
      const selected = optionValue === committed;
      li.classList.toggle("selected", selected);
      li.setAttribute("aria-selected", String(selected));
    });
  }

  function highlight(li, index = activeIndex) {
    activeIndex = index;
    menu.querySelectorAll(".dropdown-option.active").forEach((item) => item.classList.remove("active"));
    if (li) {
      li.classList.add("active");
      li.scrollIntoView({ block: "nearest" });
    }
  }

  function isOpen() { return host.classList.contains("open"); }

  function open() {
    renderOptions();
    render();
    host.classList.add("open");
    trigger.setAttribute("aria-expanded", "true");
    const active = [...items.values()][activeIndex];
    if (active) highlight(active, activeIndex);
  }

  function close() {
    host.classList.remove("open");
    trigger.setAttribute("aria-expanded", "false");
    preview = committed;
    render();
  }

  function choose(next) {
    if (next !== committed) {
      committed = next;
      preview = next;
      onChange(next);
    }
    close();
    trigger.focus();
  }

  function move(step) {
    const values = [...items.keys()];
    if (!values.length) return;
    activeIndex = (activeIndex + step + values.length) % values.length;
    preview = values[activeIndex];
    render();
    highlight(items.get(preview), activeIndex);
  }

  trigger.addEventListener("click", (event) => {
    event.stopPropagation();
    if (isOpen()) close(); else open();
  });
  trigger.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!isOpen()) open();
      move(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (isOpen()) choose(preview); else open();
    } else if (event.key === " " || event.key === "Spacebar") {
      event.preventDefault();
      if (isOpen()) close(); else open();
    } else if (event.key === "Escape" && isOpen()) {
      close();
    }
  });
  document.addEventListener("click", (event) => {
    if (!host.contains(event.target)) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && isOpen()) { close(); trigger.focus(); }
  });

  renderOptions();
  render();
  return {
    host,
    get value() { return committed; },
    setOptions(nextOptions) { options = nextOptions; renderOptions(); render(); },
  };
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try { message = (await response.json()).detail || message; } catch (_) {}
    throw new Error(message);
  }
  return response.json();
}

function renderHeader(instrument, latest) {
  $("instrument-name").textContent = instrument.name;
  $("instrument-kind").textContent = `${instrument.asset_class.toUpperCase()} · ${instrument.currency}`;
  $("data-date").textContent = latest.date;
  $("latest-price").textContent = formatNumber(latest.close);
  $("ret-20d").textContent = `近20日 ${formatPct(latest.ret_20d)}`;
  setDirection($("ret-20d"), latest.ret_20d);
  $("data-range").textContent = `${instrument.first_date} — ${instrument.last_date}`;
  $("row-count").textContent = `${Number(instrument.rows).toLocaleString("zh-CN")} 条记录`;

  [["bias-250", latest.bias250], ["bias-500", latest.bias500], ["bias-1250", latest.bias1250], ["drawdown-250", latest.drawdown_250d]].forEach(([id, value]) => {
    $(id).textContent = formatPct(value);
    setDirection($(id), value);
  });
  $("rsi-14").textContent = formatNumber(latest.rsi14, 1);
  $("rsi-marker").style.left = `${Math.max(0, Math.min(100, latest.rsi14 ?? 50))}%`;
}

function renderSignal(signal) {
  state.strategyId = signal.strategy_id || "adaptive";
  state.reference = signal.daily_reference;
  renderReference();
  const isV1 = signal.strategy_id === "ma_dynamic_v1";
  $("buy-card").querySelector("h2").textContent = isV1 ? "V1 加仓条件" : "个性化加仓倍数";
  $("sell-card").querySelector("h2").textContent = isV1 ? "V1 减仓条件" : "个性化减仓参考";
  document.querySelectorAll(".signal-title .kicker").forEach(item => { item.textContent = isV1 ? "MA DYNAMIC V1" : "ADAPTIVE STRATEGY"; });
  const sides = [
    { key: "accumulation", level: "buy-level", score: "buy-score", action: "buy-action", reasons: "buy-reasons", suffix: signal.strategy_id === "ma_dynamic_v1" ? "%" : "×" },
    { key: "reduction", level: "sell-level", score: "sell-score", action: "sell-action", reasons: "sell-reasons", suffix: "%" },
  ];
  sides.forEach(({ key, level, score, action, reasons, suffix }) => {
    const item = signal[key];
    $(score).textContent = `${Number(item.score).toFixed(suffix === "×" ? 1 : 0)}${suffix}`;
    $(level).textContent = signal.strategy_id === "ma_dynamic_v1"
      ? `${item.level} · 当日${key === "accumulation" ? "亏损" : "盈利"}比例`
      : `${item.level}信号`;
    $(action).textContent = item.suggested_action;
    const list = $(reasons);
    list.replaceChildren(...item.reasons.map((reason) => {
      const li = document.createElement("li"); li.textContent = reason; return li;
    }));
  });
}

function renderReference() {
  const ref = state.reference;
  const raw = $("reference-equity").value.trim();
  const equity = Number(raw);
  document.querySelectorAll("[data-equity]").forEach((button) => button.classList.toggle("active", Number(button.dataset.equity) === equity));
  if (!raw || !Number.isFinite(equity) || equity < 0) {
    $("reference-result").textContent = "请输入非负、有限的权益市值";
    return;
  }
  if (!ref || ref.status !== "ok") {
    $("reference-result").textContent = state.strategyId === "adaptive" ? "当前为个性化倍数策略，不使用 V1 金额换算" : "暂无V1金额参考：需有效日收益和MA250数据";
    return;
  }
  const coefficient = equity / 10000;
  $("reference-result").textContent = `${ref.date} · 系数 ${coefficient} · 加仓 ${formatNumber(ref.baseline_buy * coefficient)} 元 / 减仓 ${formatNumber(ref.baseline_sell * coefficient)} 元。${ref.basis}。${ref.note}`;
}
$("reference-equity").addEventListener("input", renderReference);
document.querySelectorAll("[data-equity]").forEach((button) => button.addEventListener("click", () => {
  $("reference-equity").value = button.dataset.equity;
  renderReference();
}));

function linePath(rows, key, x, y) {
  let started = false;
  return rows.reduce((path, row, index) => {
    const value = row[key];
    if (value == null) { started = false; return path; }
    const command = started ? "L" : "M";
    started = true;
    return `${path}${command}${x(index).toFixed(2)},${y(value).toFixed(2)} `;
  }, "");
}

function renderChart(rows) {
  const host = $("chart");
  state.chartRows = rows;
  host.replaceChildren();
  if (!rows.length) { host.innerHTML = '<div class="chart-empty">所选周期暂无数据</div>'; return; }
  const width = Math.max(320, host.clientWidth), height = Math.max(260, host.clientHeight), margin = { top: 12, right: 66, bottom: 28, left: 8 };
  const series = ["close", "ma60", "ma250", "ma500", "ma1250"];
  const values = rows.flatMap((row) => series.map((key) => row[key]).filter((value) => value != null));
  const rawMin = Math.min(...values), rawMax = Math.max(...values), pad = Math.max((rawMax - rawMin) * .09, rawMax * .01);
  const min = rawMin - pad, max = rawMax + pad;
  const x = (index) => margin.left + index / Math.max(1, rows.length - 1) * (width - margin.left - margin.right);
  const y = (value) => margin.top + (max - value) / (max - min) * (height - margin.top - margin.bottom);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "收盘价和长期均线走势图");

  for (let i = 0; i < 5; i++) {
    const gy = margin.top + i / 4 * (height - margin.top - margin.bottom);
    const line = document.createElementNS(svg.namespaceURI, "line");
    line.setAttribute("x1", margin.left); line.setAttribute("x2", width - margin.right); line.setAttribute("y1", gy); line.setAttribute("y2", gy); line.setAttribute("class", "chart-grid"); svg.append(line);
    const label = document.createElementNS(svg.namespaceURI, "text");
    label.setAttribute("x", width - margin.right + 9); label.setAttribute("y", gy + 4); label.setAttribute("class", "chart-label"); label.textContent = formatNumber(max - i / 4 * (max - min), 0); svg.append(label);
  }
  [0, Math.floor((rows.length - 1) / 2), rows.length - 1].forEach((index, i) => {
    const label = document.createElementNS(svg.namespaceURI, "text");
    label.setAttribute("x", x(index)); label.setAttribute("y", height - 4); label.setAttribute("text-anchor", i === 0 ? "start" : i === 2 ? "end" : "middle"); label.setAttribute("class", "chart-label"); label.textContent = rows[index].date; svg.append(label);
  });
  const colors = { close: "#edf2f3", ma60: "#c3b3f0", ma250: "#71d4bc", ma500: "#ddbd80", ma1250: "#83bfe0" };
  series.forEach((key) => {
    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute("d", linePath(rows, key, x, y)); path.setAttribute("class", "chart-line"); path.setAttribute("stroke", colors[key]); path.setAttribute("stroke-width", key === "close" ? "2.3" : "1.55"); path.setAttribute("opacity", key === "close" ? "1" : ".9"); svg.append(path);
  });
  host.append(svg);
}

function renderReturns(rows) {
  const labels = { 1: "1天", 7: "1周", 30: "1月", 365: "1年", 730: "2年", 1095: "3年", 1825: "5年" };
  const body = $("returns-body"); body.replaceChildren();
  const distribution = methodDropdown.value === "distribution";
  $("returns-head").replaceChildren();
  const header = document.createElement("tr");
  ["持有期", "样本数", "平均收益", "中位数", "正收益率", "最差", "最好", ...(distribution ? ["P10", "P25", "P75", "P90", "标准差"] : [])].forEach(label => {
    const th = document.createElement("th"); th.textContent = label; header.append(th);
  });
  $("returns-head").append(header);
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const values = [labels[row.days] || `${row.days}天`, row.samples.toLocaleString("zh-CN"), formatPct(row.mean), formatPct(row.median), formatPct(row.positive_rate), formatPct(row.min), formatPct(row.max)];
    values.forEach((value, index) => { const td = document.createElement("td"); td.textContent = value; if (index >= 2 && index !== 4) setDirection(td, row[[null, null, "mean", "median", "positive_rate", "min", "max"][index]]); tr.append(td); });
    if (distribution) ["p10", "p25", "p75", "p90", "std"].forEach(key => {
      const td = document.createElement("td"); td.textContent = formatPct(row[key]); tr.append(td);
    });
    body.append(tr);
  });
}

function clearDashboard() {
  state.strategyId = null;
  state.reference = null;
  renderReference();
  ["latest-price", "data-date", "data-range", "row-count", "ret-20d", "bias-250", "bias-500", "bias-1250", "drawdown-250", "rsi-14", "buy-level", "sell-level", "buy-score", "sell-score", "buy-action", "sell-action"].forEach(id => { $(id).textContent = "—"; setDirection($(id), null); });
  $("rsi-marker").style.left = "50%";
  ["buy-reasons", "sell-reasons", "returns-body"].forEach(id => $(id).replaceChildren());
  renderChart([]);
}

async function loadDashboard() {
  const generation = ++state.generation;
  clearDashboard();
  const instrument = state.instruments.find(item => item.symbol === state.symbol);
  $("instrument-name").textContent = instrument?.name || state.symbol;
  $("instrument-kind").textContent = instrument ? `${instrument.asset_class.toUpperCase()} · ${instrument.currency}` : "—";
  showStatus("正在读取本地行情…", "loading");
  const symbol = encodeURIComponent(state.symbol);
  const method = encodeURIComponent(methodDropdown.value);
  $("ma-dynamic-status").textContent = "正在读取策略…";
  $("ma-dynamic-summary").textContent = "";
  if (instrument?.data_available === false) {
    $("ma-dynamic-status").textContent = "尚无本地行情，无法回测";
    showStatus("该标的尚无本地 CSV，请先通过命令行 bootstrap 拉取行情，再刷新页面。", "error");
    return;
  }
  fetchJson(`/strategies/ma-dynamic-v1?symbol=${symbol}`).then((result) => {
    if (generation !== state.generation) return;
    $("ma-dynamic-status").textContent = result.status === "ok"
      ? `回测 ${result.start} — ${result.end} · 全收益指数 ${result.total_return_code}`
      : result.message;
    if (result.summary) {
      const s = result.summary;
      $("ma-dynamic-summary").textContent = `持仓 ${formatNumber(s.holding_value)}元 · 现金池 ${formatNumber(s.cash)}元 · 累计外部投入 ${formatNumber(s.external_total)}元 · 总盈亏 ${formatNumber(s.profit)}元 · 交易 ${s.trade_count}次`;
    }
  }).catch((error) => {
    if (generation === state.generation) $("ma-dynamic-status").textContent = `无法回测：${error.message}`;
  });
  try {
    const [latest, signal, indicators, returns] = await Promise.all([
      fetchJson(`/latest?symbol=${symbol}`), fetchJson(`/signal?symbol=${symbol}`),
      fetchJson(`/indicators?symbol=${symbol}&days=${state.days}`),
      fetchJson(`/holding-returns?symbol=${symbol}&method=${method}`),
    ]);
    if (generation !== state.generation) return;
    renderHeader(instrument, latest); renderSignal(signal); renderChart(indicators); renderReturns(returns);
    showStatus(`已更新 · ${instrument?.name || state.symbol} · 数据截至 ${latest.date}`, "success");
  } catch (error) { if (generation === state.generation) showStatus(`无法加载数据：${error.message}`, "error"); }
}

async function boot() {
  try {
    state.instruments = await fetchJson("/instruments");
    if (!state.instruments.some(item => item.symbol === state.symbol)) {
      state.symbol = (state.instruments.find(item => item.data_available !== false) || state.instruments[0])?.symbol;
    }
    if (!state.symbol) throw new Error("未配置可选标的");
    symbolDropdown = createDropdown({
      options: state.instruments.map((item) => ({
        value: item.symbol,
        label: item.data_available === false ? `${item.name} · ${item.symbol}（待拉取）` : `${item.name} · ${item.symbol}`,
      })),
      value: state.symbol,
      onChange: (value) => { state.symbol = value; loadDashboard(); },
      ariaLabel: "选择行情标的",
    });
    $("symbol-select").appendChild(symbolDropdown.host);
    methodDropdown = createDropdown({
      options: [{ value: "summary", label: "概要" }, { value: "distribution", label: "分布" }],
      value: "summary",
      onChange: () => loadDashboard(),
      ariaLabel: "选择统计方法",
    });
    $("method-select").appendChild(methodDropdown.host);
    $("reload-button").addEventListener("click", async () => {
      try {
        state.instruments = await fetchJson("/instruments");
        symbolDropdown.setOptions(state.instruments.map(item => ({
          value: item.symbol,
          label: item.data_available === false ? `${item.name} · ${item.symbol}（待拉取）` : `${item.name} · ${item.symbol}`,
        })));
        await loadDashboard();
      } catch (error) { showStatus(`无法刷新目录：${error.message}`, "error"); }
    });
    document.querySelectorAll("[data-days]").forEach((button) => button.addEventListener("click", () => {
      state.days = Number(button.dataset.days);
      document.querySelectorAll("[data-days]").forEach((item) => item.classList.toggle("active", item === button));
      loadDashboard();
    }));
    await loadDashboard();
  } catch (error) { showStatus(`仪表盘启动失败：${error.message}`, "error"); }
}

document.addEventListener("DOMContentLoaded", boot);
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (state.chartRows) renderChart(state.chartRows); }, 100);
});
const navigationSections = ["overview", "trend", "signals", "history"].map($);
function updateNavigation() {
  const boundary = Math.min(180, window.innerHeight * .3);
  const current = navigationSections.filter(section => section.getBoundingClientRect().top <= boundary).pop() || navigationSections[0];
  document.querySelectorAll(".sidebar nav a").forEach(link => {
    if (link.hash === `#${current.id}`) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  });
}
let navigationFrame = null;
window.addEventListener("scroll", () => {
  if (navigationFrame !== null) return;
  navigationFrame = requestAnimationFrame(() => { updateNavigation(); navigationFrame = null; });
}, { passive: true });
window.addEventListener("resize", updateNavigation);
updateNavigation();
