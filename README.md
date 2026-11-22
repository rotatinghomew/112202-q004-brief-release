# 经营简报底稿

`data/` 为离线合成业务记录。文件均为 UTF-8 的 Tab 分隔表，首行是列名，逗号分隔集合，`-` 表示不适用，`?` 表示未取得，不把它们当作零。标识符只在各表声明的归属范围内有效。

## 运行与资料核对

使用 Python 3.11。分析环境另附固定版本的数值与统计依赖，可在本地虚拟环境执行 `python3 -m pip install -r requirements.txt`。

```sh
python3 inspect_packet.py
python3 -m unittest discover -s tests
```

前一条命令只检查表头和记录形状并显示行数。可传入另一目录读取同格式记录。当前没有分析、决策或业务处理结果。

## 输入表

- `sales.tsv`：成交 ID 唯一；每个已结成交计一次；refunded=1 表示发生退款。一笔可有多个工作室。参与数为所在格内曾参与成交的工作室并集。 列顺序为 `deal`、`period`、`counter`、`product`、`studios`、`refunded`。
- `availability.tsv`：格状态：closed 表示业务禁售的结构零，missing 表示来源缺测（不是零），complete 表示采集完整。未列出的为 complete。 列顺序为 `period`、`counter`、`product`、`state`。
- `audience.tsv`：share_with 为明确可共享经营简报的直接联系，按连通分享考虑；不含内部审核员。 列顺序为 `reader`、`share_with`。
- `direct.tsv`：受众获准直接获知当前事实的范围；all 为该维总计，metrics 为 deals/studios/returns。 列顺序为 `reader`、`period`、`counter`、`product`、`metric`、`value`。
- `releases.tsv`：已签、已送达、候审各自状态；同一期 rev 更高为更正版。相等上下界为精确披露；上期发出的精确件即使被新稿替换仍可见。 列顺序为 `id`、`reader`、`period`、`counter`、`product`、`metric`、`rev`、`lo`、`hi`、`state`。
- `requests.tsv`：dimensions 用逗号分隔；小格定义为 1 到 max_small（含）；min_width 按整数上下界之差；utility 为一级汇总优先权（越大越重要）。 列顺序为 `request`、`reader`、`period`、`dimensions`、`metrics`、`max_small`、`min_width`、`utility`。
- `corrections.tsv`：交易退款事实的复核，以收到后的新 rev 为准；旧发布口径不随之抹掉。 列顺序为 `record`、`deal`、`rev`、`refunded`、`received`。
