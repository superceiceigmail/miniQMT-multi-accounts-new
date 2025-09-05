// Toast提示
function showToast(msg, color) {
  var toast = document.getElementById('toast');
  toast.innerText = msg;
  if (color) toast.style.background = color;
  else toast.style.background = '#409eff';
  toast.style.display = 'block';
  setTimeout(() => { toast.style.opacity = '1'; }, 10);
  clearTimeout(window.toastTimeout1);
  clearTimeout(window.toastTimeout2);
  window.toastTimeout1 = setTimeout(() => { toast.style.opacity = '0'; }, 1500);
  window.toastTimeout2 = setTimeout(() => { toast.style.display = 'none'; }, 2000);
}

// ==== 股票代码-名称映射 ====
let nameVsCode = {}; // 股票代码->名称映射

// 异步加载股票代码映射表
async function loadNameVsCode() {
  try {
    nameVsCode = await fetch('./utils/stocks_code_search_tool/stocks_data/name_vs_code.json?t=' + Date.now()).then(r => r.json());
  } catch (e) {
    nameVsCode = {};
  }
}

// ==== 账户持仓信息 ====
// 新增工具函数：统计参考市值
function getReferenceMarketValue(stockName) {
  let sum = 0;
  Object.values(strategies).forEach(targets => {
    targets.forEach(t => {
      if (t.name === stockName && t.hold) {
        sum += Number(t.default_amount) || 0;
      }
    });
  });
  return sum;
}

