# 文创试销成交与价格约定

`data/` 为离线合成业务记录。文件均为 UTF-8 的 Tab 分隔表，首行是列名，逗号分隔集合，`-` 表示不适用，`?` 表示未取得，不把它们当作零。标识符只在各表声明的归属范围内有效。

## 运行与资料核对

使用 Python 3.11。分析环境另附固定版本的数值与统计依赖，可在本地虚拟环境执行 `python3 -m pip install -r requirements.txt`。

```sh
python3 inspect_packet.py
python3 -m unittest discover -s tests
```

前一条命令只检查表头和记录形状并显示行数。可传入另一目录读取同格式记录。当前没有分析、决策或业务处理结果。

## 输入表
- `items.tsv`：pack 是原始规格；pieces 是该销售单位件数；grade 与 finish 为采购核定的规格字段。 列为 `sku`、`pack`、`pieces`、`grade`、`finish`。
- `bundles.tsv`：包装在 start 至 end（不含）月份内生效；可含另一层销售包装。 列为 `pack`、`component`、`qty`、`start`、`end`。
- `quotes.tsv`：金额分；discount_basis=order 表示整行一次折扣，unit 表示每销售单位；received 为月份内来源批次序号，跨月也是同一递增序列。 列为 `trade`、`month`、`channel`、`sku`、`units`、`gross`、`discount`、`discount_basis`、`received`。
- `bridges.tsv`：basis 表示单位等价、经核实际件数比例或档次改换；approval 可为核准、待核或撤回，最新收到记录可改变状态。 列为 `submission`、`previous`、`replacement`、`channel`、`start`、`basis`、`approval`、`received`。
- `component_bounds.tsv`：所涉礼包每销售单位中该成分可支持的最低和最高金额，来源为同类规格独售记录与采购裁定。 列为 `pack`、`component`、`month`、`channel`、`lower`、`upper`、`received`。
- `weights.tsv`：分合同篮和渠道固定，share 为百分数。 列为 `basket`、`channel`、`anchor`、`grade`、`share`。
- `wholesale.tsv`：coverage、trigger 均为百分数；next_period 是目前还可变更的付款月份。 列为 `contract`、`basket`、`base`、`coverage`、`trigger`、`consecutive`、`next_period`。
- `announcements.tsv`：旧公告只记录当初正式结论；? 表示当时未能出指数；已锁价单不可重发覆盖。 列为 `record`、`contract`、`month`、`as_of`、`state`、`old_index`、`price_sheet`。
