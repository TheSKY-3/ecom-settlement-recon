/* 对账工作台前端逻辑：对话优先 + 数据页（概览/差异/账本）+ 数据源条 + 导出。
   只读：一切数字来自 /api/*，页面本身不算账；导出文件由后端确定性生成。 */
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
  dataView: "diffs",
  tables: null,
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

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
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

// ── 概览（数据页顶部）─────────────────────────
async function renderOverview() {
  $("#data-error").hidden = true;
  try {
    const [ov, eng] = await Promise.all([
      fetchJSON("/api/overview"),
      fetchJSON("/api/engine").catch(() => ({ available: false })),
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
        switchDataView("ledgers");
        location.hash = "#/data";
      });
    });

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
        syncDiffsControls();
        switchDataView("diffs");
        location.hash = "#/data";
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
    showError("#data-error", err);
  }
}

// ── 数据页：概览 / 差异 / 账本 一张页里切换 ──────────
function syncDiffsControls() {
  const map = { "#f-source": state.diffs.source, "#f-type": state.diffs.type,
                "#f-side": state.diffs.side, "#f-q": state.diffs.q };
  for (const [sel, value] of Object.entries(map)) {
    const el = $(sel);
    if (el && el.value !== value) el.value = value;
  }
}

function switchDataView(name) {
  state.dataView = name === "ledgers" ? "ledgers" : "diffs";
  const isLedgers = state.dataView === "ledgers";
  $("#panel-diffs").hidden = isLedgers;
  $("#panel-ledgers").hidden = !isLedgers;
  $("#seg-diffs").classList.toggle("is-active", !isLedgers);
  $("#seg-ledgers").classList.toggle("is-active", isLedgers);
  $("#seg-diffs").setAttribute("aria-selected", String(!isLedgers));
  $("#seg-ledgers").setAttribute("aria-selected", String(isLedgers));
  $("#export-btn").hidden = isLedgers;
  $("#export-note").hidden = true;
  if (isLedgers) renderLedgers(); else renderDiffs();
}

function wireDataSeg() {
  $("#seg-diffs").addEventListener("click", () => switchDataView("diffs"));
  $("#seg-ledgers").addEventListener("click", () => switchDataView("ledgers"));
  $("#export-btn").addEventListener("click", exportCurrent);
}

async function renderData() {
  switchDataView(state.dataView);
  await renderOverview();
}

function exportFilters() {
  const f = { source: state.diffs.source || "gt" };
  if (state.diffs.type) f.diff_type = state.diffs.type;
  if (state.diffs.side) f.side = state.diffs.side;
  if (state.diffs.q) f.q = state.diffs.q;
  return f;
}