let stockMarketValueMap = {}, stockPercentMap = {}, assetTotal = 0, cash = 0, marketValue = 0;
async function loadAccountInfo() {
  let asset, positionsData;
  try {
    asset = await fetch('./template_account_info/template_account_asset_info.json?t=' + Date.now()).then(r => r.json());
    positionsData = await fetch('./template_account_info/template_account_position_info.json?t=' + Date.now()).then(r => r.json());
  } catch (e) {
    document.getElementById('errormsg').textContent = '读取账户信息失败：' + e;
    return;
  }
  // 新增：显示更新时间
  let lastUpdate = positionsData.last_update;
  document.getElementById('position-update-time').textContent = lastUpdate
    ? `最后更新时间: ${formatDateTime(lastUpdate)}`
    : '';
  let positions = positionsData.positions || [];
  assetTotal = Number(asset.total_asset) || 0;
  cash = Number(asset.cash) || 0;
  marketValue = Number(asset.market_value) || 0;
  let assetDiv = document.getElementById('account-asset-info');
  assetDiv.innerHTML = `
    <b>账户ID:</b> ${asset.account_id} &nbsp;
    <b>总资产:</b> ${assetTotal.toFixed(2)} &nbsp;
    <b>可用现金:</b> ${cash.toFixed(2)} &nbsp;
    <b>冻结资金:</b> ${Number(asset.frozen_cash).toFixed(2)} &nbsp;
    <b>持仓市值:</b> ${marketValue.toFixed(2)} &nbsp;
    <b>现金占比:</b> ${asset.percent_cash} &nbsp;
    <b>持仓占比:</b> ${asset.percent_market}
  `;
  const tbody = document.getElementById('position-table').querySelector('tbody');
  tbody.innerHTML = '';
  stockMarketValueMap = {};
  stockPercentMap = {};

  // ---- 持仓排序 ----
  let withIndex = positions.map((pos, i) => ({ ...pos, _origIndex: i }));

  // 补全股票名称
  withIndex.forEach(pos => {
    if ((!pos.stock_name || pos.stock_name === '' || pos.stock_name === '未知股票')
        && pos.stock_code && nameVsCode[pos.stock_code]) {
      pos.stock_name = nameVsCode[pos.stock_code];
    }
  });

  // 查找关联策略
  withIndex.forEach(pos => {
    let relatedStrategies = [];
    if (pos.stock_name) {
      Object.entries(strategies).forEach(([strategyName, targets]) => {
        if (targets.some(t => t.name === pos.stock_name)) {
          relatedStrategies.push(strategyName);
        }
      });
    }
    pos._relatedStrategies = relatedStrategies;
  });

  // 排序逻辑
  withIndex.sort((a, b) => {
    const aUnknown = !a.stock_name;
    const bUnknown = !b.stock_name;
    if (aUnknown && !bUnknown) return 1;
    if (!aUnknown && bUnknown) return -1;
    if (aUnknown && bUnknown) return a._origIndex - b._origIndex;
    const aNoRel = a.stock_name && (!a._relatedStrategies || a._relatedStrategies.length === 0);
    const bNoRel = b.stock_name && (!b._relatedStrategies || b._relatedStrategies.length === 0);
    if (aNoRel && !bNoRel) return -1;
    if (!aNoRel && bNoRel) return 1;
    return a._origIndex - b._origIndex;
  });

  withIndex.forEach(pos => {
      const avg_price = (typeof pos.avg_price === 'number' && !isNaN(pos.avg_price)) ? pos.avg_price : null;
      const percent = assetTotal && pos.market_value
        ? ((pos.market_value / assetTotal) * 100).toFixed(2) + '%'
        : '0%';

      const relatedStrategies = pos._relatedStrategies || [];
      let relatedStrategiesHtml = '';
      if (relatedStrategies.length > 0) {
        relatedStrategiesHtml = relatedStrategies.map(rs => {
          const sArr = strategies[rs] || [];
          const found = sArr.find(t => t.name === pos.stock_name && t.hold === true);
          if (found) {
            return `<span class="strategy-related-hold">${rs}</span>`;
          } else {
            return rs;
          }
        }).join('、');
      }

      // ==== 参考市值（所有策略持有累加默认金额） ====
      let refMarketValue = '-';
      let refMarketValueNum = 0;
      if (pos.stock_name) {
        const ref = getReferenceMarketValue(pos.stock_name);
        refMarketValue = ref && ref > 0 ? ref.toFixed(2) : '-';
        refMarketValueNum = ref;
      }

      // ==== 计算差异并决定市值是否标红 ====
      let marketValue = typeof pos.market_value === 'number' ? pos.market_value : null;
      let marketValueCell = '-';
      if (marketValue !== null && refMarketValueNum > 0) {
        let diff = Math.abs(marketValue - refMarketValueNum) / refMarketValueNum;
        if (diff > 0.3) {
          marketValueCell = `<span style="color:#e74c3c;font-weight:bold;">${marketValue.toFixed(2)}</span>`;
        } else {
          marketValueCell = marketValue.toFixed(2);
        }
      } else if (marketValue !== null) {
        marketValueCell = marketValue.toFixed(2);
      }

      tbody.innerHTML += `
        <tr>
          <td>${pos.stock_code || '-'}</td>
          <td>${pos.stock_name || '-'}</td>
          <td>${marketValueCell}</td>
          <td>${refMarketValue}</td>
          <td>${typeof pos.volume === 'number' ? pos.volume : '-'}</td>
          <td>${typeof pos.can_use_volume === 'number' ? pos.can_use_volume : '-'}</td>
          <td>${avg_price !== null ? avg_price.toFixed(4) : '-'}</td>
          <td>${percent}</td>
          <td>${relatedStrategiesHtml}</td>
        </tr>
      `;
      if (pos.stock_name) {
        stockMarketValueMap[pos.stock_name] = typeof pos.market_value === 'number' ? pos.market_value : 0;
        stockPercentMap[pos.stock_name] = percent;
      }
    });
}

