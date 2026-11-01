"""规则树：把订单视图判成六类发现。先形态后金额，一单至多一条金额类发现。

判定谓词与 P1 埋雷逐条对齐（docs/superpowers/specs/2026-09-26-p2-engine-design.md 第 1 节）；
金额期望复用 src/synth/bills.py 的规则卡实现——造数与判卷同一口径，杜绝两边漂移。
"""
from __future__ import annotations

from src.synth.bills import amounts_from_items
from src.synth.config import NO_BILL_STATUSES, TOLERANCE, WRONG_RATE


def classify(world) -> list[dict]:
    findings: list[dict] = []

    def emit(order_id, diff_type, variant, target_side, confidence, description,
             evidence, amount=None):
        findings.append({"finding_id": "", "order_id": order_id, "diff_type": diff_type,
                         "variant": variant, "target_side": target_side,
                         "confidence": confidence, "description": description,
                         "evidence": evidence, "amount": (None if amount is None
                                                          else round(float(amount), 2)),
                         "verified": False})

    # #1 孤儿账单：账单的订单号不在订单表
    for oid, bills in world.bills_by_order.items():
        if oid not in world.orders:
            emit(oid, "单边账", "孤儿账单", "bills", 1.0, "孤儿账单：订单不存在",
                 {"bill_ids": [b["bill_id"] for b in bills]},
                 amount=sum(float(b["settlement_amount"]) for b in bills))

    for oid, order in world.orders.items():
        items = world.items_by_order.get(oid, [])
        bills = world.bills_by_order.get(oid, [])
        pays = world.payments_by_order.get(oid, [])
        refunds = world.refunds_by_order.get(oid, [])
        paid = round(sum(float(p["payment_value"]) for p in pays), 2)
        approved = bool((order.get("order_approved_at") or "").strip())
        no_bill_status = order["order_status"] in NO_BILL_STATUSES

        # 退款侧异常：不该有的退款（活跃单、或未审批取消单出现退款）
        if refunds and not (no_bill_status and approved):
            emit(oid, "金额不符", "不该有的退款", "refunds", 0.8,
                 "非「已审批的取消单」出现退款记录",
                 {"refund_ids": [r["refund_id"] for r in refunds]},
                 amount=sum(float(r["refund_amount"]) for r in refunds))

        if no_bill_status:
            if bills:                                   # #2 状态不一致
                emit(oid, "状态不一致", "取消单被开账单", "bills", 1.0,
                     "取消/不可达订单出现在账单中",
                     {"bill_ids": [b["bill_id"] for b in bills]},
                     amount=sum(float(b["settlement_amount"]) for b in bills))
            if approved and pays:                       # #3 退款遗漏 / 退款金额不符
                if not refunds:
                    emit(oid, "退款遗漏", "退款缺失", "refunds", 1.0,
                         "已付款的取消单无退款记录", {"paid": paid}, amount=paid)
                else:
                    for r in refunds:
                        if abs(float(r["refund_amount"]) - paid) > TOLERANCE:
                            emit(oid, "金额不符", "退款金额不符", "refunds", 0.9,
                                 "退款金额 ≠ 已付金额",
                                 {"refund_id": r["refund_id"], "paid": paid,
                                  "refund_amount": float(r["refund_amount"])},
                                 amount=abs(float(r["refund_amount"]) - paid))
            continue                                    # 取消单不做账单金额核对

        if not items:
            continue                                    # 无明细订单无账单期望（P0：775 单）

        if not bills:
            # 删账单/双缺失：账单不存在，金额取规则卡期望（应付卖家应该是多少）
            exp_price, exp_freight, exp_fee = amounts_from_items(items)
            exp_settle = round(exp_price + exp_freight - exp_fee, 2)
            if pays:                                    # #4 删账单
                emit(oid, "单边账", "删账单", "bills", 1.0,
                     "账单缺失：有明细有支付但无账单", {"paid": paid},
                     amount=exp_settle)
            else:                                       # #5 账与支付双缺失
                emit(oid, "单边账", "账与支付均缺失", "bills", 0.8,
                     "账单与支付双双缺失", {"n_items": len(items)},
                     amount=exp_settle)
            continue

        if len({b["version"] for b in bills}) > 1:      # #6 版本差异（命中即停）
            settles = [float(b["settlement_amount"]) for b in bills]
            emit(oid, "版本差异", "两版并存", "bills", 1.0, "两版账单并存，按最高版本对账",
                 {"bill_ids": [b["bill_id"] for b in bills],
                  "versions": sorted({b["version"] for b in bills})},
                 amount=max(settles) - min(settles))
            continue
        if len(bills) > 1:                              # #7 重复结算
            emit(oid, "重复结算", "整单重复", "bills", 1.0, "同订单同版本账单重复",
                 {"bill_ids": [b["bill_id"] for b in bills]},
                 amount=sum(float(b["settlement_amount"]) for b in bills[1:]))
            continue
        if not pays:                                    # #8 删支付
            # 涉案金额按支付侧口径：缺的是"客户该付的那笔"（货款+运费），
            # 不是账单结算额（那是卖家视角、已扣佣金）——与考卷记录口径一致
            p_price, p_freight, _ = amounts_from_items(items)
            emit(oid, "单边账", "删支付", "payments", 1.0, "支付缺失",
                 {"bill_ids": [b["bill_id"] for b in bills]},
                 amount=p_price + p_freight)
            continue

        # #9 账单侧金额 vs 规则卡期望（依次：货款→佣金→运费→结算额）
        exp_price, exp_freight, exp_fee = amounts_from_items(items)
        exp_settle = round(exp_price + exp_freight - exp_fee, 2)
        b = bills[0]
        ev = {"bill_id": b["bill_id"], "rate": b["commission_rate"]}
        if abs(float(b["price_amount"]) - exp_price) > TOLERANCE:
            emit(oid, "金额不符", "货款不符", "bills", 0.8, "账单货款 ≠ 明细货款合计",
                 {**ev, "expected": exp_price, "actual": float(b["price_amount"])},
                 amount=abs(float(b["price_amount"]) - exp_price))
        elif abs(float(b["commission_fee"]) - exp_fee) > TOLERANCE:
            if b["commission_rate"] == f"{WRONG_RATE:.2f}":
                emit(oid, "金额不符", "费率错误", "bills", 1.0,
                     f"佣金费率错误：{b['commission_rate']} ≠ 标准费率",
                     {**ev, "expected_fee": exp_fee, "actual_fee": float(b["commission_fee"])},
                     amount=abs(float(b["commission_fee"]) - exp_fee))
            else:
                emit(oid, "金额不符", "费率异常", "bills", 0.7,
                     f"佣金费率异常：{b['commission_rate']}（标准 0.20）",
                     {**ev, "expected_fee": exp_fee, "actual_fee": float(b["commission_fee"])},
                     amount=abs(float(b["commission_fee"]) - exp_fee))
        elif abs(float(b["freight_amount"]) - exp_freight) > TOLERANCE:
            if float(b["freight_amount"]) == 0:
                emit(oid, "金额不符", "漏运费", "bills", 1.0, "账单漏加运费",
                     {**ev, "expected_freight": exp_freight, "actual_freight": 0.0},
                     amount=abs(0.0 - exp_freight))
            else:
                emit(oid, "金额不符", "运费不符", "bills", 0.7, "账单运费 ≠ 明细运费合计",
                     {**ev, "expected_freight": exp_freight,
                      "actual_freight": float(b["freight_amount"])},
                     amount=abs(float(b["freight_amount"]) - exp_freight))
        elif abs(float(b["settlement_amount"]) - exp_settle) > TOLERANCE:
            emit(oid, "金额不符", "结算额不符", "bills", 0.8, "应付卖家 ≠ 规则卡期望",
                 {**ev, "expected": exp_settle, "actual": float(b["settlement_amount"])},
                 amount=abs(float(b["settlement_amount"]) - exp_settle))
        elif abs(paid - round(exp_price + exp_freight, 2)) > TOLERANCE:
            # #10 账单侧干净 → 支付侧（自然差异的主要落点）
            emit(oid, "金额不符", "支付与单据不符", "payments", 0.9,
                 "支付合计 ≠ 明细货款+运费",
                 {"expected": round(exp_price + exp_freight, 2), "paid": paid},
                 amount=abs(paid - round(exp_price + exp_freight, 2)))

    for i, f in enumerate(findings, 1):
        f["finding_id"] = f"F{i:06d}"
    return findings
