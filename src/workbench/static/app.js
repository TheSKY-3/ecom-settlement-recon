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
  diffs: { source: "gt", type: "", side: "", q: "", page: 1, pageSize: 50 },
  ledgers: { world: "clean", book: "platform_bills", q: "", page: 1, pageSize: 50 },
};

// 账本原始列名 → 中文表头（弹层与账本浏览共用；未收录的列原样显示）
const COL_ZH = {
  bill_id: "账单号", order_id: "订单号", seller_id: "卖家", version: "版本",
  issued_date: "出具日期", commission_rate: "佣金率", commission_fee: "佣金",
  freight_amount: "运费", price_amount: "货款", settlement_amount: "结算额",
  payment_sequential: "支付笔次", payment_type: "支付方式",
  payment_installments: "分期数", payment_value: "支付金额",
  refund_id: "退款号", refund_amount: "退款金额", refund_date: "退款日期",
  customer_id: "客户号", order_status: "订单状态",
  order_purchase_timestamp: "下单时间", order_approved_at: "支付审批时间",
  order_delivered_carrier_date: "交承运人时间", order_delivered_customer_date: "送达时间",
  order_estimated_delivery_date: "预计送达", order_item_id: "明细序号",
  product_id: "商品号", price: "单价", freight_value: "运费",
  shipping_limit_date: "发货截止",
};

// 枚举字段的值翻译（支付方式 / 订单状态）
const VAL_ZH = {
  payment_type: { credit_card: "信用卡", boleto: "线下缴费单", debit_card: "借记卡",
                  voucher: "代金券", not_defined: "未定义" },
  order_status: { created: "已创建", approved: "已支付审批", invoiced: "已开票",
                  processing: "备货中", shipped: "已发货", delivered: "已送达",
                  canceled: "已取消", unavailable: "无法配送" },
};

function zhCol(c) { return COL_ZH[c] || c; }
function zhVal(col, v) {
  const table = VAL_ZH[col];
  if (!table || v === null || v === undefined) return v;
  const s = String(v);
  return table[s] !== undefined ? `${table[s]}` : s;
}

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
  el.textContent = "加载失败：" + err.message + "（若数据未生成：造数跑 scripts/build_synthetic.py，引擎判定跑 scripts/run_engine.py）";
}