// ==== 策略维护 ====
const defaultStrategies = {
  "美股策略": [
    {name:"海外科技", default_amount: 11000, hold: false},
    {name:"纳指9941", default_amount: 11000, hold: false},
    {name:"纳指3100", default_amount: 11000, hold: false},
    {name:"嘉实黄金", default_amount: 11000, hold: false},
    {name:"美国消费", default_amount: 11000, hold: false},
    {name:"嘉实原油", default_amount: 11000, hold: false},
    {name:"黄金ETF", default_amount: 11000, hold: false},
    {name:"黄金主题", default_amount: 11000, hold: false},
    {name:"印度基金", default_amount: 11000, hold: false},
    {name:"纳指生物科技", default_amount: 11000, hold: false},
    {name:"原油易方达", default_amount: 11000, hold: false},
    {name:"中概互联网", default_amount: 11000, hold: false},
  ],
  "黄金策略": [
    {name:"黄金主题", default_amount: 11000, hold: false},
    {name:"黄金ETF", default_amount: 11000, hold: false},
    {name:"黄金LOF", default_amount: 11000, hold: false},
    {name:"嘉实黄金", default_amount: 11000, hold: false},
    {name:"标普医疗", default_amount: 11000, hold: false},
    {name:"美国消费", default_amount: 11000, hold: false},
    {name:"美国精选", default_amount: 11000, hold: false},
    {name:"国泰商品", default_amount: 11000, hold: false},
    {name:"嘉实原油", default_amount: 11000, hold: false},
    {name:"标普信息科技", default_amount: 11000, hold: false},
    {name:"印度基金", default_amount: 11000, hold: false},
    {name:"黄金主题", default_amount: 11000, hold: false},
  ],
  "国债策略": [
    {name:"30年国债", default_amount: 190000, hold: false},
    {name:"30年国债指数", default_amount: 130000, hold: false},
    {name:"可转债", default_amount: 80000, hold: false},
  ],
};
let strategies = getSavedStrategies();
function getSavedStrategies() {
  try {
    const saved = localStorage.getItem('strategies');
    if (saved) return JSON.parse(saved);
  } catch (e) {}
  return JSON.parse(JSON.stringify(defaultStrategies));
}
function saveStrategies() {
  localStorage.setItem('strategies', JSON.stringify(strategies));
}
const strategySelect = document.getElementById('strategy');
function renderStrategyOptions() {
  strategySelect.innerHTML = '<option value="">请选择策略</option>';
  Object.keys(strategies).forEach(s => {
    const opt = document.createElement('option');
    opt.value = s; opt.textContent = s;
    strategySelect.appendChild(opt);
  });
}
let plans = [];
let currentStrategy = "";

// ========== 标的操作相关 ==========
let editingTargetIdx = null; // 当前编辑的标的索引

