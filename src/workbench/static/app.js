/* 对账工作台前端逻辑：hash 路由 + 三个视图渲染 + 单雷证据弹层。
   只读：一切数字来自 /api/*，页面本身不算账。 */
"use strict";

const $ = (sel) => document.querySelector(sel);

const TYPE_SLUG = {
  "单边账": "single",
  "金额不符": "amount",
  "状态不一致": "status",
  "退款遗漏": "refund",
  "重复结算": "duplicate",
  "版本差异": "version",
};

const SIDE_LABEL = { bills: "账单", payments: "支付", refunds: "退款" };

// 每类差异的一句话解释（概览条形下方的悬停提示）
const TYPE_HINT = {
  "单边账": "一本账有、另一本账没有：删账单 / 无主账单 / 删支付",
  "金额不符": "金额算错：佣金费率用错 / 漏加运费",
  "状态不一致": "已取消的订单仍被平台开账单收费",
  "退款遗漏": "该退的钱没退：取消单已付款但无退款记录",
  "重复结算": "同一笔账出现两次",
  "版本差异": "新旧两版账单并存，须以新版为准",
};

const state = {
  diffs: { type: "", side: "", q: "", page: 1, pageSize: 50 },
};

async function fetchJSON(url) {
  const res = await fetch(url);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return body;
}

const fmt = (n) => Number(n).toLocaleString("zh-CN");

function badge(type) {
  const slug = TYPE_SLUG[type] || "unknown";
  return `<span class="badge badge--${slug}">${type}</span>`;
}

function sideDot(side) {
  return `<span class="side-dot side-dot--${side}">${SIDE_LABEL[side] || side}</span>`;
}

function showError(sel, err) {
  const el = $(sel);
  el.hidden = false;
  el.textContent = "加载失败：" + err.message + "（若是数据文件缺失，请先跑 scripts/build_synthetic.py）";
}

// ── 概览 ─────────────────────────────────────
async function renderOverview() {
  $("#overview-error").hidden = true;
  try {
    const ov = await fetchJSON("/api/overview");
    $("#seed-badge").textContent = `种子 ${ov.seed}`;

    const kpis = [
      { label: "标准答案（考题总数）", value: fmt(ov.gt.total), foot: "六类差异，每颗雷都有唯一归因", cls: "kpi--accent" },
      { label: "干净世界 · 平台账单", value: fmt(ov.clean.bills), foot: `退款 ${fmt(ov.clean.refunds)} · 支付 ${fmt(ov.clean.payments)}` },
      { label: "脏世界 · 平台账单", value: fmt(ov.dirty.bills), foot: `退款 ${fmt(ov.dirty.refunds)} · 支付 ${fmt(ov.dirty.payments)}` },
      { label: "确定性引擎（P2）", value: "待接入", foot: "接入后此处展示引擎判定结果与得分", cls: "kpi--dim" },
    ];
    $("#kpi-grid").innerHTML = kpis.map((k) => `
      <div class="kpi ${k.cls || ""}">
        <div class="kpi__label">${k.label}</div>
        <div class="kpi__value">${k.value}</div>
        <div class="kpi__foot">${k.foot}</div>
      </div>`).join("");

    const entries = Object.entries(ov.gt.by_type).sort((a, b) => b[1] - a[1]);
    const max = Math.max(...entries.map(([, n]) => n));
    $("#type-bars").innerHTML = entries.map(([type, n]) => `
      <div class="bar-row" data-type="${type}" title="${TYPE_HINT[type] || ""}">
        <span class="bar-row__label">${type}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${(n / max * 100).toFixed(1)}%"></span></span>
        <span class="bar-row__value">${fmt(n)} 条</span>
      </div>`).join("");
    document.querySelectorAll("#type-bars .bar-row").forEach((row) => {
      row.addEventListener("click", () => {
        state.diffs.type = row.dataset.type;
        state.diffs.page = 1;
        location.hash = "#/diffs";
      });
    });

    const rows = [
      ["平台账单", ov.clean.bills, ov.dirty.bills],
      ["退款流水", ov.clean.refunds, ov.dirty.refunds],
      ["支付流水", ov.clean.payments, ov.dirty.payments],
    ];
    $("#ledger-counts").innerHTML = `
      <div class="counts-grid">
        <div class="counts-head">三本账</div><div class="counts-head">干净世界</div><div class="counts-head">脏世界</div>
        ${rows.map(([k, c, d]) => `
          <div><div class="k">${k}</div></div>
          <div><div class="v">${fmt(c)}</div></div>
          <div><div class="v">${fmt(d)}</div></div>`).join("")}
      </div>`;
  } catch (err) {
    showError("#overview-error", err);
  }
}

