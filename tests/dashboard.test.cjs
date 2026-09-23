const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');

function element() {
  return { textContent: '', value: '10000', style: {}, children: [], dataset: {},
    classList: { add() {}, remove() {}, toggle() {} },
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; },
    addEventListener() {}, setAttribute() {}, removeAttribute() {},
    querySelector() { return element(); },
    getBoundingClientRect() { return { top: 0 }; },
  };
}
function context() {
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
  const sandbox = vm.createContext({
    document: { getElementById: get, querySelectorAll: () => [], addEventListener() {}, createElement: element },
    window: { innerHeight: 800, addEventListener() {} }, setTimeout: () => 1, clearTimeout() {},
    requestAnimationFrame() {}, console,
  });
  vm.runInContext(fs.readFileSync('src/csi300_service/web/dashboard.js', 'utf8'), sandbox);
  vm.runInContext(`methodDropdown = { value: 'summary' };`, sandbox);
  return { sandbox, get, run: code => vm.runInContext(code, sandbox) };
}

test('an older response cannot overwrite a newer symbol or period', async () => {
  const { sandbox, run } = context();
  const pending = [];
  sandbox.getData = url => new Promise((resolve, reject) => pending.push({ url, resolve, reject }));
  run(`
    fetchJson = getData;
    state.instruments = [{symbol:'a', name:'A', asset_class:'index', currency:'CNY'}, {symbol:'b', name:'B', asset_class:'index', currency:'CNY'}];
    clearDashboard = () => {};
    renderHeader = (instrument) => { state.rendered = instrument.symbol; };
    renderSignal = renderChart = renderReturns = () => {};
    showStatus = message => { state.message = message; };
    state.symbol = 'a';
  `);
  const first = run('loadDashboard()');
  run("state.symbol = 'b'");
  const second = run('loadDashboard()');
  pending.slice(5).forEach(item => item.resolve({date: 'new'}));
  await second;
  assert.equal(run('state.rendered'), 'b');
  pending.slice(0, 5).forEach(item => item.resolve({date: 'old'}));
  await first;
  assert.equal(run('state.rendered'), 'b');
  assert.match(run('state.message'), /new/);
  // Same symbol, different period: symbol-only checks would incorrectly accept it.
  const third = run('loadDashboard()');
  run('state.days = 500');
  const fourth = run('loadDashboard()');
  pending.slice(15).forEach(item => item.resolve({date: 'period-new'}));
  await fourth;
  pending.slice(10, 15).forEach(item => item.reject(new Error('stale failure')));
  await third;
  assert.match(run('state.message'), /period-new/);
});

test('distribution mode exposes percentiles, including missing samples', () => {
  const { run, get } = context();
  run(`methodDropdown.value = 'distribution'; renderReturns([{days: 30, samples: 0}]);`);
  assert.equal(get('returns-head').children[0].children.length, 12);
  assert.equal(get('returns-body').children[0].children.length, 12);
  assert.equal(get('returns-body').children[0].children[7].textContent, '—');
});

test('RSI zero remains zero and adaptive signals show a multiplier', () => {
  const { run, get } = context();
  run(`renderHeader({name:'Demo', asset_class:'stock', currency:'CNY'}, {rsi14:0});`);
  assert.equal(get('rsi-marker').style.left, '0%');
  run(`renderSignal({accumulation:{score:1.5, level:'中', suggested_action:'', reasons:[]}, reduction:{score:15,level:'中',suggested_action:'',reasons:[]}});`);
  assert.equal(get('buy-score').textContent, '1.5×');
});

test('missing local data clears existing results without issuing requests', async () => {
  const { run, get } = context();
  run(`state.instruments = [{symbol:'ghost', name:'Missing', asset_class:'index', currency:'CNY', data_available:false}]; state.symbol='ghost'; renderChart = () => {}; fetchJson = () => { throw new Error('should not fetch'); };`);
  get('latest-price').textContent = '12345';
  await run('loadDashboard()');
  assert.equal(get('latest-price').textContent, '—');
  assert.match(get('status-text').textContent, /尚无本地 CSV/);
});