function loadStrategy() {
  const s = strategySelect.value;
  if (!s) {
    document.getElementById('targets-box').style.display = 'none';
    currentStrategy = "";
    return;
  }
  currentStrategy = s;
  let targets = strategies[s];
  targets = targets.slice().sort((a, b) => (a.hold === b.hold ? 0 : a.hold ? -1 : 1));
  document.getElementById('targets-box').style.display = 'block';
  const form = document.getElementById('targets-form');
  form.innerHTML = `<table>
    <tr>
      <th>标的</th>
      <th>市值</th>
      <th>操作</th>
      <th>金额</th>
      <th>执行前持有</th>
      <th>其他策略持有</th>
      <th>标的维护</th>
    </tr>
    ${
      targets.map((t, i) => {
        const other = getOtherHold(s, t.name);
        const marketValue = stockMarketValueMap[t.name] || 0;
        return `
          <tr>
            <td>${t.name}</td>
            <td>${marketValue.toFixed(2)}</td>
            <td>
              <select id="target-action-${i}">
                <option value="">请选择</option>
                <option value="买">买入</option>
                <option value="卖">卖出</option>
              </select>
            </td>
            <td>
              <input type="number" id="target-value-${i}" class="input-short" min="0" placeholder="${t.default_amount}"/>
            </td>
            <td>
              <span id="hold-status-${i}" class="${t.hold ? 'hold-yes':'hold-no'}">${t.hold ? '持有':'未持有'}</span>
            </td>
            <td>
              ${other.length > 0 ? `<span class="hold-other">${other.join("、")}</span>` : '<span style="color:#aaa;">无</span>'}
            </td>
            <td>
              <button class="target-ops-btn" onclick="showEditTargetModal(${i})">修改</button>
              <button class="target-ops-btn danger" onclick="showDeleteTargetModal(${i})">删除</button>
            </td>
          </tr>
        `;
      }).join("")
    }
  </table>`;
  window.sorted_targets = targets;
}
function getOtherHold(currentStrategyName, targetName) {
  let result = [];
  Object.entries(strategies).forEach(([sname, arr]) => {
    if (sname === currentStrategyName) return;
    arr.forEach(t => {
      if (t.name === targetName && t.hold) result.push(sname);
    });
  });
  return result;
}
function addPlan() {
  const s = currentStrategy;
  if (!s) return;
  const targets = window.sorted_targets || strategies[s];
  let hasChange = false;
  targets.forEach((t, i) => {
    const action = document.getElementById(`target-action-${i}`).value;
    if (action) {
      hasChange = true;
      let value = document.getElementById(`target-value-${i}`).value.trim();
      value = value !== "" ? parseFloat(value) : t.default_amount;
      const originalIndex = strategies[s].findIndex(st => t.name === st.name);
      const holdBefore = t.hold;
      const otherHold = getOtherHold(s, t.name);
      plans.push({
        strategy: s,
        index: originalIndex,
        target: t.name,
        action,
        value,
        holdBefore,
        holdAfter: null,
        otherHold: [...otherHold]
      });
      document.getElementById(`target-action-${i}`).value = "";
      document.getElementById(`target-value-${i}`).value = "";
    }
  });
  if (!hasChange) {
    showToast('未选择任何标的变更！', '#e74c3c');
    return;
  }
  renderPlans();
}
function getHoldAfter(strategy, index, action) {
  if (action === "买") return true;
  if (action === "卖") return false;
  return strategies[strategy][index].hold;
}
function getOtherHoldAfter(currentStrategyName, targetName, thisPlan) {
  let result = [];
  Object.entries(strategies).forEach(([sname, arr]) => {
    if (sname === currentStrategyName) return;
    arr.forEach((t, idx) => {
      if (t.name === targetName) {
        const plan = plans.find(p => p.strategy === sname && p.target === targetName);
        let hold = t.hold;
        if (plan) {
          hold = getHoldAfter(plan.strategy, plan.index, plan.action);
        }
        if (hold) result.push(sname);
      }
    });
  });
  return result;
}
function renderPlans() {
  const tbody = document.getElementById('plans-table').querySelector('tbody');
  tbody.innerHTML = '';
  plans.forEach((p, idx) => {
    const holdAfter = getHoldAfter(p.strategy, p.index, p.action);
    plans[idx].holdAfter = holdAfter;
    const otherAfter = getOtherHoldAfter(p.strategy, p.target, p);
    // 执行占比
    let ratio = assetTotal ? (p.value / assetTotal * 100) : 0;
    let percentText = ratio.toFixed(2) + "%";
    // 持仓百分比
    let percentHold = stockPercentMap[p.target] || "0%";
    tbody.innerHTML += `
      <tr>
        <td>${p.strategy}</td>
        <td>${p.target}</td>
        <td>${p.action}</td>
        <td>${p.value}</td>
        <td>${percentText}</td>
        <td>${percentHold}</td>
        <td><span class="${p.holdBefore?'hold-yes':'hold-no'}">${p.holdBefore?'持有':'未持有'}</span></td>
        <td><span class="${holdAfter?'hold-yes':'hold-no'}">${holdAfter?'持有':'未持有'}</span></td>
        <td>
          ${otherAfter.length > 0 ? `<span class="hold-other">${otherAfter.join("、")}</span>` : '<span style="color:#aaa;">无</span>'}
        </td>
        <td><button onclick="deletePlan(${idx})">删除</button></td>
      </tr>
    `;
  });
}
window.deletePlan = function(idx) {
  plans.splice(idx, 1);
  renderPlans();
}