async function exportCurrent() {
  const btn = $("#export-btn");
  const note = $("#export-note");
  if (btn.disabled) return;
  btn.disabled = true;
  btn.textContent = "生成中…";
  note.hidden = false;
  note.className = "export-note";
  note.textContent = "正在生成 Excel（对照明细 + 订单汇总）…";
  try {
    const res = await fetch("/api/exports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(exportFilters()),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `导出失败（${res.status}）`);
    note.className = "export-note export-note--ok";
    note.replaceChildren();
    note.append(document.createTextNode(
      `已生成 ${fmt(body.rows)} 行 · ${fmt(body.orders)} 个订单 · `));
    const link = makeEl("a", "export-link", `下载 ${body.file}`);
    link.href = body.url;
    link.download = body.file || "对账对照.xlsx";
    note.append(link);
    note.append(makeEl("span", "export-note__ttl", "（30 分钟内有效）"));
  } catch (err) {
    note.className = "export-note export-note--bad";
    note.textContent = "导出失败：" + err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "导出当前结果";
  }
}

// ── 数据源条 + 全部表弹层 ─────────────────────
const DS_BOOK = { dirty_bills: "platform_bills", dirty_payments: "order_payments",
                  dirty_refunds: "refunds" };

function openTablesModal() {
  $("#tables-modal").hidden = false;
  document.body.style.overflow = "hidden";
}

function closeTablesModal() {
  $("#tables-modal").hidden = true;
  document.body.style.overflow = "";
}

function gotoData() {
  if (location.hash === "#/data") {
    renderData();
  } else {
    location.hash = "#/data";
  }
}

function openTableEntry(table) {
  if (table.role === "输入" && DS_BOOK[table.key]) {
    state.ledgers.world = "dirty";
    state.ledgers.book = DS_BOOK[table.key];
    state.ledgers.page = 1;
    switchDataView("ledgers");
    gotoData();
    return;
  }
  if (table.role === "标准答案") {
    state.diffs.source = "gt";
    state.diffs.page = 1;
    syncDiffsControls();
    switchDataView("diffs");
    gotoData();
    return;
  }
  if (table.role === "产出") {
    state.diffs.source = "engine";
    state.diffs.page = 1;
    syncDiffsControls();
    switchDataView("diffs");
    gotoData();
    return;
  }
  openTablesModal();
}

function renderDatasource(data) {
  const chips = $("#datasource-chips");
  chips.replaceChildren();
  const input = data.tables.filter((t) => t.role === "输入");
  const refs = data.tables.filter((t) => t.role === "参照");
  const gt = data.tables.filter((t) => t.role === "标准答案");
  const found = data.tables.filter((t) => t.role === "产出");
  for (const table of input) {
    const chip = makeEl("button", "ds-chip", table.label);
    chip.type = "button";
    chip.title = `输入 · ${fmt(table.rows)} 行 · ${table.columns.length} 列 · 点击去查`;
    chip.append(makeEl("span", "ds-chip__rows", fmt(table.rows)));
    chip.addEventListener("click", () => openTableEntry(table));
    chips.append(chip);
  }
  if (refs.length) {
    const chip = makeEl("button", "ds-chip ds-chip--group", `干净参照 ${refs.length} 份`);
    chip.type = "button";
    chip.title = "干净参照表：只用于对照，不参与对账";
    chip.addEventListener("click", openTablesModal);
    chips.append(chip);
  }
  for (const table of [...gt, ...found]) {
    const chip = makeEl("button", "ds-chip", table.label);
    chip.type = "button";
    chip.title = `${table.role} · ${fmt(table.rows)} 行 · 点击去查`;
    chip.append(makeEl("span", "ds-chip__rows", fmt(table.rows)));
    chip.addEventListener("click", () => openTableEntry(table));
    chips.append(chip);
  }
  $("#seed-badge").textContent = `评测集批次 ${data.seed}`;
  $("#tables-badge").textContent = data.engine_available
    ? `评测集批次 ${data.seed} · 引擎 ${data.engine_run_id || "已运行"}`
    : `评测集批次 ${data.seed} · 引擎未运行`;
  renderTablesModal(data);
}

function renderTablesModal(data) {
  const body = $("#tables-body");
  body.replaceChildren();
  const head = makeEl("div", "tables-row tables-row--head");
  for (const h of ["表", "角色", "行数", "列", ""]) head.append(makeEl("span", "", h));
  body.append(head);
  for (const table of data.tables) {
    const row = makeEl("div", "tables-row");
    row.append(makeEl("span", "tables-row__name", table.label));
    row.append(makeEl("span", "tables-row__role", table.role));
    row.append(makeEl("span", "num", fmt(table.rows)));
    row.append(makeEl("span", "tables-row__cols",
      `${table.columns.length} 列`));
    const btn = makeEl("button", "btn btn--ghost tables-row__go", "浏览");
    btn.type = "button";
    btn.addEventListener("click", () => {
      closeTablesModal();
      openTableEntry(table);
    });
    row.append(btn);
    body.append(row);
    row.title = table.columns.map(zhCol).join("、");
  }
}

async function loadDatasource() {
  try {
    const data = await fetchJSON("/api/tables");
    state.tables = data;
    renderDatasource(data);
  } catch (err) {
    const chips = $("#datasource-chips");
    chips.replaceChildren(makeEl("span", "datasource__loading",
      "表清单读取失败：" + err.message));
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
  $("#export-note").hidden = true;
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

let currentRef = null;
const aiAnswerCache = {};   // ref -> 已取得的归因回答，收起再展开不重复请求

async function askLedgerAttribution() {
  if (!currentRef) return;
  const box = $("#ledger-ai-answer");
  if (!box.hidden) {                     // 已展开 → 再点收起，把空间还给表格
    box.hidden = true;
    $("#ledger-ai-btn").textContent = "AI 归因解释";
    return;
  }
  box.hidden = false;
  const cached = aiAnswerCache[currentRef];
  if (cached) {
    renderAgentAnswer(box, cached);
    $("#ledger-ai-btn").textContent = "收起 AI 解释";
    return;
  }
  box.textContent = "思考中…";
  $("#ledger-ai-btn").textContent = "收起 AI 解释";
  try {
    const ans = await fetchJSON(`/api/agent/attribute/${currentRef}`);
    aiAnswerCache[currentRef] = ans;
    renderAgentAnswer(box, ans);
  } catch (err) {
    box.textContent = "归因失败：" + err.message;
    $("#ledger-ai-btn").textContent = "AI 归因解释";
  }
}

async function openLedger(gtId, orderId, findingId) {
  currentRef = findingId || gtId || orderId;
  $("#ledger-ai").hidden = !currentRef;
  $("#ledger-ai-answer").hidden = true;
  $("#ledger-ai-btn").textContent = "AI 归因解释";
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
  $("#ledger-body").innerHTML = LEDGER_GROUPS.map((group) => {
    const isOriginal = group.secs.some((sec) => sec.key === "orders");
    if (isOriginal && led.original_available === false) {
      return `<div class="ledger-group"><h3 class="ledger-group__title">${group.title}</h3>`
        + `<div class="ledger-empty">原始订单库未加载（data/olist.db 不在当前运行环境里，Docker 镜像默认不带）。`
        + `账本对照不受影响；要看订单底单与明细，请在本机构建底座库后挂载到 /app/data/olist.db（见 README）。</div></div>`;
    }
    return `<div class="ledger-group"><h3 class="ledger-group__title">${group.title}</h3>`
      + group.secs.map((sec) => renderLedgerSection(sec, led[sec.key], led.gt)).join("")
      + `</div>`;
  }).join("");
  $("#ledger-modal").hidden = false;
  document.body.style.overflow = "hidden";
}

function closeLedger() {
  $("#ledger-modal").hidden = true;
  document.body.style.overflow = "";
}

// ── 多轮对账对话（D013/D016）────────────────────
const CHAT_SESSION_KEY = "recon.chat.session";
const CHAT_FALLBACK_PRESETS = [
  "这批一共多少条差异？",
  "这批评测涉及几张表，各有多少行？",
  "六类差异分别有多少条？",
  "把单边账导成 Excel 对照表。",
];
const CHAT_REASON_LABEL = {
  NO_KEY: "未配置模型密钥",
  VALIDATION_FAILED: "模型答案未通过白名单校验",
  LLM_ERROR: "模型调用失败",
  INTERNAL_ERROR: "内部错误",
  MODEL_OUTPUT_INVALID: "模型输出格式不正确",
  BAD_ANSWER_SCHEMA: "答案结构不合法",
  ROUNDS_EXCEEDED: "工具轮数超限",
  SESSION_LIMIT: "会话轮数上限",
};

let chatRestoreToken = 0;

const chatState = {
  sessionId: null,
  messages: [],
  turns: 0,
  maxTurns: 20,
  available: false,
  statusLoaded: false,
  statusError: null,
  loading: false,
  limitReached: false,
  presets: CHAT_FALLBACK_PRESETS.slice(),
  activityId: null,
  activitySteps: [],
  activityTimer: null,
  activityPollingId: null,
  model: null,
};

function safeStorageGet(key) {
  try { return sessionStorage.getItem(key); } catch { return null; }
}
function safeStorageSet(key, value) {
  try { sessionStorage.setItem(key, value); } catch { /* 隐私模式忽略 */ }
}
function safeStorageRemove(key) {
  try { sessionStorage.removeItem(key); } catch { /* 忽略 */ }
}

function makeEl(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
}

function scrollChat() {
  const log = $("#chat-log");
  if (!log) return;
  const jump = () => { log.scrollTop = log.scrollHeight; };
  // 立即滚一次 + 定时补一次：后台窗口会暂停 rAF，不能只依赖动画帧
  jump();
  requestAnimationFrame(jump);
  setTimeout(jump, 80);
}

function updateChatNotice() {
  const el = $("#chat-notice");
  if (!el) return;
  if (chatState.limitReached) {
    el.hidden = false;
    el.textContent = `本会话已达 ${chatState.maxTurns} 轮上限。点“新对话”重新开始，已有历史仍保留在服务端直至过期。`;
    return;
  }
  if (chatState.statusError) {
    el.hidden = false;
    el.textContent = "对话状态读取失败：" + chatState.statusError + "。仍可尝试发送，失败会原样提示。";
    return;
  }
  if (!chatState.statusLoaded) { el.hidden = true; return; }
  if (!chatState.available) {
    el.hidden = false;
    el.textContent = "未配置模型 key：点右上角「模型」粘贴 DeepSeek key 即可启用 AI 对话；当前用确定性路由回答，统计、样例、订单仍可查，自由追问会受限。";
    return;
  }
  el.hidden = true;
  el.textContent = "";
}

function updateChatChrome() {
  const turns = $("#chat-turns");
  const shownTurns = chatState.loading
    ? Math.min(chatState.turns + 1, chatState.maxTurns) : chatState.turns;
  if (turns) turns.textContent = `${shownTurns} / ${chatState.maxTurns} 轮`;
  const send = $("#chat-send");
  if (send) send.disabled = chatState.loading || chatState.limitReached;
  const input = $("#chat-input");
  if (input) input.disabled = chatState.limitReached;
  const fresh = $("#chat-new");
  if (fresh) fresh.disabled = chatState.loading;
}

function buildChatEmpty() {
  const wrap = makeEl("div", "chat-empty");
  wrap.append(makeEl("div", "chat-empty__icon", "◐"));
  wrap.append(makeEl("h3", "", "先问一句，再决定要不要翻表"));
  wrap.append(makeEl("p", "",
    "能查：整批统计、六类差异、表清单与行数、GT/F 编号、32 位订单号；"));
  wrap.append(makeEl("p", "", "要文件就说“把单边账导成 Excel 对照表”，导完直接下载。"));
  wrap.append(makeEl("p", "chat-empty__note",
    "回答里的数字先过白名单校验；查不到会直说，不编造。没配模型密钥也能查清单和导出。"));
  return wrap;
}

function openChatRef(ref) {
  if (/^GT\d+$/.test(ref)) {
    openLedger(ref, null, null);
  } else if (/^[0-9a-f]{32}$/i.test(ref)) {
    openLedger(null, ref, null);
  }
}

function buildChatRefs(refs) {
  const wrap = makeEl("div", "chat-refs");
  wrap.append(makeEl("span", "chat-refs__label", "引用"));
  for (const ref of refs) {
    const clickable = /^GT\d+$/.test(ref) || /^[0-9a-f]{32}$/i.test(ref);
    const node = makeEl(clickable ? "button" : "span",
      "chat-ref" + (clickable ? "" : " chat-ref--plain"), ref);
    if (clickable) {
      node.type = "button";
      node.title = "打开账本证据";
      node.addEventListener("click", () => openChatRef(ref));
    } else {
      node.title = "引擎发现编号；可在差异明细里按关键词搜索";
    }
    wrap.append(node);
  }
  return wrap;
}

const CHAT_ARG_LABELS = {
  source: "来源", diff_type: "类型", side: "账本", q: "关键词",
  ref: "编号", order_id: "订单", limit: "条数",
  natural_only: "仅自然差异", min_confidence: "置信度≥", verified: "已核验",
};
const CHAT_ARG_VALUES = {
  source: { gt: "标准答案", engine: "引擎结果", both: "两者对照" },
  side: { bills: "账单", payments: "支付", refunds: "退款" },
};

function formatChatStepArgs(args) {
  if (!args || typeof args !== "object") return "";
  const parts = [];
  for (const key of ["source", "diff_type", "side", "q", "ref", "order_id",
                     "limit", "natural_only", "min_confidence", "verified"]) {
    if (!(key in args) || args[key] === "") continue;
    const raw = typeof args[key] === "boolean"
      ? (args[key] ? "是" : "否") : String(args[key]);
    const value = (CHAT_ARG_VALUES[key] || {})[raw] || raw;
    parts.push((CHAT_ARG_LABELS[key] || key) + " " + value);
  }
  return parts.join(" · ");
}

function buildChatArtifacts(list) {
  const wrap = makeEl("div", "chat-artifacts");
  for (const a of list) {
    if (!a || !a.url) continue;
    const card = makeEl("div", "chat-artifact");
    card.append(makeEl("span", "chat-artifact__ext",
      String(a.format || "xlsx").toUpperCase()));
    const info = makeEl("div", "chat-artifact__info");
    info.append(makeEl("div", "chat-artifact__name", a.file || "对账对照表.xlsx"));
    const meta = [];
    if (Array.isArray(a.sheets) && a.sheets.length) {
      meta.push(`${a.sheets.length} 个工作表`);
    }
    if (a.rows !== undefined) meta.push(`${fmt(a.rows)} 行`);
    if (a.orders !== undefined) meta.push(`${fmt(a.orders)} 个订单`);
    if (meta.length) info.append(makeEl("div", "chat-artifact__meta", meta.join(" · ")));
    if (a.filters_text) {
      info.append(makeEl("div", "chat-artifact__filters", "筛选：" + a.filters_text));
    }
    card.append(info);
    const link = makeEl("a", "btn btn--primary chat-artifact__dl", "下载");
    link.href = a.url;
    link.download = a.file || "对账对照.xlsx";
    link.title = "30 分钟内有效；由后端确定性生成";
    card.append(link);
    wrap.append(card);
  }
  return wrap;
}

function askPreset(text) {
  if (chatState.loading || chatState.limitReached) return;
  const input = $("#chat-input");
  input.value = text;
  resizeChatInput();
  sendChat();
}

function buildChatSuggest(list) {
  const row = makeEl("div", "chat-suggest__row");
  row.append(makeEl("span", "chat-suggest__label", "下一步"));
  for (const item of list) {
    if (!item || !item.text) continue;
    const chip = makeEl("button", "chat-suggest__chip", item.text);
    chip.type = "button";
    chip.addEventListener("click", () => askPreset(item.text));
    row.append(chip);
  }
  return row;
}

function renderChatSuggest() {
  const wrap = $("#chat-suggest");
  if (!wrap) return;
  wrap.replaceChildren();
  const last = [...chatState.messages].reverse()
    .find((m) => m.role === "assistant" && !m.error);
  const list = last && Array.isArray(last.suggestions) ? last.suggestions : [];
  if (chatState.loading || chatState.limitReached || !list.length) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  wrap.append(buildChatSuggest(list));
}

function buildChatSteps(steps, live) {
  const wrap = makeEl("details", "chat-steps" + (live ? " chat-steps--live" : ""));
  // 执行中展开看进度；答完收起，正文和下一句建议才是主角
  wrap.open = Boolean(live);
  const summary = makeEl("summary", "chat-steps__summary");
  summary.append(makeEl("span", "chat-steps__title", "执行过程"));
  summary.append(makeEl("span", "chat-steps__count", steps.length + " 步"));
  if (live) summary.append(makeEl("span", "chat-steps__live", "进行中"));
  wrap.append(summary);
  const list = makeEl("ol", "chat-steps__list");
  steps.forEach((step, i) => {
    const status = ["running", "ok", "error"].includes(step.status)
      ? step.status : "ok";
    const item = makeEl("li", "chat-step chat-step--" + status);
    item.append(makeEl("span", "chat-step__index", String(step.index || i + 1)));
    const main = makeEl("div", "chat-step__main");
    const head = makeEl("div", "chat-step__head");
    head.append(makeEl("span", "chat-step__label", step.label || step.name || "工具"));
    if (step.kind === "tool" && step.name && step.name !== step.label) {
      head.append(makeEl("code", "chat-step__name", step.name));
    }
    const duration = Number(step.duration_ms) || 0;
    head.append(makeEl("span", "chat-step__time", status === "running"
      ? "进行中…" : duration > 0 ? duration + "ms" : ""));
    main.append(head);
    const args = formatChatStepArgs(step.args);
    if (args) main.append(makeEl("div", "chat-step__args", args));
    const detail = String(step.detail || "").trim()
      || (status === "running" ? "正在执行…" : "");
    if (detail) main.append(makeEl("div", "chat-step__detail", detail));
    item.append(main);
    list.append(item);
  });
  wrap.append(list);
  return wrap;
}

function buildChatMessage(m) {
  const isUser = m.role === "user";
  const row = makeEl("div", "chat-msg chat-msg--" + (isUser ? "user" : "assistant"));
  if (!isUser) row.append(makeEl("span", "chat-msg__avatar", "◐"));
  const body = makeEl("div", "chat-msg__body");

  if (m.error) {
    body.append(makeEl("div", "chat-msg__error", m.content || "请求失败"));
  } else if (isUser) {
    body.textContent = m.content || "";
  } else {
    const reason = m.reason === "SESSION_LIMIT" ? "会话上限"
      : m.source === "llm" ? "AI · 白名单已过" : "确定性回答";
    const sourceClass = m.source === "llm" ? "llm" : "fallback";
    const meta = makeEl("div", "chat-msg__meta");
    meta.append(makeEl("span", "chat-source chat-source--" + sourceClass, reason));
    if (m.reason && m.source !== "llm") {
      meta.title = CHAT_REASON_LABEL[m.reason] || "按确定性规则回答";
    }
    body.append(meta);
    const steps = Array.isArray(m.tool_steps) ? m.tool_steps : [];
    if (steps.length) body.append(buildChatSteps(steps, false));
    body.append(makeEl("div", "chat-msg__text", m.content || ""));
    if (Array.isArray(m.artifacts) && m.artifacts.length) {
      body.append(buildChatArtifacts(m.artifacts));
    }
    if (!steps.length && Array.isArray(m.tool_trace) && m.tool_trace.length) {
      const details = makeEl("details", "chat-tools");
      const isLlm = m.source === "llm";
      details.append(makeEl("summary", "", isLlm
        ? `查了 ${m.tool_trace.length} 个工具`
        : "回答依据"));
      const ul = makeEl("ul");
      if (isLlm) {
        for (const line of m.tool_trace) ul.append(makeEl("li", "", line));
      } else {
        const why = CHAT_REASON_LABEL[m.reason] || "按确定性规则回答";
        ul.append(makeEl("li", "", "确定性路由：" + why));
      }
      details.append(ul);
      body.append(details);
    }
    if (Array.isArray(m.refs) && m.refs.length) body.append(buildChatRefs(m.refs));
    const turns = Number(m.session_turns) || 0;
    if (turns > 0) {
      body.append(makeEl("div", "chat-msg__foot",
        `调用 ${Number(m.model_calls) || 0} 次模型 · 对话第 ${turns} 轮`));
    }
  }
  row.append(body);
  return row;
}

function buildChatLoading() {
  const row = makeEl("div", "chat-msg chat-msg--assistant");
  row.append(makeEl("span", "chat-msg__avatar", "◐"));
  const body = makeEl("div", "chat-msg__body");
  const steps = Array.isArray(chatState.activitySteps) ? chatState.activitySteps : [];
  if (steps.length) body.append(buildChatSteps(steps, true));
  const dots = makeEl("div", "chat-loading");
  dots.append(makeEl("span"), makeEl("span"), makeEl("span"));
  let label = "正在查账…";
  if (steps.some((s) => s.kind === "submit")) {
    label = "正在校验并组织回答…";
  } else if (steps.some((s) => s.status === "running")) {
    label = "正在查账…";
  } else if (steps.length) {
    label = "继续查账…";
  }
  dots.append(makeEl("em", "", label));
  body.append(dots);
  row.append(body);
  return row;
}

function renderQuick() {
  const wrap = $("#chat-quick");
  if (!wrap) return;
  const show = chatState.messages.length === 0
    && !chatState.loading && !chatState.limitReached;
  wrap.hidden = !show;
  wrap.replaceChildren();
  if (!show) return;
  for (const q of chatState.presets) {
    const chip = makeEl("button", "chat-chip", q);
    chip.type = "button";
    chip.addEventListener("click", () => {
      if (chatState.loading) return;
      $("#chat-input").value = q;
      resizeChatInput();
      sendChat();
    });
    wrap.append(chip);
  }
}

function renderChat() {
  const log = $("#chat-log");
  if (!log) return;
  log.replaceChildren();
  if (!chatState.messages.length) {
    log.append(buildChatEmpty());
  } else {
    for (const m of chatState.messages) log.append(buildChatMessage(m));
  }
  if (chatState.loading) log.append(buildChatLoading());
  log.setAttribute("aria-busy", chatState.loading ? "true" : "false");
  renderQuick();
  renderChatSuggest();
  updateChatChrome();
  scrollChat();
}

async function loadChatStatus() {
  try {
    const st = await fetchJSON("/api/chat/status");
    chatState.available = !!st.available;
    chatState.maxTurns = Number(st.max_turns) || chatState.maxTurns;
    chatState.statusLoaded = true;
    chatState.statusError = null;
  } catch (err) {
    chatState.statusLoaded = true;
    chatState.statusError = err.message;
    chatState.available = false;
  }
  updateChatNotice();
  updateChatChrome();
}

// ── 模型设置：页面输入 key，只存服务端进程内存 ──
const MODEL_SOURCE_LABEL = { override: "页面输入", env: "环境变量" };

function renderModelStatus(st) {
  chatState.model = st || null;
  const on = !!(st && st.available);
  const btn = $("#model-btn");
  const label = $("#model-label");
  const badge = $("#model-badge");
  if (btn) btn.classList.toggle("model-btn--on", on);
  if (label) label.textContent = on ? "AI · 已连接" : "模型未配置";
  if (badge) {
    const src = MODEL_SOURCE_LABEL[st && st.source] || (st && st.source) || "未知";
    badge.textContent = on
      ? `${st.model} · ${src}${st.key_hint ? " · " + st.key_hint : ""}`
      : "未配置";
  }
  const hint = $("#model-hint");
  if (hint && !on) hint.textContent = "未配置：粘贴 key 后点“保存并测试”";
}

async function loadModelStatus() {
  try {
    renderModelStatus(await fetchJSON("/api/model"));
  } catch {
    renderModelStatus(null);
  }
}

function openModelModal() {
  const modal = $("#model-modal");
  if (!modal) return;
  modal.hidden = false;
  document.body.style.overflow = "hidden";
  const input = $("#model-key");
  if (input) { input.value = ""; input.focus(); }
  loadModelStatus();
}

function closeModelModal() {
  const modal = $("#model-modal");
  if (!modal) return;
  modal.hidden = true;
  document.body.style.overflow = "";
}

async function saveModelKey(e) {
  e.preventDefault();
  const input = $("#model-key");
  const hint = $("#model-hint");
  const save = $("#model-save");
  const key = ((input && input.value) || "").trim();
  if (!key) { if (hint) hint.textContent = "先粘贴 key 再保存"; return; }
  if (save) save.disabled = true;
  if (hint) hint.textContent = "正在用一次最小调用验证…";
  try {
    const st = await fetchJSON("/api/model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key }),
    });
    if (input) input.value = "";
    renderModelStatus(st);
    if (hint) hint.textContent = "已验证并生效：本会话立即走模型。";
    await loadChatStatus();
  } catch (err) {
    if (hint) hint.textContent = "保存失败：" + friendlyModelError(err.message);
  } finally {
    if (save) save.disabled = false;
  }
}

function friendlyModelError(message) {
  const text = String(message || "");
  if (text.includes("HTTP 401")) return "key 无效或已失效（401），检查是否复制完整。";
  if (text.includes("HTTP 402")) return "账户余额不足（402），先充值再试。";
  if (text.includes("HTTP 429")) return "请求太频繁（429），等几秒再试。";
  if (text.includes("连接失败")) return "网络连不上 DeepSeek，检查代理或稍后再试。";
  return text;
}

async function clearModelKey() {
  const hint = $("#model-hint");
  try {
    const st = await fetchJSON("/api/model", { method: "DELETE" });
    renderModelStatus(st);
    if (hint) {
      hint.textContent = st.available
        ? "已清除页面输入的 key，回落到环境变量。"
        : "已清除，当前没有可用 key。";
    }
    await loadChatStatus();
  } catch (err) {
    if (hint) hint.textContent = "清除失败：" + err.message;
  }
}

async function loadPresets() {
  try {
    const body = await fetchJSON("/api/chat/presets");
    const texts = (body.presets || [])
      .map((p) => (typeof p === "string" ? p : p.text))
      .filter(Boolean);
    if (texts.length) {
      chatState.presets = texts;
      renderQuick();
    }
  } catch {
    // 预设接口失败不挡对话：沿用内置四条
  }
}

function newChatActivityId() {
  try {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
      return globalThis.crypto.randomUUID();
    }
  } catch { /* 旧浏览器忽略 */ }
  return "act-" + Date.now().toString(36) + "-"
    + Math.random().toString(36).slice(2, 10);
}

function stopChatActivity() {
  if (chatState.activityTimer) clearInterval(chatState.activityTimer);
  chatState.activityTimer = null;
  chatState.activityId = null;
  chatState.activitySteps = [];
  chatState.activityPollingId = null;
}

function beginChatActivity() {
  stopChatActivity();
  const id = newChatActivityId();
  chatState.activityId = id;
  chatState.activitySteps = [];
  chatState.activityTimer = setInterval(pollChatActivity, 320);
  return id;
}

async function pollChatActivity() {
  const id = chatState.activityId;
  if (!id || !chatState.loading) return;
  if (chatState.activityPollingId === id) return;
  chatState.activityPollingId = id;
  try {
    const res = await fetch("/api/chat/activity/" + encodeURIComponent(id),
      { cache: "no-store" });
    if (!res.ok) return;
    const body = await res.json();
    if (chatState.activityId !== id || !chatState.loading) return;
    const steps = Array.isArray(body.steps) ? body.steps : [];
    if (JSON.stringify(steps) !== JSON.stringify(chatState.activitySteps)) {
      chatState.activitySteps = steps;
      renderChat();
    }
  } catch { /* 轮询失败不影响正式请求 */ }
  finally {
    if (chatState.activityPollingId === id) chatState.activityPollingId = null;
  }
}

async function requestChat(message, sessionId, activityId) {
  const payload = { message };
  if (sessionId) payload.session_id = sessionId;
  if (activityId) payload.activity_id = activityId;
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  let body = {};
  try { body = await res.json(); } catch { body = {}; }
  return { res, body };
}

function resizeChatInput() {
  const input = $("#chat-input");
  if (!input) return;
  input.style.height = "auto";
  input.style.height = Math.min(Math.max(input.scrollHeight, 56), 124) + "px";
}

async function sendChat() {
  if (chatState.loading || chatState.limitReached) return;
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message) { input.focus(); return; }
  if (message.length > 1000) {
    chatState.messages.push({
      role: "assistant", source: "error", error: true,
      content: "问题最长 1000 字，请缩短后再发。",
    });
    renderChat();
    return;
  }
  chatRestoreToken += 1; // 用户已开始新回合，作废仍在路上的历史恢复
  chatState.loading = true;
  const activityId = beginChatActivity();
  chatState.messages.push({ role: "user", content: message });
  input.value = "";
  input.style.height = "";
  renderChat();

  try {
    let { res, body } = await requestChat(message, chatState.sessionId, activityId);
    if (res.status === 404 && chatState.sessionId) {
      // 服务端会话已过期：旧上下文不能继续冒充“多轮”，清掉后重开
      chatState.sessionId = null;
      safeStorageRemove(CHAT_SESSION_KEY);
      chatState.turns = 0;
      chatState.messages = [{ role: "user", content: message }];
      ({ res, body } = await requestChat(message, null, activityId));
    }
    if (!res.ok) {
      const detail = typeof body.detail === "string" ? body.detail
        : "请求参数不正确";
      throw new Error(detail);
    }
    chatState.sessionId = body.session_id || chatState.sessionId;
    if (chatState.sessionId) safeStorageSet(CHAT_SESSION_KEY, chatState.sessionId);
    chatState.turns = Number(body.session_turns) || chatState.turns + 1;
    if (body.status === "unavailable" || body.reason === "SESSION_LIMIT"
        || chatState.turns >= chatState.maxTurns) {
      chatState.limitReached = true;
    }
    chatState.messages.push({
      role: "assistant",
      content: body.answer,
      source: body.source,
      refs: body.refs || [],
      tool_trace: body.tool_trace || [],
      tool_steps: Array.isArray(body.tool_steps) ? body.tool_steps : [],
      model_calls: Number(body.model_calls) || 0,
      session_turns: Number(body.session_turns) || 0,
      reason: body.reason || null,
      artifacts: Array.isArray(body.artifacts) ? body.artifacts : [],
      suggestions: Array.isArray(body.suggestions) ? body.suggestions : [],
    });
  } catch (err) {
    chatState.messages.push({
      role: "assistant", source: "error", error: true,
      content: "对话请求失败：" + err.message + "。可以稍后重试，或点“新对话”。",
    });
  } finally {
    stopChatActivity();
    chatState.loading = false;
    renderChat();
    updateChatNotice();
    if (!chatState.limitReached) input.focus();
  }
}

