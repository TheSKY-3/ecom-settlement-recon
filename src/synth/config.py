"""P1 造数配置（冻结项）。改动任何数值必须先过 docs/decisions.md。"""

SEED = 20260926

# 规则卡：平台账单
COMMISSION_RATE = 0.20          # 干净世界的佣金费率
WRONG_RATE = 0.10               # "金额不符-费率错误"用的错误费率
OLD_RATE = 0.15                 # "版本差异"里旧版账单用的费率
BILL_OFFSET_DAYS = 7            # 账单日期 = 审批日 + 7 天（缺审批用下单日）
REFUND_OFFSET_DAYS = 14         # 退款日期 = 审批日 + 14 天

# 金额容差（比较到分）
TOLERANCE = 0.005

# 六类雷的注入数量（评测集冻结值；改前过 decisions.md）
SINGLE_DROP_BILL = 400          # 单边账-删账单
SINGLE_ORPHAN_BILL = 100        # 单边账-孤儿账单
SINGLE_DROP_PAYMENT = 200       # 单边账-删支付
AMOUNT_WRONG_RATE = 250         # 金额不符-费率错误
AMOUNT_MISSING_FREIGHT = 250    # 金额不符-漏运费
STATUS_REBILL = 150             # 状态不一致-取消单被开账单
REFUND_MISSING = 200            # 退款遗漏
DUPLICATE_BILL = 100            # 重复结算
VERSION_DIFF = 100              # 版本差异

# 干净世界不开账单的订单状态
NO_BILL_STATUSES = {"canceled", "unavailable"}