// 导出时展示当前总资产/现金/市值和执行后结果，再输出JSON
function exportPlan() {
  if (plans.length === 0) {
    showToast('没有计划可导出', '#e74c3c');
    return;
  }
  let sell_stocks_info = [];
  let buy_stocks_info = [];
  let sellSum = 0, buySum = 0;
  plans.forEach(p => {
    let ratio = assetTotal ? (p.value / assetTotal * 100) : 0;
    ratio = +ratio.toFixed(2);
    if (p.action === "买") {
      buy_stocks_info.push({
        name: p.target,
        ratio: ratio
      });
      buySum += Number(p.value);
    } else if (p.action === "卖") {
      sell_stocks_info.push({
        name: p.target,
        ratio: ratio
      });
      sellSum += Number(p.value);
    }
  });
  let cashNow = typeof cash === "number" ? cash : 0;
  let marketNow = typeof marketValue === "number" ? marketValue : 0;
  let totalNow = typeof assetTotal === "number" ? assetTotal : 0;
  let cashAfter = cashNow + sellSum - buySum;
  let marketAfter = marketNow - sellSum + buySum;
  let totalAfter = cashAfter + marketAfter;
  // 用span包裹并加id，便于高亮
  let summaryNow = `当前总资产：<span id="total-asset">${totalNow.toFixed(2)}</span>，可用资金：<span id="cash">${cashNow.toFixed(2)}</span>，持仓市值：<span id="position-value">${marketNow.toFixed(2)}</span>`;
  let summaryResult = `执行后可用资金：<span id="after-cash">${cashAfter.toFixed(2)}</span>，持仓市值：<span id="after-position-value">${marketAfter.toFixed(2)}</span>，总资产：<span id="after-total-asset">${totalAfter.toFixed(2)}</span>`;
  let exportBox = document.getElementById('export-box');
  exportBox.style.display = 'block';
  document.getElementById('export-summary-info').innerHTML = summaryNow;
  document.getElementById('export-summary-result').innerHTML = summaryResult;
  const out = JSON.stringify({
    sell_stocks_info,
    buy_stocks_info
  }, null, 2);
  document.getElementById('export-json').textContent = out;
  showToast('导出成功');
  highlightNegativeFunds();
}

// 高亮可用资金为负时的所有summary字段
function highlightNegativeFunds() {
  const afterCashElem = document.getElementById('after-cash');
  if (!afterCashElem) return;
  const afterCash = parseFloat(afterCashElem.textContent.replace(/,/g, ''));
  const ids = [
    'total-asset', 'cash', 'position-value',
    'after-cash', 'after-position-value', 'after-total-asset'
  ];
  if (afterCash < 0) {
    ids.forEach(id => {
      const elem = document.getElementById(id);
      if (elem) elem.style.color = 'red';
    });
  } else {
    ids.forEach(id => {
      const elem = document.getElementById(id);
      if (elem) elem.style.color = '';
    });
  }
}

function approvePlan() {
  if (plans.length === 0) {
    showToast('无计划可执行', '#e74c3c');
    return;
  }
  plans.forEach(p => {
    const arr = strategies[p.strategy];
    if (arr && arr[p.index]) {
      if (p.action === "买") arr[p.index].hold = true;
      if (p.action === "卖") arr[p.index].hold = false;
    }
  });
  saveStrategies();
  showToast('已根据计划执行持有状态更新！');
  loadStrategy();
  renderPlans();
}

function approvePlanAndCopy() {
  approvePlan();
  copyExportJson();
}

function copyExportJson() {
  const content = document.getElementById('export-json').textContent;
  if (!content) return;
  if (navigator.clipboard) {
    navigator.clipboard.writeText(content).then(
      () => { showToast("已复制到剪贴板！", "#67c23a"); },
      () => { fallbackCopyTextToClipboard(content); }
    );
  } else {
    fallbackCopyTextToClipboard(content);
  }
}
function fallbackCopyTextToClipboard(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  document.body.appendChild(textarea);
  textarea.select();
  try {
    document.execCommand('copy');
    showToast("已复制到剪贴板！", "#67c23a");
  } catch (err) {
    showToast("复制失败，请手动复制。", "#e74c3c");
  }
  document.body.removeChild(textarea);
}

