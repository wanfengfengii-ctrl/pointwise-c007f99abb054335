# 线扫卷归档与交班复检

采集端给白班导入员交付固定块卷。白班质控员按原块号分批复检，归档员发布勘误，夜班质控员用获准版次核账并凭报告号交班。样例给卷 `coil-04` 的末两块改值，并保留白班原任务的定版读数。

## 运行

需要 Python 3.11 标准库。在项目根目录运行平台提供的完整检查入口和样例演示。

```sh
python3 -B check_project.py
python3 -B demo.py
```

也可用 `python3 -B -m unittest discover -s tests -t .` 直接运行同一测试包。演示和测试会建立自己的临时工作区。业务接口也可打开实验室已有的工作区。

## Python 接口

先用 `archive.session.open_archive(root)` 打开或初始化工作区。它会接续具备条件的归位并清理未接纳的导入介质。可以反复打开同一目录。已经验收的卷使用工作区内自己的基卷字节，修改外部输入文件只影响以后显式提交。

| 导入位置 | 调用 | 成功结果 |
| --- | --- | --- |
| `archive.importer` | `ingest(ws, reel_id, layout, blocks, checksums)` | 返回 `ReelRecord`，可用卷号领取首版任务 |
| `revision.publication` | `amend(ws, reel_id, request_id, parent_version, replacements)` | 返回 `AmendReceipt`，含卷号、请求号、固定新版号 |
| `reader.tasks` | `open(ws, reel_id)` | 返回 `ReadTask`，含任务号、固定版和勘误出处 |
| `reader.cursor` | `next(ws, task_id, limit)` | 返回原序 `Observation` 元组，每条有 `block_no` 和 `value` |
| `reader.release` | `finish(ws, task_id)` | 完成任务并释放介质依赖，触发符合资格的归位 |
| `reports.issue` | `report(ws, task_id=task_id, threshold=26)` 或 `report(ws, report_id=report_id)` | 签发或领取封存核账字典 |

`archive.layout.BlockLayout(block_count, block_width)` 的两个值必须为正整数，积须在有符号文件偏移范围内。输入是按原块号有序的 `bytes` 和对应的小写 SHA-256 十六进制摘要。原块号从 0 起。每块按小端二补码解出一个有符号整数，单位为采集原始计数。样例块宽为四字节。卷号和请求号均为非空文本，请求号在工作区内唯一。首版编号是 1。

更正项是由 `(原块号, 替换字节)` 组成的可迭代对象。目标原块号须互异，替换须等长，父版须为当前版。同号、同参数重投可续办待提交工作或领取原回执，重排替换项仍属同参。更正发布前领取的任务绑定父版，成功后领取的任务绑定整批新版。每卷同时保留一批未归位的更正以及每个改动块的一份额外块载荷。SQLite 目录保存身份、摘要、进度和已解码的核账底稿。实际取块来自固定偏移基卷或更正区。归位期间已发布新版仍可读，已核验基卷后先回收更正区，再开放下一批。

读取上限为正整数。读尽后继续领取返回空元组。读取以整批为单位核验和提交，损坏使本批失败并保留原游标。任务读尽后可签发报告，`finish` 用于释放持有的版次依赖，可以重复调用。报告包含 `report_id`、`task_id`、`reel_id`、`version`、`source_request`、`threshold`、`range`、`hits` 和 `count`。计算按原块顺序，取全卷最小值和最大值，筛出值大于等于整数阈值的原块。没有命中时仍返回全卷范围。历史领取直接交付封存件，归位和后续勘误不会改变它。

非法布局、输入范围和操作状态报 `ValueError`，未知卷、任务或报告报 `LookupError`。块校验和短读可报 `BlockIntegrityError`，介质访问也可报 `OSError`。待提交批次发生介质写入失败时可以同参重投。已成功发布后的归位介质错误会留下待办和日志，重开会再次尝试，也可通过 `revision.finalize.finalize_if_ready(ws, reel_id)` 检查和重试。运行时由归档接口独占管理工作区内的介质，应用输入应存放在工作区介质目录以外。

## 样例一天

1. 白班验收 `examples/reel.json`，按原块号登记 `12、18、25、31`。
2. 白班领取首版任务并读取 `12、18`，游标持久停在块 2。
3. 归档员提交 `examples/correction.json`，申请把块 2 和 3 改为 `26、33`。
4. 整批发布后，夜班领取版 2 并读出 `12、18、26、33`。白班重开后仍从块 2 领取 `25、31`。
5. 两版各以 26 核账。旧版范围是 `12–31`，命中块 3。新版范围是 `12–33`，命中块 2 和 3。
6. 两班完成任务。基卷归位后更正区释放八字节，夜班重开按各自报告号取得原结果。

回归另用实际子进程分别在第一份更正持久后、回包前及归位各阶段退出，核对重开、重投、固定版读取及实际更正文件。独立双版夹具直接登记合法目录和字节，覆盖已有双版介质上的定版续读。
