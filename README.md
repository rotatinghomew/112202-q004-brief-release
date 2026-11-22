# 套册登记与跨馆换件资料

`data/` 为离线合成业务记录。文件均为 UTF-8 的 Tab 分隔表，首行是列名，逗号分隔集合，`-` 表示不适用，`?` 表示未取得，不把它们当作零。标识符只在各表声明的归属范围内有效。

## 运行与资料核对

使用 Python 3.11。分析环境另附固定版本的数值与统计依赖，可在本地虚拟环境执行 `python3 -m pip install -r requirements.txt`。

```sh
python3 inspect_packet.py
python3 -m unittest discover -s tests
```

前一条命令只检查表头和记录形状并显示行数。可传入另一目录读取同格式记录。当前没有分析、决策或业务处理结果。

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