// ── 标准答案列表 ─────────────────────────────
async function renderDiffs() {
  $("#diffs-error").hidden = true;
  const { type, side, q, page, pageSize } = state.diffs;
  const params = new URLSearchParams({ page, page_size: pageSize });
  if (type) params.set("type", type);
  if (side) params.set("side", side);
  if (q) params.set("q", q);

  try {
    const body = await fetchJSON("/api/diffs?" + params);
    const tbody = $("#diffs-body");
    if (!body.rows.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty">没有符合筛选条件的记录</td></tr>`;
    } else {
      tbody.innerHTML = body.rows.map((r) => `
        <tr class="rowlink" data-gt="${r.gt_id}">
          <td class="mono">${r.gt_id}</td>
          <td class="mono cell-id">${r.order_id}</td>
          <td>${badge(r.diff_type)}</td>
          <td>${r.variant}</td>
          <td>${sideDot(r.target_side)}</td>
          <td class="cell-desc">${r.description}</td>
        </tr>`).join("");
      tbody.querySelectorAll("tr.rowlink").forEach((tr) => {
        tr.addEventListener("click", () => openLedger(tr.dataset.gt));
      });
    }

    const pages = Math.max(1, Math.ceil(body.total / body.page_size));
    $("#page-info").textContent = `第 ${body.page} / ${pages} 页 · 共 ${fmt(body.total)} 条`;
    $("#prev-page").disabled = body.page <= 1;
    $("#next-page").disabled = body.page >= pages;
  } catch (err) {
    showError("#diffs-error", err);
  }
}

function resetDiffsAndRender() {
  state.diffs.page = 1;
  renderDiffs();
}

function wireDiffsControls() {
  const typeSel = $("#f-type");
  Object.keys(TYPE_SLUG).forEach((t) => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    typeSel.appendChild(opt);
  });
  typeSel.addEventListener("change", () => { state.diffs.type = typeSel.value; resetDiffsAndRender(); });
  $("#f-side").addEventListener("change", (e) => { state.diffs.side = e.target.value; resetDiffsAndRender(); });
  let timer = null;
  $("#f-q").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.diffs.q = e.target.value.trim(); resetDiffsAndRender(); }, 250);
  });
  $("#prev-page").addEventListener("click", () => { state.diffs.page -= 1; renderDiffs(); });
  $("#next-page").addEventListener("click", () => { state.diffs.page += 1; renderDiffs(); });
}

// ── 单雷证据弹层 ─────────────────────────────
const LEDGER_SECTIONS = [
  { key: "bills", label: "平台账单（脏）", side: "bills" },
  { key: "payments", label: "支付流水（脏）", side: "payments" },
  { key: "refunds", label: "退款流水（脏）", side: "refunds" },
  { key: "orders", label: "订单（底座）" },
  { key: "items", label: "订单明细（底座）" },
];

function miniTable(rows) {
  const cols = Object.keys(rows[0]);
  const cell = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    const numeric = /^-?\d+(\.\d+)?$/.test(s);
    const cls = numeric ? "num" : /^B_|^R_|^[0-9a-f]{16,}$/.test(s) ? "mono" : "";
    return `<td class="${cls}">${s}</td>`;
  };
  return `<div class="table-wrap"><table class="table">
    <thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${cols.map((c) => cell(r[c])).join("")}</tr>`).join("")}</tbody>
  </table></div>`;
}

function renderLedgerSection(sec, rows, gt) {
  let inner;
  if (rows.length) {
    inner = miniTable(rows);
  } else if (sec.side && sec.side === gt.target_side) {
    inner = `<div class="ledger-empty ledger-empty--hit">该订单在此账本无任何记录 —— 这正是这颗雷的位置（${gt.variant}）。</div>`;
  } else {
    inner = `<div class="ledger-empty">无记录</div>`;
  }
  return `<div class="ledger-sec"><h3>${sec.label} · ${rows.length} 行</h3>${inner}</div>`;
}

async function openLedger(gtId) {
  let led;
  try {
    led = await fetchJSON(`/api/diffs/${gtId}/ledger`);
  } catch (err) {
    alert("读取证据失败：" + err.message);
    return;
  }
  $("#ledger-gtid").textContent = led.gt.gt_id;
  $("#ledger-badge").innerHTML = badge(led.gt.diff_type);
  $("#ledger-desc").textContent = `${led.gt.description}　·　订单 ${led.gt.order_id}　·　目标侧：${SIDE_LABEL[led.gt.target_side] || led.gt.target_side}`;
  $("#ledger-body").innerHTML = LEDGER_SECTIONS
    .map((sec) => renderLedgerSection(sec, led[sec.key], led.gt)).join("");
  $("#ledger-modal").hidden = false;
  document.body.style.overflow = "hidden";
}

function closeLedger() {
  $("#ledger-modal").hidden = true;
  document.body.style.overflow = "";
}

// ── 路由 ─────────────────────────────────────
const RENDERERS = { overview: renderOverview, diffs: renderDiffs, about: () => {} };

function route() {
  const name = (location.hash.replace(/^#\//, "") || "overview").split("?")[0];
  const valid = RENDERERS[name] ? name : "overview";
  for (const [key, el] of Object.entries({
    overview: $("#view-overview"), diffs: $("#view-diffs"), about: $("#view-about"),
  })) {
    el.hidden = key !== valid;
  }
  document.querySelectorAll("#tabs a").forEach((a) => {
    a.classList.toggle("active", a.dataset.tab === valid);
  });
  RENDERERS[valid]();
}

wireDiffsControls();
document.querySelectorAll("#ledger-modal [data-close]").forEach((el) => {
  el.addEventListener("click", closeLedger);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLedger(); });
window.addEventListener("hashchange", route);
route();