// ================ 模态弹窗功能 ===================
function showSupplementModal() {
  let newStrategies = [];
  let newStocks = [];
  Object.entries(defaultStrategies).forEach(([sname, arr]) => {
    if (!strategies[sname]) {
      newStrategies.push(sname);
    } else {
      const existNames = strategies[sname].map(t => t.name);
      arr.forEach(newStock => {
        if (!existNames.includes(newStock.name)) {
          newStocks.push(`${sname} - ${newStock.name}`);
        }
      });
    }
  });
  let msg = "将会补充defaultStrategies中的所有新策略和新标的，已存在的不会被覆盖。是否继续？";
  if (newStrategies.length === 0 && newStocks.length === 0) {
    msg = "没有需要补充的新策略或新标的。";
  } else {
    if (newStrategies.length > 0) {
      msg += "<br><br><b>新增策略：</b><br>" + newStrategies.join("<br>");
    }
    if (newStocks.length > 0) {
      msg += "<br><br><b>新增标的：</b><br>" + newStocks.join("<br>");
    }
  }
  document.getElementById('supplement-modal-body').innerHTML = msg;
  document.getElementById('supplement-modal').style.display = 'block';
}
function hideSupplementModal() {
  document.getElementById('supplement-modal').style.display = 'none';
}
function doSupplementStrategies() {
  let changed = false;
  Object.entries(defaultStrategies).forEach(([sname, arr]) => {
    if (!strategies[sname]) {
      strategies[sname] = JSON.parse(JSON.stringify(arr));
      changed = true;
    } else {
      const existNames = strategies[sname].map(t => t.name);
      arr.forEach(newStock => {
        if (!existNames.includes(newStock.name)) {
          strategies[sname].push(JSON.parse(JSON.stringify(newStock)));
          changed = true;
        }
      });
    }
  });
  saveStrategies();
  renderStrategyOptions();
  if (strategySelect.value) loadStrategy();
  renderPlans();
  hideSupplementModal();
  if (changed) {
    showToast('已补充所有新策略和新标的！');
  } else {
    showToast('没有需要补充的新策略或新标的。', '#e74c3c');
  }
}
function showClearModal() {
  document.getElementById('clear-modal').style.display = 'block';
}
function hideClearModal() {
  document.getElementById('clear-modal').style.display = 'none';
}
function doClearLocalStorage() {
  Object.values(strategies).forEach(arr => {
    arr.forEach(item => item.hold = false);
  });
  plans = [];
  saveStrategies();
  renderStrategyOptions();
  loadStrategy();
  renderPlans();
  hideClearModal();
  showToast('已清空所有持有状态和变更计划，策略和标的已保留。');
}
function showDeleteStrategyModal() {
  const s = strategySelect.value;
  if (!s) {
    showToast('请先选择策略', '#e74c3c');
    return;
  }
  let msg = `确定要删除策略 <b>${s}</b> 吗？<br>该操作不可恢复，所有该策略下的标的和持有状态也将被删除。`;
  document.getElementById('delete-strategy-body').innerHTML = msg;
  document.getElementById('delete-strategy-modal').style.display = 'block';
}
function hideDeleteStrategyModal() {
  document.getElementById('delete-strategy-modal').style.display = 'none';
}
function doDeleteStrategy() {
  const s = strategySelect.value;
  if (!s) return;
  delete strategies[s];
  saveStrategies();
  plans = plans.filter(p => p.strategy !== s);
  renderStrategyOptions();
  strategySelect.value = "";
  loadStrategy();
  renderPlans();
  hideDeleteStrategyModal();
  showToast('策略已删除！');
}
function showAddStrategyModal() {
  document.getElementById('add-strategy-name').value = "";
  document.getElementById('add-strategy-modal').style.display = 'block';
}
function hideAddStrategyModal() {
  document.getElementById('add-strategy-modal').style.display = 'none';
}
function doAddStrategy() {
  const name = document.getElementById('add-strategy-name').value.trim();
  if (!name) {
    showToast("请输入策略名称", "#e74c3c");
    return;
  }
  if (strategies[name]) {
    showToast("策略已存在", "#e74c3c");
    return;
  }
  strategies[name] = [];
  saveStrategies();
  renderStrategyOptions();
  hideAddStrategyModal();
  strategySelect.value = name;
  loadStrategy();
  showToast("新增策略成功");
}