async function newChat() {
  if (chatState.loading) return;
  chatRestoreToken += 1; // 防止刚刷新时的历史恢复覆盖“新对话”
  const sid = chatState.sessionId;
  chatState.sessionId = null;
  safeStorageRemove(CHAT_SESSION_KEY);
  chatState.messages = [];
  chatState.turns = 0;
  chatState.limitReached = false;
  renderChat();
  updateChatNotice();
  $("#chat-input").focus();
  if (sid) {
    // 本地立即清空；服务端会话删除放到后台，不阻塞输入
    fetch(`/api/chat/${sid}`, { method: "DELETE" }).catch(() => {});
  }
}

async function restoreChat() {
  const sid = safeStorageGet(CHAT_SESSION_KEY);
  if (!sid) return;
  const token = ++chatRestoreToken;
  try {
    const res = await fetch(`/api/chat/${sid}`);
    if (token !== chatRestoreToken) return;
    if (res.status === 404) {
      safeStorageRemove(CHAT_SESSION_KEY);
      return;
    }
    if (!res.ok) throw new Error(`${res.status}`);
    const body = await res.json();
    if (token !== chatRestoreToken) return;
    chatState.sessionId = sid;
    chatState.messages = Array.isArray(body.messages) ? body.messages : [];
    chatState.turns = chatState.messages.filter((m) => m.role === "user").length;
    chatState.maxTurns = Number(body.max_turns) || chatState.maxTurns;
    chatState.limitReached = chatState.turns >= chatState.maxTurns;
    renderChat();
    updateChatNotice();
  } catch {
    // 网络或服务暂不可用：保留 sessionStorage，下次刷新再试
  }
}

