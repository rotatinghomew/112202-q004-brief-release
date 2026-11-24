# 套册登记与跨馆换件资料

`data/` 为离线合成业务记录。文件均为 UTF-8 的 Tab 分隔表，首行是列名，逗号分隔集合，`-` 表示不适用，`?` 表示未取得，不把它们当作零。标识符只在各表声明的归属范围内有效。

## 运行与资料核对

使用 Python 3.11。分析环境另附固定版本的数值与统计依赖，可在本地虚拟环境执行 `python3 -m pip install -r requirements.txt`。

```sh
python3 inspect_packet.py
python3 -m unittest discover -s tests
```

前一条命令只检查表头和记录形状并显示行数。可传入另一目录读取同格式记录。

## 业务核对命令

```sh
python3 -m collection_desk.cli report
python3 -m collection_desk.cli album A9
python3 -m collection_desk.cli itt
python3 -m collection_desk.cli plan
python3 -m collection_desk.cli queue
python3 -m collection_desk.cli dispositions

# 客服签认/补录使用追加账，不回写或覆盖 data/*.tsv
python3 -m collection_desk.cli --ledger .desk-state/events.jsonl \
  receive --album A8 --mark C11 --day 39
python3 -m collection_desk.cli --ledger .desk-state/events.jsonl \
  exchange --from A11 --to A12 --mark C19 --day 38
python3 -m collection_desk.cli --ledger .desk-state/events.jsonl trace --dispatch D2
```

`report` 会写出 `reports/result.json` 与 `reports/analysis.md`。事件账是 JSONL：
交卡补录、改寄确认、实际寄出日和客服签认都只追加；重查时生成内存叠加视图。
已经标记 sent 的卡会继续锁定，不会重新进入共享库存。

## 认定口径

- 足窗截止日为 `albums.opened + albums.horizon`；以 `movements.received` /
  `possibilities.received` 判断是否到手，不用安排日、`day` 或 `promised` 替代签收。
- `design.until < window_end` 时列为 `insufficient / access_truncated`；窗口未到为
  `insufficient / window_open`。未知不是零完成。
- 未编号扫描先看 cutoff 前已确认的 `possibilities`；未确认时枚举候选身份。
  同一 `mark` 在一次全局归属认定中最多支持一册，城市/册型筛选只过滤已全局认定的结果。
- ITT 只通过 `albums.visit_block -> design.assigned` 做事前分组；不使用 `movements.via`、
  后来的寄单或是否补齐回溯分组。`design.chance=0.5` 是设计概率，不冒充册级抽签结果。
- 分配只承诺整组缺件：候选卡必须在所有证据世界中均为可靠空闲、满足版本替代规则，
  并按 `delivery.latest` 的最坏寄送日和 lane 容量在 `requests.latest` 前到手。
  `requests.available_city` 按“该请求允许调用的供卡/到馆城市”处理；因此 R10(counter, B)
  不会隐式调用 A 市的 C12。
- 第 38 日 cutoff 下，若当天才新寄，最坏寄送窗使 R9/R11/R12 均无无条件可靠新方案；
  资源前沿中的 A9+A11 等是“若在第 34 日前后签认并寄出”的可兑现候选，不能倒写成第 38 日仍可承诺。

当前资料的可复现结论、分层率和候选方案见 `reports/analysis.md`。


## 输入表
- `albums.tsv`：由开册登记确定册型和开册日；horizon 是开册后完整观察天数，按自然日。 列为 `album`、`edition`、`city`、`opened`、`visit_block`、`horizon`、`protected`。
- `design.tsv`：assigned 为事前分派，chance 为被抽到资格的概率；until 为现场仍有完整观测的最末日。 列为 `visit_block`、`wave`、`assigned`、`chance`、`visited`、`until`、`city`。
- `checklist.tsv`：每册的应齐槽位及认可图案；不同槽位的实物仍独立。 列为 `edition`、`position`、`permitted`。
- `cards.tsv`：明确编号实物；早期资料中的未编号卡不在此表，需回看现场凭证。 列为 `mark`、`design`、`minted`、`available`、`city`。
- `movements.tsv`：mark 为问号时有多种候选，见辨认证据；安排不等于到手，receive 与 mail 语义不同。 列为 `record`、`album`、`mark`、`design`、`action`、`day`、`received`、`via`。
- `possibilities.tsv`：同一现场无编号卡可以是已知卡或另一张同设计旧卡；confirmed 为票据补录后确认。 列为 `record`、`candidate`、`received`、`status`。
- `requests.tsv`：latest 为需要到手截止日；跨馆实物须看寄送日窗。 列为 `request`、`album`、`channel`、`latest`、`available_city`、`destination`。
- `delivery.tsv`：日期以出信后日数计；容量按当期可寄整组数计，不等于卡张数。 列为 `from`、`to`、`earliest`、`latest`、`max_parcels`。
- `commitments.tsv`：sent 是已发出日期；promised 是预计签收，不作为实得；待签尚可调配。 列为 `dispatch`、`album`、`marks`、`sent`、`promised`、`state`。
- `guarantees.tsv`：protected_fraction 为补件后老版册的保守改善份额；cutoff 为作出决定时收到的资料日。 列为 `phase`、`min_additional`、`protected_fraction`、`cutoff`。