// ---------- 新增/编辑标的 ----------
function showAddTargetModal() {
  if (!strategySelect.value) {
    showToast("请先选择策略", "#e74c3c");
    return;
  }
  editingTargetIdx = null;
  document.getElementById('add-target-modal-title').textContent = "新增标的";
  document.getElementById('add-target-name').value = "";
  document.getElementById('add-target-amount').value = "";
  document.getElementById('add-target-confirm-btn').textContent = "新增";
  document.getElementById('add-target-confirm-btn').onclick = doAddTarget;
  document.getElementById('add-target-modal').style.display = 'block';
}
function showEditTargetModal(idx) {
  const s = strategySelect.value;
  if (!s) return;
  editingTargetIdx = idx;
  const t = strategies[s][idx];
  document.getElementById('add-target-modal-title').textContent = "修改标的";
  document.getElementById('add-target-name').value = t.name;
  document.getElementById('add-target-amount').value = t.default_amount;
  document.getElementById('add-target-confirm-btn').textContent = "保存";
  document.getElementById('add-target-confirm-btn').onclick = doEditTarget;
  document.getElementById('add-target-modal').style.display = 'block';
}
function hideAddTargetModal() {
  document.getElementById('add-target-modal').style.display = 'none';
}
function doAddTarget() {
  const strategy = strategySelect.value;
  const name = document.getElementById('add-target-name').value.trim();
  const amount = parseFloat(document.getElementById('add-target-amount').value.trim());
  if (!name) {
    showToast("请输入标的名称", "#e74c3c");
    return;
  }
  if (!amount || amount <= 0) {
    showToast("请输入有效的默认买入金额", "#e74c3c");
    return;
  }
  if (strategies[strategy].find(t => t.name === name)) {
    showToast("标的已存在", "#e74c3c");
    return;
  }
  strategies[strategy].push({name, default_amount: amount, hold: false});
  saveStrategies();
  loadStrategy();
  hideAddTargetModal();
  showToast("新增标的成功");
}
function doEditTarget() {
  const s = strategySelect.value;
  if (editingTargetIdx === null || !s) return;
  const arr = strategies[s];
  const name = document.getElementById('add-target-name').value.trim();
  const amount = parseFloat(document.getElementById('add-target-amount').value.trim());
  if (!name) {
    showToast("请输入标的名称", "#e74c3c");
    return;
  }
  if (!amount || amount <= 0) {
    showToast("请输入有效的默认买入金额", "#e74c3c");
    return;
  }
  if (arr.some((t, i) => t.name === name && i !== editingTargetIdx)) {
    showToast("标的名称已存在", "#e74c3c");
    return;
  }
  arr[editingTargetIdx].name = name;
  arr[editingTargetIdx].default_amount = amount;
  saveStrategies();
  loadStrategy();
  hideAddTargetModal();
  showToast("标的修改成功");
}

// ---------- 删除标的 ----------
let deletingTargetIdx = null;
function showDeleteTargetModal(idx) {
  const s = strategySelect.value;
  if (!s) return;
  deletingTargetIdx = idx;
  const t = strategies[s][idx];
  document.getElementById('delete-target-body').innerHTML = `确定要删除标的 <b>${t.name}</b> 吗？<br>该操作不可恢复。`;
  document.getElementById('delete-target-modal').style.display = 'block';
}
function hideDeleteTargetModal() {
  document.getElementById('delete-target-modal').style.display = 'none';
}
function doDeleteTarget() {
  const s = strategySelect.value;
  if (deletingTargetIdx === null || !s) return;
  strategies[s].splice(deletingTargetIdx, 1);
  saveStrategies();
  loadStrategy();
  hideDeleteTargetModal();
  showToast("标的已删除");
}