function initChat() {
  $("#chat-new").addEventListener("click", newChat);
  $("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    sendChat();
  });
  $("#chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      sendChat();
    }
  });
  $("#chat-input").addEventListener("input", resizeChatInput);
  resizeChatInput();
  $("#model-btn").addEventListener("click", openModelModal);
  $("#model-form").addEventListener("submit", saveModelKey);
  $("#model-clear").addEventListener("click", clearModelKey);
  document.querySelectorAll("#model-modal [data-close]").forEach((el) => {
    el.addEventListener("click", closeModelModal);
  });
  loadChatStatus();
  loadModelStatus();
  loadPresets();
  restoreChat();
}

// ── 路由 ─────────────────────────────────────
const RENDERERS = {
  chat: () => { renderChat(); },
  data: renderData,
  about: () => {},
};

function route() {
  const name = (location.hash.replace(/^#\//, "") || "chat").split("?")[0];
  const valid = RENDERERS[name] ? name : "chat";
  for (const [key, el] of Object.entries({
    chat: $("#view-chat"), data: $("#view-data"), about: $("#view-about"),
  })) {
    el.hidden = key !== valid;
  }
  document.querySelectorAll("#tabs a").forEach((a) => {
    a.classList.toggle("active", a.dataset.tab === valid);
  });
  RENDERERS[valid]();
  // 切页回到顶部：否则从对话页带下来的滚动位置会把数据页工具栏顶到粘性数据条下面
  window.scrollTo(0, 0);
}

wireDiffsControls();
wireLedgersControls();
wireDataSeg();
initChat();
loadDatasource();
$("#ledger-ai-btn").addEventListener("click", askLedgerAttribution);
document.querySelectorAll("#ledger-modal [data-close]").forEach((el) => {
  el.addEventListener("click", closeLedger);
});
document.querySelectorAll("#tables-modal [data-close]").forEach((el) => {
  el.addEventListener("click", closeTablesModal);
});
$("#datasource-more").addEventListener("click", async () => {
  if (state.tables) { openTablesModal(); return; }
  await loadDatasource();
  if (state.tables) openTablesModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("#model-modal").hidden) { closeModelModal(); return; }
  if (!$("#ledger-modal").hidden) { closeLedger(); return; }
  if (!$("#tables-modal").hidden) { closeTablesModal(); return; }
});
window.addEventListener("hashchange", route);
route();
