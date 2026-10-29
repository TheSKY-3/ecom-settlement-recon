#!/usr/bin/env python3
"""P0 自然差异盘点：对 Olist "业务单据侧（orders+order_items）" 与 "支付流水侧
（order_payments）" 做全量自然不一致盘点，生成 docs/natural-diff-report.md。

- 仅标准库，重复运行可复现（依赖 data/olist.db，见 scripts/build_db.py）。
- 口径：金额比较容差 ±0.005 BRL（到分）；"有支付"= order_payments 中存在该 order_id。
- 平台账单侧由 P1 合成构造，本报告只覆盖 订单/明细 × 支付 两方，范围如此声明。
"""
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "olist.db"
OUT = ROOT / "docs" / "natural-diff-report.md"
TOL = 0.005


def q(conn, sql, args=()):
    return conn.execute(sql, args).fetchall()


def one(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()[0]


def md_table(headers, data):
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in data:
        lines.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    return "\n".join(lines)


def main():
    if not DB.exists():
        sys.exit(f"[FAIL] {DB} 不存在，先运行 scripts/build_db.py")
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-65536")  # 64MB 页缓存
    conn.executescript("""
    CREATE TEMP TABLE item_agg AS
    SELECT order_id, COUNT(*) AS n_items, ROUND(SUM(price),2) AS price_sum,
           ROUND(SUM(freight_value),2) AS freight_sum,
           ROUND(SUM(price)+SUM(freight_value),2) AS total
    FROM order_items GROUP BY order_id;

    CREATE TEMP TABLE pay_agg AS
    SELECT order_id, COUNT(*) AS n_pay, ROUND(SUM(payment_value),2) AS pay_sum,
           MAX(payment_installments) AS max_inst, MIN(payment_installments) AS min_inst
    FROM order_payments GROUP BY order_id;

    -- 临时表必须带 join 键索引，否则关联子查询退化为 O(n^2) 全表扫描
    CREATE INDEX tmp_item_agg_oid ON item_agg(order_id);
    CREATE INDEX tmp_pay_agg_oid ON pay_agg(order_id);
    """)

    L = []
    L.append("# P0 自然差异盘点报告（Olist 底座）")
    L.append("")
    L.append(f"> 生成日期：{date.today().isoformat()}　|　数据库：`data/olist.db`　|　"
             f"脚本：`scripts/natural_diff_inventory.py`（可复现）")
    L.append("> 口径：金额容差 ±0.005 BRL（比较到分）；\"有支付\" = `order_payments` 中存在该 "
             "order_id 的记录；\"有单\" = `order_items` 中存在该 order_id。")
    L.append("> 视角映射：**支付流水侧** = order_payments；**业务单据侧** = orders + order_items；"
             "**平台账单侧** = 由 P1 按公开佣金/运费规则合成，不在本报告范围。")
    L.append("> 所有数字均为数据集**自然发生**的不一致，用途：P1 合成注入的基线与缺口清单。")

    # ---- 1. 数据快照 ----
    L.append("\n## 1. 数据快照\n")
    snap = q(conn, """
    SELECT 'orders' t, COUNT(*) n, (SELECT COUNT(DISTINCT order_id) FROM orders) d FROM orders
    UNION ALL SELECT 'order_items', COUNT(*), (SELECT COUNT(DISTINCT order_id) FROM order_items) FROM order_items
    UNION ALL SELECT 'order_payments', COUNT(*), (SELECT COUNT(DISTINCT order_id) FROM order_payments) FROM order_payments
    UNION ALL SELECT 'order_reviews', COUNT(*), (SELECT COUNT(DISTINCT order_id) FROM order_reviews) FROM order_reviews
    UNION ALL SELECT 'customers', COUNT(*), (SELECT COUNT(DISTINCT customer_id) FROM customers) FROM customers
    UNION ALL SELECT 'sellers', COUNT(*), (SELECT COUNT(DISTINCT seller_id) FROM sellers) FROM sellers
    UNION ALL SELECT 'products', COUNT(*), (SELECT COUNT(DISTINCT product_id) FROM products) FROM products
    UNION ALL SELECT 'geolocation', COUNT(*), NULL FROM geolocation
    UNION ALL SELECT 'product_category_translation', COUNT(*), NULL FROM product_category_translation
    """)
    L.append(md_table(["表", "行数", "去重主键数"], snap))
    rng = q(conn, "SELECT MIN(order_purchase_timestamp), MAX(order_purchase_timestamp) FROM orders")[0]
    L.append(f"\n订单购买时间范围：{rng[0]} ~ {rng[1]}。")

    # ---- 2. 三方覆盖 / 单边账基线 ----
    L.append("\n## 2. 覆盖与单边账（自然基线）\n")
    cov = q(conn, """
    SELECT (SELECT COUNT(*) FROM orders) AS orders_total,
           (SELECT COUNT(*) FROM item_agg) AS orders_with_items,
           (SELECT COUNT(*) FROM pay_agg) AS orders_with_payment,
           (SELECT COUNT(*) FROM orders o JOIN item_agg i ON o.order_id=i.order_id
              JOIN pay_agg p ON o.order_id=p.order_id) AS both_sides,
           (SELECT COUNT(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM item_agg x WHERE x.order_id=o.order_id)
              AND NOT EXISTS (SELECT 1 FROM pay_agg y WHERE y.order_id=o.order_id)) AS neither
    """)[0]
    orphan_pay = one(conn, """SELECT COUNT(*) FROM order_payments p
        LEFT JOIN orders o ON p.order_id=o.order_id WHERE o.order_id IS NULL""")
    orphan_item = one(conn, """SELECT COUNT(*) FROM order_items i
        LEFT JOIN orders o ON i.order_id=o.order_id WHERE o.order_id IS NULL""")
    L.append(md_table(
        ["orders 总数", "有明细", "有支付", "两侧都有", "两侧都无",
         "孤儿支付行(无订单)", "孤儿明细行(无订单)"],
        [cov + (orphan_pay, orphan_item)]))

    no_items = q(conn, """SELECT o.order_status, COUNT(*) FROM orders o
        LEFT JOIN item_agg i ON o.order_id=i.order_id WHERE i.order_id IS NULL
        GROUP BY 1 ORDER BY 2 DESC""")
    no_pay = q(conn, """SELECT o.order_status, COUNT(*) FROM orders o
        LEFT JOIN pay_agg p ON o.order_id=p.order_id WHERE p.order_id IS NULL
        GROUP BY 1 ORDER BY 2 DESC""")
    L.append("\n**有订单无明细**（按状态）：\n")
    L.append(md_table(["order_status", "订单数"], no_items))
    L.append("\n**有订单无支付**（按状态）：\n")
    L.append(md_table(["order_status", "订单数"], no_pay))

    # ---- 3. 金额一致性 ----
    L.append("\n## 3. 金额一致性（支付合计 vs 明细价+运费）\n")
    buckets = q(conn, f"""
    SELECT o.order_status,
           CASE WHEN i.order_id IS NULL THEN 'no_items'
                WHEN p.order_id IS NULL THEN 'no_payment'
                WHEN ABS(p.pay_sum - i.total) < {TOL} THEN 'match'
                WHEN ABS(p.pay_sum - i.price_sum) < {TOL} THEN 'pay_eq_price(免运费口径?)'
                WHEN p.pay_sum < i.total THEN 'underpaid'
                ELSE 'overpaid' END AS bucket,
           COUNT(*)
    FROM orders o
    LEFT JOIN item_agg i ON o.order_id=i.order_id
    LEFT JOIN pay_agg p ON o.order_id=p.order_id
    GROUP BY 1, 2 ORDER BY 1, 2""")
    L.append(md_table(["order_status", "金额桶", "订单数"], buckets))

    both_n = sum(n for _, b, n in buckets if b not in ("no_items", "no_payment"))
    match_n = sum(n for _, b, n in buckets if b == "match")
    eq_price_n = sum(n for _, b, n in buckets if b.startswith("pay_eq_price"))
    under_n = sum(n for _, b, n in buckets if b == "underpaid")
    over_n = sum(n for _, b, n in buckets if b == "overpaid")
    L.append(f"\n两侧齐全的订单共 **{both_n}** 单：完全一致 **{match_n}**（"
             f"{match_n/both_n*100:.2f}%）；支付=仅商品价（运费未收）**{eq_price_n}**；"
             f"少付 **{under_n}**；多付 **{over_n}**。")

    L.append("\n### 差异金额分布（|d| ≥ 0.005，d = 支付合计 − 单据合计）\n")
    dist = q(conn, f"""
    WITH j AS (
      SELECT p.pay_sum - i.total AS d
      FROM orders o JOIN item_agg i ON o.order_id=i.order_id JOIN pay_agg p ON o.order_id=p.order_id
      WHERE ABS(p.pay_sum - i.total) >= {TOL})
    SELECT CASE WHEN d > 0 THEN 'over(多付)' ELSE 'under(少付)' END dir,
           CASE WHEN ABS(d) < 1 THEN 'a. [0,1)' WHEN ABS(d) < 10 THEN 'b. [1,10)'
                WHEN ABS(d) < 50 THEN 'c. [10,50)' WHEN ABS(d) < 100 THEN 'd. [50,100)'
                WHEN ABS(d) < 500 THEN 'e. [100,500)' ELSE 'f. >=500' END mag,
           COUNT(*), ROUND(SUM(d), 2)
    FROM j GROUP BY 1, 2 ORDER BY 1, 2""")
    L.append(md_table(["方向", "金额区间 (BRL)", "订单数", "差异合计"], dist))

    # ---- 4. 状态 × 支付矩阵 ----
    L.append("\n## 4. 状态一致性（取消/不可达但有支付 = 状态不一致基线）\n")
    matrix = q(conn, """
    SELECT o.order_status,
           COUNT(*) AS n_orders,
           SUM(CASE WHEN p.order_id IS NULL THEN 1 ELSE 0 END) AS no_payment,
           SUM(CASE WHEN p.order_id IS NOT NULL AND o.order_approved_at IS NOT NULL
                    THEN 1 ELSE 0 END) AS paid_approved,
           SUM(CASE WHEN p.order_id IS NOT NULL AND o.order_approved_at IS NULL
                    THEN 1 ELSE 0 END) AS paid_not_approved,
           ROUND(SUM(CASE WHEN o.order_status IN ('canceled','unavailable')
                          THEN COALESCE(p.pay_sum,0) ELSE 0 END), 2) AS cancel_paid_value
    FROM orders o LEFT JOIN pay_agg p ON o.order_id=p.order_id
    GROUP BY 1 ORDER BY 2 DESC""")
    L.append(md_table(["order_status", "订单数", "无支付", "已支付且已审批",
                       "有支付未审批", "取消/不可达单的支付额(BRL)"], matrix))
    c_u = one(conn, """SELECT COUNT(*) FROM orders o JOIN pay_agg p ON o.order_id=p.order_id
                       WHERE o.order_status IN ('canceled','unavailable')""")
    c_u_val = one(conn, """SELECT ROUND(SUM(p.pay_sum),2) FROM orders o
        JOIN pay_agg p ON o.order_id=p.order_id WHERE o.order_status IN ('canceled','unavailable')""")
    c_u_appr = one(conn, """SELECT COUNT(*) FROM orders o JOIN pay_agg p ON o.order_id=p.order_id
        WHERE o.order_status IN ('canceled','unavailable') AND o.order_approved_at IS NOT NULL""")
    L.append(f"\n取消/不可达（canceled+unavailable）却有支付记录的订单 **{c_u}** 单，"
             f"合计 **{c_u_val} BRL**（其中 {c_u_appr} 单支付曾审批通过）。"
             f"Olist 无退款流水表，这批钱是\"取消未退\"的自然代理样本。")

    # ---- 5. 重复基线 ----
    L.append("\n## 5. 重复与键异常（自然基线）\n")
    dup_orders_n = one(conn, "SELECT COUNT(*) FROM (SELECT order_id FROM orders GROUP BY 1 HAVING COUNT(*)>1)")
    dup_pay_n = one(conn, "SELECT COUNT(*) FROM (SELECT 1 FROM order_payments GROUP BY order_id, payment_sequential HAVING COUNT(*)>1)")
    dup_item_n = one(conn, "SELECT COUNT(*) FROM (SELECT 1 FROM order_items GROUP BY order_id, order_item_id HAVING COUNT(*)>1)")
    dup_rev_n = one(conn, "SELECT COUNT(*) FROM (SELECT 1 FROM order_reviews GROUP BY review_id HAVING COUNT(*)>1)")
    multi_rev_orders = one(conn, "SELECT COUNT(*) FROM (SELECT 1 FROM order_reviews GROUP BY order_id HAVING COUNT(*)>1)")
    L.append(md_table(
        ["重复项", "数量", "说明"],
        [["orders 中重复的 order_id", dup_orders_n, ""],
         ["order_payments 中重复 (order_id, payment_sequential)", dup_pay_n, ""],
         ["order_items 中重复 (order_id, order_item_id)", dup_item_n, ""],
         ["order_reviews 中重复的 review_id", dup_rev_n, ""],
         ["同单多条评价记录的订单数", multi_rev_orders, "对账无直接影响，备注"]]))
    dup_rows = q(conn, """SELECT order_id, customer_id, order_status, order_purchase_timestamp
        FROM orders WHERE order_id IN
          (SELECT order_id FROM orders GROUP BY order_id HAVING COUNT(*)>1)
        ORDER BY order_id""")
    if dup_rows:
        L.append("\n重复 order_id 明细：\n")
        L.append(md_table(["order_id", "customer_id", "status", "purchase_ts"], dup_rows))

    # ---- 6. 支付形态基线 ----
    L.append("\n## 6. 支付形态基线（分期 / 多笔 / 零额）\n")
    ptypes = q(conn, """SELECT payment_type, COUNT(*), ROUND(SUM(payment_value),2),
        SUM(CASE WHEN payment_value<=0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN payment_installments=0 THEN 1 ELSE 0 END)
        FROM order_payments GROUP BY 1 ORDER BY 2 DESC""")
    L.append(md_table(["payment_type", "支付行数", "金额合计(BRL)", "零/负额行", "分期=0 行"], ptypes))
    npay = q(conn, "SELECT n_pay, COUNT(*) FROM pay_agg GROUP BY 1 ORDER BY 1")
    L.append("\n单订单支付笔数分布（n_pay = 该订单 payment 行数）：\n")
    L.append(md_table(["n_pay", "订单数"], npay))
    inst = q(conn, """SELECT payment_installments, COUNT(*) FROM order_payments
                      GROUP BY 1 ORDER BY 1""")
    L.append("\n分期数分布（payment_installments）：\n")
    L.append(md_table(["installments", "支付行数"], inst))

    # ---- 7. 抽样 ----
    L.append("\n## 7. 各类异常抽样（每类 5 条，供人工复核口径）\n")
    SEL = ("o.order_id, o.order_status, i.n_items, i.price_sum, i.freight_sum, i.total, "
           "p.n_pay, p.pay_sum, ROUND(p.pay_sum-i.total,2) AS diff")
    FROMW = ("FROM orders o JOIN item_agg i ON o.order_id=i.order_id "
             "JOIN pay_agg p ON o.order_id=p.order_id ")
    HDR = ["order_id", "status", "n_items", "商品价", "运费", "单据合计", "支付笔数", "支付合计", "差异d"]
    samples = [
        ("少付最多（underpaid）", f"SELECT {SEL} {FROMW} WHERE p.pay_sum - i.total < -{TOL} ORDER BY p.pay_sum-i.total ASC LIMIT 5"),
        ("多付最多（overpaid）", f"SELECT {SEL} {FROMW} WHERE p.pay_sum - i.total > {TOL} ORDER BY p.pay_sum-i.total DESC LIMIT 5"),
        ("支付=仅商品价（pay_eq_price）", f"SELECT {SEL} {FROMW} WHERE ABS(p.pay_sum-i.total) >= {TOL} AND ABS(p.pay_sum-i.price_sum) < {TOL} LIMIT 5"),
        ("取消/不可达却有支付", """SELECT o.order_id, o.order_status, o.order_approved_at, p.n_pay, p.pay_sum, p.max_inst
            FROM orders o JOIN pay_agg p ON o.order_id=p.order_id
            WHERE o.order_status IN ('canceled','unavailable') ORDER BY p.pay_sum DESC LIMIT 5"""),
        ("已送达但无支付记录", """SELECT o.order_id, o.order_status, o.order_purchase_timestamp
            FROM orders o LEFT JOIN pay_agg p ON o.order_id=p.order_id
            WHERE o.order_status='delivered' AND p.order_id IS NULL LIMIT 5"""),
        ("支付笔数最多（多笔支付）", f"SELECT {SEL} {FROMW} ORDER BY p.n_pay DESC LIMIT 5"),
    ]
    for title, sql in samples:
        L.append(f"\n**{title}**\n")
        data = q(conn, sql)
        if not data:
            L.append("（自然数据中无此类样本）")
            continue
        hdr = HDR if len(data[0]) == len(HDR) else \
            ["order_id", "status", "approved_at", "n_pay", "pay_sum", "max_inst"]
        if title == "已送达但无支付记录":
            hdr = ["order_id", "status", "purchase_ts"]
        L.append(md_table(hdr, data))

    # ---- 8. 雷区映射 ----
    L.append("\n## 8. 自然基线 → P1 注入雷区映射\n")
    no_pay_total = sum(n for _, n in no_pay)
    no_items_total = sum(n for _, n in no_items)
    L.append(md_table(
        ["差异类型（雷区）", "自然发生量（本报告口径）", "P1 处置"],
        [["单边账", f"有订单无支付 {no_pay_total}；有订单无明细 {no_items_total}；"
                    f"孤儿支付行 {orphan_pay}；孤儿明细行 {orphan_item}",
          "无明细 775 单样本充足；\"已送达但无支付\"仅 1 单，作为保留金样本并注入变体"],
         ["金额不符", f"少付 {under_n} + 多付 {over_n}；支付=仅商品价 {eq_price_n}（自然数据不存在该模式）",
          "自然样本充足；注入时补充\"拆单支付/含运费口径\"受控变体"],
         ["状态不一致", f"canceled/unavailable 但有支付 {c_u} 单（{c_u_val} BRL，{c_u_appr} 单曾审批）",
          "自然样本作为保留测试集；注入变体：canceled 无支付但账单已开"],
         ["退款遗漏", f"自然数据无退款流水表；代理信号 = 取消/不可达单已付额 {c_u_val} BRL",
          "退款流水侧需全量合成注入"],
         ["重复结算", f"支付键重复 {dup_pay_n}；明细键重复 {dup_item_n}",
          "自然几乎为零 → 需全量注入"],
         ["版本差异（账单新旧版）", "自然数据不存在账单侧 → 无法自然发生",
          "全量注入（对应新旧账单兼容场景）"]]))

    # ---- 9. 结论 ----
    L.append("\n## 9. P0 结论\n")
    mismatch_total = under_n + over_n + eq_price_n
    small10 = sum(n for _d, mag, n, _s in dist if mag in ("a. [0,1)", "b. [1,10)"))
    L.append(f"1. 两侧齐全订单的金额一致率 {match_n/both_n*100:.2f}%（{match_n}/{both_n}）；"
             f"自然不一致 {mismatch_total} 单（{mismatch_total/both_n*100:.2f}%），"
             f"多付 {over_n} 单、少付 {under_n} 单；其中 {small10}/{mismatch_total} 单差异在 "
             f"10 BRL 以内（分位尾差形态），10 BRL 以上大额差异是真实异常样本。")
    L.append(f"2. 单边账形态：无明细 {no_items_total} 单（集中在 canceled/unavailable，含 1 单 "
             f"shipped 无明细）、无支付仅 {no_pay_total} 单且状态为 delivered；孤儿支付/明细 0，"
             f"说明该数据集对 orders 的引用完整性良好，单边账注入需自行构造。")
    L.append(f"3. 取消/不可达但已支付 {c_u} 单（{c_u_val} BRL，{c_u_appr} 单曾审批）是最大的自然差异面，"
             f"可直接用作\"状态不一致/退款遗漏\"的 ground truth 种子。")
    L.append("4. 重复结算（支付/明细键零重复）与版本差异（无账单侧）在自然数据中不存在，是纯注入区；"
             "退款遗漏需合成退款流水表（P1 设计）。")
    L.append("5. 结构冻结：原始层 schema 见 `sql/01_schema.sql`（无约束原始层，重复键不丢行）；"
             "已知数据特性：product_category_name_translation.csv 带 BOM（加载已兼容）、"
             "789 条重复 review_id、2 条分期=0 的 credit_card 行、3 条 not_defined 零额支付行。")

    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    conn.close()

    print(f"orders={cov[0]} with_items={cov[1]} with_pay={cov[2]} both={cov[3]}")
    print(f"match={match_n}/{both_n} ({match_n/both_n*100:.2f}%)  "
          f"under={under_n} over={over_n} pay_eq_price={eq_price_n}")
    print(f"no_payment={no_pay_total} no_items={no_items_total} "
          f"orphan_pay={orphan_pay} orphan_item={orphan_item}")
    print(f"canceled/unavailable paid={c_u} ({c_u_val} BRL)")
    print(f"dup: orders={dup_orders_n} pay_keys={dup_pay_n} item_keys={dup_item_n} review_ids={dup_rev_n}")
    print(f"[OK] report -> {OUT}")


if __name__ == "__main__":
    main()