// ── 概览 ─────────────────────────────────────
async function renderOverview() {
  $("#overview-error").hidden = true;
  try {
    const [ov, eng, agent] = await Promise.all([
      fetchJSON("/api/overview"),
      fetchJSON("/api/engine").catch(() => ({ available: false })),
      fetchJSON("/api/agent/status").catch(() => ({ available: false })),
    ]);
    $("#seed-badge").textContent = `评测集批次 ${ov.seed}`;

    const kpis = [
      { label: "埋入的错误（考题总数）", value: fmt(ov.gt.total), foot: "六类差异，每条都有唯一归因", cls: "kpi--accent" },
      { label: "标准账本 · 平台账单", value: fmt(ov.clean.bills), foot: `退款 ${fmt(ov.clean.refunds)} · 支付 ${fmt(ov.clean.payments)}` },
      { label: "实际账本 · 平台账单", value: fmt(ov.dirty.bills), foot: `退款 ${fmt(ov.dirty.refunds)} · 支付 ${fmt(ov.dirty.payments)}` },
      eng.available
        ? { label: "确定性引擎（P2）", value: `${(eng.score.recall * 100).toFixed(1)}%`,
            foot: `检出 ${fmt(eng.score.tp)}/${fmt(eng.score.gt_total)} · 误报 ${fmt(eng.score.fp_other)} · 另报自然差异 ${fmt(eng.score.fp_natural)}`,
            cls: "kpi--accent" }
        : { label: "确定性引擎（P2）", value: "待接入", foot: "接入后此处展示引擎判定结果与得分", cls: "kpi--dim" },
    ];
    $("#kpi-grid").innerHTML = kpis.map((k, i) => `
      <div class="kpi ${k.cls || ""}" ${i === 1 || i === 2 ? `data-ledger="${i === 1 ? "clean" : "dirty"}" title="点击翻阅这本账"` : ""}>
        <div class="kpi__label">${k.label}</div>
        <div class="kpi__value">${k.value}</div>
        <div class="kpi__foot">${k.foot}</div>
      </div>`).join("");
    document.querySelectorAll("#kpi-grid .kpi[data-ledger]").forEach((el) => {
      el.addEventListener("click", () => {
        state.ledgers.world = el.dataset.ledger;
        state.ledgers.book = "platform_bills";
        state.ledgers.page = 1;
        location.hash = "#/ledgers";
      });
    });

    $("#ask-card").hidden = !agent.available;

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
        <div class="counts-head">三本账</div><div class="counts-head">标准账本</div><div class="counts-head">实际账本</div>
        ${rows.map(([k, c, d]) => `
          <div><div class="k">${k}</div></div>
          <div><div class="v">${fmt(c)}</div></div>
          <div><div class="v">${fmt(d)}</div></div>`).join("")}
      </div>`;
  } catch (err) {
    showError("#overview-error", err);
  }
}

// ── 标准答案列表（数据源可切换：标准答案 / 引擎判定）──
async function renderDiffs() {
  $("#diffs-error").hidden = true;
  const { source, type, side, q, page, pageSize } = state.diffs;
  const isEngine = source === "engine";
  const params = new URLSearchParams({ page, page_size: pageSize });
  if (type) params.set("type", type);
  if (side) params.set("side", side);
  if (q) params.set("q", q);

  $("#diffs-head").innerHTML = isEngine
    ? `<th>编号</th><th>订单号</th><th>类型</th><th>变体</th><th>所在账本</th><th>置信度</th><th>描述</th>`
    : `<th>编号</th><th>订单号</th><th>类型</th><th>变体</th><th>所在账本</th><th>描述</th>`;

  try {
    const body = await fetchJSON(
      (isEngine ? "/api/engine/findings" : "/api/diffs") + "?" + params);
    const tbody = $("#diffs-body");
    if (!body.rows.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty">没有符合筛选条件的记录</td></tr>`;
    } else {
      tbody.innerHTML = body.rows.map((r) => {
        const id = r.gt_id || r.finding_id;
        const conf = isEngine
          ? `<td class="num">${Math.round(r.confidence * 100)}%</td>` : "";
        return `
        <tr class="rowlink" data-gt="${r.gt_id || ""}" data-order="${r.order_id}"
            data-finding="${r.finding_id || ""}">
          <td class="mono">${id}</td>
          <td class="mono cell-id">${r.order_id}</td>
          <td>${badge(r.diff_type)}</td>
          <td>${r.variant}</td>
          <td>${sideDot(r.target_side)}</td>
          ${conf}
          <td class="cell-desc">${r.description}</td>
        </tr>`;
      }).join("");
      tbody.querySelectorAll("tr.rowlink").forEach((tr) => {
        tr.addEventListener("click", () =>
          openLedger(tr.dataset.gt || null, tr.dataset.order, tr.dataset.finding || null));
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
  $("#f-source").addEventListener("change", (e) => {
    state.diffs.source = e.target.value;
    resetDiffsAndRender();
  });
  $("#f-side").addEventListener("change", (e) => { state.diffs.side = e.target.value; resetDiffsAndRender(); });
  let timer = null;
  $("#f-q").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.diffs.q = e.target.value.trim(); resetDiffsAndRender(); }, 250);
  });
  $("#prev-page").addEventListener("click", () => { state.diffs.page -= 1; renderDiffs(); });
  $("#next-page").addEventListener("click", () => { state.diffs.page += 1; renderDiffs(); });
}