function toggleToolboxDropdown(e) {
  var dropdown = document.getElementById('toolbox-dropdown');
  dropdown.style.display = dropdown.style.display === 'flex' ? 'none' : 'flex';
  dropdown.style.flexDirection = 'column';
  document.addEventListener('mousedown', onToolboxOutsideClick, false);
}
function hideToolboxDropdown() {
  var dropdown = document.getElementById('toolbox-dropdown');
  dropdown.style.display = 'none';
  document.removeEventListener('mousedown', onToolboxOutsideClick, false);
}
function onToolboxOutsideClick(e) {
  var toolbox = document.getElementById('toolbox-btn');
  var dropdown = document.getElementById('toolbox-dropdown');
  if (!dropdown.contains(e.target) && !toolbox.contains(e.target)) {
    hideToolboxDropdown();
  }
}
function showChangeDefaultAmountModal() {
  const s = strategySelect.value;
  if (!s) {
    showToast('请先选择策略', '#e74c3c');
    return;
  }
  const arr = strategies[s];
  let html = "";
  if (!arr || arr.length === 0) {
    html = "<div>当前策略没有标的可以配置。</div>";
  } else {
    html = '<form id="change-default-amount-form">';
    arr.forEach((item, idx) => {
      html += `
        <div class="modal-input">
          <label style="display:inline-block;width:110px;">${item.name}：</label>
          <input type="number" min="1" style="width:120px;" id="change-default-amount-${idx}" value="${item.default_amount}"/>
        </div>
      `;
    });
    html += '</form>';
  }
  document.getElementById('change-default-amount-body').innerHTML = html;
  document.getElementById('change-default-amount-modal').style.display = 'block';
}
function hideChangeDefaultAmountModal() {
  document.getElementById('change-default-amount-modal').style.display = 'none';
}
function doChangeDefaultAmount() {
  const s = strategySelect.value;
  if (!s) return;
  const arr = strategies[s];
  let changed = false;
  arr.forEach((item, idx) => {
    const val = document.getElementById(`change-default-amount-${idx}`).value.trim();
    if (val !== "" && !isNaN(val) && Number(val) > 0) {
      const newVal = Number(val);
      if (item.default_amount !== newVal) {
        item.default_amount = newVal;
        changed = true;
      }
    }
  });
  saveStrategies();
  hideChangeDefaultAmountModal();
  loadStrategy();
  if (changed) {
    showToast('已更新所有标的默认金额！');
  } else {
    showToast('未做任何修改。', '#e74c3c');
  }
}

// =========== 定时自动刷新持仓 ===========
let refreshInterval = 60; // 秒
let remain = refreshInterval;
function updateRefreshTimer() {
  document.getElementById('refresh-timer').textContent = '自动刷新: ' + remain + 's';
}
function startAutoRefresh() {
  remain = refreshInterval;
  updateRefreshTimer();
  setInterval(() => {
    remain--;
    if (remain <= 0) {
      loadAccountInfo();
      remain = refreshInterval;
    }
    updateRefreshTimer();
  }, 1000);
}

// -- 入口，先加载股票代码映射 --
window.onload = async function() {
  await loadNameVsCode();
  loadAccountInfo();
  renderStrategyOptions();
  if (strategySelect.value) loadStrategy();
  renderPlans();
  startAutoRefresh();
}

// 辅助：格式化时间
function formatDateTime(dt) {
  if (!dt) return '';
  const date = new Date(dt);
  if (isNaN(date)) return dt;
  return date.getFullYear() + '-' +
    String(date.getMonth() + 1).padStart(2, '0') + '-' +
    String(date.getDate()).padStart(2, '0') + ' ' +
    String(date.getHours()).padStart(2, '0') + ':' +
    String(date.getMinutes()).padStart(2, '0') + ':' +
    String(date.getSeconds()).padStart(2, '0');
}