// ── 账本浏览（六本账通读）────────────────────────
async function renderLedgers() {
  $("#ledgers-error").hidden = true;
  const { world, book, q, page, pageSize } = state.ledgers;
  const params = new URLSearchParams({ page, page_size: pageSize });
  if (q) params.set("q", q);
  try {
    const body = await fetchJSON(`/api/rows/${world}/${book}?` + params);
    $("#ledgers-head").innerHTML =
      `<th>#</th>` + body.columns.map((c) => `<th>${zhCol(c)}</th>`).join("");
    const tbody = $("#ledgers-body");
    if (!body.rows.length) {
      tbody.innerHTML = `<tr><td class="empty">没有符合条件的记录</td></tr>`;
    } else {
      const start = (body.page - 1) * body.page_size;
      tbody.innerHTML = body.rows.map((r, i) => `
        <tr class="rowlink" data-order="${r.order_id || ""}">
          <td class="mono">${fmt(start + i + 1)}</td>
          ${body.columns.map((c) => {
            const raw = zhVal(c, r[c]);
            const v = raw === null || raw === undefined ? "" : String(raw);
            const cls = /^-?\d+(\.\d+)?$/.test(v) ? "num"
              : /^B_|^R_|^[0-9a-f]{16,}$/.test(v) ? "mono" : "";
            return `<td class="${cls}">${v}</td>`;
          }).join("")}
        </tr>`).join("");
      tbody.querySelectorAll("tr.rowlink").forEach((tr) => {
        if (tr.dataset.order) {
          tr.addEventListener("click", () => openLedger(null, tr.dataset.order, null));
        }
      });
    }
    const pages = Math.max(1, Math.ceil(body.total / body.page_size));
    $("#rows-info").textContent = `第 ${body.page} / ${pages} 页 · 共 ${fmt(body.total)} 行`;
    $("#rows-prev").disabled = body.page <= 1;
    $("#rows-next").disabled = body.page >= pages;
  } catch (err) {
    showError("#ledgers-error", err);
  }
}

function wireLedgersControls() {
  $("#f-ledger-world").addEventListener("change", (e) => {
    state.ledgers.world = e.target.value;
    state.ledgers.page = 1;
    renderLedgers();
  });
  $("#f-ledger-book").addEventListener("change", (e) => {
    state.ledgers.book = e.target.value;
    state.ledgers.page = 1;
    renderLedgers();
  });
  let timer = null;
  $("#f-ledger-q").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.ledgers.q = e.target.value.trim();
      state.ledgers.page = 1;
      renderLedgers();
    }, 250);
  });
  $("#rows-prev").addEventListener("click", () => { state.ledgers.page -= 1; renderLedgers(); });
  $("#rows-next").addEventListener("click", () => { state.ledgers.page += 1; renderLedgers(); });
}

// ── 单雷证据弹层 ─────────────────────────────
const LEDGER_GROUPS = [
  { title: "标准账本（这个订单应有的账）", secs: [
    { key: "clean_bills", label: "平台账单" },
    { key: "clean_payments", label: "支付流水" },
    { key: "clean_refunds", label: "退款流水" },
  ]},
  { title: "实际账本（平台实际给的账）", secs: [
    { key: "bills", label: "平台账单", side: "bills" },
    { key: "payments", label: "支付流水", side: "payments" },
    { key: "refunds", label: "退款流水", side: "refunds" },
  ]},
  { title: "原始记录（订单底单）", secs: [
    { key: "orders", label: "订单" },
    { key: "items", label: "订单明细" },
  ]},
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
    <thead><tr>${cols.map((c) => `<th>${zhCol(c)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) =>
      `<tr>${cols.map((c) => cell(zhVal(c, r[c]))).join("")}</tr>`).join("")}</tbody>
  </table></div>`;
}

function renderLedgerSection(sec, rows, gt) {
  let inner;
  if (rows.length) {
    inner = miniTable(rows);
  } else if (gt && sec.side && sec.side === gt.target_side) {
    inner = `<div class="ledger-empty ledger-empty--hit">该订单在此账本无任何记录 —— 这正是埋下错误的位置（${gt.variant}）。</div>`;
  } else {
    inner = `<div class="ledger-empty">无记录</div>`;
  }
  return `<div class="ledger-sec"><h3>${sec.label} · ${rows.length} 行</h3>${inner}</div>`;
}

function renderAgentAnswer(el, data) {
  const tag = data.source === "llm"
    ? `<span class="ai-tag ai-tag--llm">AI · 已过白名单校验</span>`
    : `<span class="ai-tag">确定性文案</span>`;
  el.innerHTML = `<div class="ask-answer__meta">${tag}</div>${data.answer}`
    + (data.refs.length ? `<div class="ask-answer__refs">引用：${data.refs.map((r) => `<span class="mono">${r}</span>`).join(" · ")}</div>` : "");
  el.hidden = false;
}

async function askAgent() {
  const input = $("#ask-input");
  const q = input.value.trim();
  if (!q) return;
  const box = $("#ask-answer");
  box.hidden = false;
  box.textContent = "思考中…";
  try {
    const res = await fetch("/api/agent/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || `${res.status}`);
    renderAgentAnswer(box, body);
  } catch (err) {
    box.textContent = "问答失败：" + err.message;
  }
}

let currentRef = null;

async function askLedgerAttribution() {
  if (!currentRef) return;
  const box = $("#ledger-ai-answer");
  box.hidden = false;
  box.textContent = "思考中…";
  try {
    renderAgentAnswer(box, await fetchJSON(`/api/agent/attribute/${currentRef}`));
  } catch (err) {
    box.textContent = "归因失败：" + err.message;
  }
}

async function openLedger(gtId, orderId, findingId) {
  currentRef = findingId || gtId || orderId;
  $("#ledger-ai").hidden = !currentRef;
  $("#ledger-ai-answer").hidden = true;
  const url = gtId ? `/api/diffs/${gtId}/ledger` : `/api/ledger/order/${orderId}`;
  let led;
  try {
    led = await fetchJSON(url);
  } catch (err) {
    alert("读取证据失败：" + err.message);
    return;
  }
  const label = led.gt ? `${led.gt.gt_id}　·　订单 ${led.gt.order_id}` : `订单 ${orderId}`;
  $("#ledger-gtid").textContent = label;
  $("#ledger-badge").innerHTML = led.gt ? badge(led.gt.diff_type) : "";
  $("#ledger-desc").textContent = led.gt
    ? `${led.gt.description}　·　所在账本：${SIDE_LABEL[led.gt.target_side] || led.gt.target_side}`
    : "该订单不在标准答案中 —— 引擎报出的这项差异属于数据自带的问题（自然差异）或待归因项。";
  $("#ledger-body").innerHTML = LEDGER_GROUPS
    .map((g) => `<div class="ledger-group"><h3 class="ledger-group__title">${g.title}</h3>`
      + g.secs.map((sec) => renderLedgerSection(sec, led[sec.key], led.gt)).join("")
      + `</div>`).join("");
  $("#ledger-modal").hidden = false;
  document.body.style.overflow = "hidden";
}

function closeLedger() {
  $("#ledger-modal").hidden = true;
  document.body.style.overflow = "";
}

// ── 路由 ─────────────────────────────────────
const RENDERERS = { overview: renderOverview, diffs: renderDiffs, ledgers: renderLedgers, about: () => {} };

function route() {
  const name = (location.hash.replace(/^#\//, "") || "overview").split("?")[0];
  const valid = RENDERERS[name] ? name : "overview";
  for (const [key, el] of Object.entries({
    overview: $("#view-overview"), diffs: $("#view-diffs"),
    ledgers: $("#view-ledgers"), about: $("#view-about"),
  })) {
    el.hidden = key !== valid;
  }
  document.querySelectorAll("#tabs a").forEach((a) => {
    a.classList.toggle("active", a.dataset.tab === valid);
  });
  RENDERERS[valid]();
}

wireDiffsControls();
wireLedgersControls();
$("#ask-btn").addEventListener("click", askAgent);
$("#ask-input").addEventListener("keydown", (e) => { if (e.key === "Enter") askAgent(); });
$("#ledger-ai-btn").addEventListener("click", askLedgerAttribution);
document.querySelectorAll("#ledger-modal [data-close]").forEach((el) => {
  el.addEventListener("click", closeLedger);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLedger(); });
window.addEventListener("hashchange", route);
route();
