# Casevo 澄清传播实验：必要步骤与操作位置

> 实验文件与模拟／真实接口已经实现。文本服务已配置为智谱 `glm-5.3`，向量模型为 `embedding-3`；实际凭据从 `.env` 加载，`.env.example` 仅保留密钥占位。模拟输出不代表真实实验结论。
>
> 路径统一相对于 `competition/`，文中的 `.` 表示该根目录。
> 实验工作目录：`experiments/clarification`
> 文中 `<批次编号>`、`<运行编号>` 为实际运行时替换的占位符。

当前已生成一轮 A/B/C 模拟结果：`experiments/clarification/results/mock_one_repeat/`；实际日志位于 `experiments/clarification/runs/mock/mock_one_repeat/`。真实接口已通过连通检查，并完成 C 条件 6 人、3 轮试跑，结果位于 `experiments/clarification/results/glm_C_pilot_01/`。启动方法见 `experiments/clarification/protocol.md`。

## 1．确认环境

**操作位置：终端，先进入项目根目录。**

```bash
# 在 competition 根目录执行
conda activate alien
which python
python -c "import casevo; print(casevo.__file__)"
python -m pip check
```

确认 `which python` 指向 Conda 的 `alien` 环境。编辑器中也选择此环境的解释器。

当前加载的框架位于 `alien` 环境的 site-packages，实际位置由上面的导入检查显示。
本地源码位置：`casevo-main/src/casevo/`。首轮在独立实验目录实现功能，不直接修改本地框架源码或环境中的安装文件。

## 2．创建实验目录，补充模型接口

**操作位置：编辑器中创建并打开 `experiments/clarification/`。后续终端命令均在该目录执行。**

从 `competition/` 根目录进入已创建的实验目录：

```bash
cd experiments/clarification
```

实验文件如下；路径均相对于 `competition/`：

| 文件位置 | 补充内容 |
| --- | --- |
| `experiments/clarification/config.json` | 网络、条件、轮数、模型参数、种子、重试和预算上限 |
| `experiments/clarification/personas.json` | 六份角色及每次重复的角色位置映射 |
| `experiments/clarification/materials.json` | 传闻和澄清原文 |
| `experiments/clarification/protocol.md` | 固定时间线、判定口径、失败处理和比较方法 |
| `experiments/clarification/prompts/initial.txt` | 基线和干预后初始判断模板 |
| `experiments/clarification/prompts/update.txt` | 每轮判断与发言模板 |
| `experiments/clarification/prompts/reflect.txt` | 长期记忆反思模板 |
| `experiments/clarification/llm_adapter.py` | 真实文本生成、Embedding、调用统计 |
| `experiments/clarification/mock_llm.py` | 固定 JSON 和向量的模拟接口 |
| `experiments/clarification/agent.py` | 个体状态、判断、反思和记忆读取 |
| `experiments/clarification/model.py` | 网络、同步收件箱和消息投递 |
| `experiments/clarification/run.py` | 基线、单条件、配对重复和结果保存入口 |
| `experiments/clarification/analyze.py` | 从日志计算指标和输出图表 |
| `experiments/clarification/.gitignore` | 排除私有配置及按需排除运行产物 |
| `experiments/clarification/.env.example` | API 占位配置，复制为 `.env` 后手动替换并加载 |
| `experiments/clarification/common.py` | 配置校验、结果文件写入和版本快照 |
| `experiments/clarification/tests/test_experiment.py` | 同步传播、记忆、失败和接口机制检查 |
| `experiments/clarification/runs/` | 每次运行的独立输出目录 |

例如，模型接口文件的位置为：`experiments/clarification/llm_adapter.py`。

在 `experiments/clarification/llm_adapter.py` 中实现 Casevo 的 `send_message`、`send_embedding`、`get_lang_embedding`。凭据通过启动终端的环境变量提供，不写进配置快照或日志。先验证文本响应、JSON 解析和向量写入／查询；固定模型及采样参数，记录用量、失败和重试。

## 3．固定网络、角色和条件

**操作位置：编辑器中的以下三个配置文件。**

| 文件位置（相对于 competition） | 填写内容 |
| --- | --- |
| `experiments/clarification/config.json` | 六节点、七条无向边、三轮讨论及 A/B/C 条件 |
| `experiments/clarification/personas.json` | 打印频率、核实习惯、价格关注程度及预先确定的角色轮换 |
| `experiments/clarification/materials.json` | 固定传闻和澄清材料 |

- 群体：`{1,2,3}`、`{4,5,6}`。
- 边：`(1,2)、(2,3)、(1,3)、(4,5)、(5,6)、(4,6)、(3,4)`。
- A 无澄清；B 仅节点 1 收到；C 仅节点 3 收到。
- 传闻：“听说打印服务下周要涨价。”
- 澄清：“服务方公告：下周仅调整营业时间，打印价格保持不变。”

同一次重复内，三个条件共用相同角色位置、网络、材料和参数，分别从全新状态启动，不预设谁会被说服。

## 4．确定时间线与共同基线

**操作位置：在 `experiments/clarification/protocol.md` 写定规则，后续在 `experiments/clarification/run.py` 中组织执行。**

1. `pre`：六人只阅读传闻，各判断一次，不广播、不反思。保存同一份基线供 A、B、C 分别加载。
2. `t=0`：按条件注入澄清，六人各生成一次判断和发言，暂不反思。
3. `t=1～3`：接收邻居上一轮发言，更新判断和发言，记录经历，再反思。

基线建议保存到：

`experiments/clarification/runs/formal/<批次编号>/rep_01/baseline.json`

同次重复的三个条件分别保存到 `experiments/clarification/runs/formal/<批次编号>/rep_01/{A,B,C}/`；其余重复将路径中的 `rep_01` 替换为 `rep_02`、`rep_03`。

`t=0` 发言在 `t=1` 投递；`t=3` 发言只记录，不能计作已被邻居接收。

## 5．补充同步传播与输出校验

**操作位置：以下实现文件和提示词文件。**

| 文件位置（相对于 competition） | 负责内容 |
| --- | --- |
| `experiments/clarification/model.py` | 冻结上一轮消息、建立收件箱、沿边投递、统一提交新状态 |
| `experiments/clarification/agent.py` | 判断输出解析、字段校验和状态更新 |
| `experiments/clarification/prompts/initial.txt` | 基线与初态的可见材料、输出要求 |
| `experiments/clarification/prompts/update.txt` | 每轮上下文及输出要求 |

每轮先固定全部收件箱，再生成六人的输出，不能读取邻居刚生成的本轮发言。输出固定为：

- `belief_price_increase`：0～1 的数值。
- `opinion`：判断及依据。
- `message`：准备发送的文本。
- `share`：布尔值。

`share=true` 时向全部邻居发送同一文本，下一轮收到；否则不投递。技术失败按 `experiments/clarification/config.json` 的固定上限重试，最终失败标记运行未完成，不填默认答案。

## 6．接入记忆并检查可见范围

**操作位置：在 `experiments/clarification/agent.py` 组织记忆写入、检索和提示词组装；在 `experiments/clarification/prompts/reflect.txt` 定义反思；在 `experiments/clarification/model.py` 初始化独立记忆库。**

- 短期记忆记录实际收到和生成的消息，保留来源、目标和轮次。
- 判断提示主动加入本轮收件箱、相关短期记忆和旧长期记忆；Casevo 不会自动注入。
- 每轮反思只更新本人的长期记忆，下一轮使用。
- 每个条件使用独立数据库和 Agent，未收到澄清者看不到澄清原文、实验真值或他人私有状态。

例如，正式运行第 1 次重复 C 条件的记忆库位置为：

`experiments/clarification/runs/formal/<批次编号>/rep_01/C/memory/`

保存实际提示词到 `experiments/clarification/runs/formal/<批次编号>/rep_01/C/prompts/`，记忆轨迹到 `experiments/clarification/runs/formal/<批次编号>/rep_01/C/memory_trace.jsonl`。验收时打开节点 4 的 `t=2` 实际提示词，确认包含其 `t=1` 长期记忆和合法接收的信息。

## 7．保存日志并固定指标

**操作位置：在 `experiments/clarification/run.py` 组织保存，由 `experiments/clarification/llm_adapter.py`、`experiments/clarification/model.py`、`experiments/clarification/agent.py` 提供调用、投递和状态数据；指标规则写入 `experiments/clarification/protocol.md`，计算放入 `experiments/clarification/analyze.py`。**

以下以第 1 次重复的 C 条件为例，路径均相对于 `competition/`；其他条件替换对应批次、重复和条件名称：

| 文件位置（相对于 competition） | 内容 |
| --- | --- |
| `experiments/clarification/runs/formal/<批次编号>/rep_01/C/manifest.json` | 配置快照、版本、条件、角色映射、运行状态 |
| `experiments/clarification/runs/formal/<批次编号>/rep_01/C/states.jsonl` | 每个节点每轮的判断、分享决定和长期记忆 |
| `experiments/clarification/runs/formal/<批次编号>/rep_01/C/messages.jsonl`、`experiments/clarification/runs/formal/<批次编号>/rep_01/C/deliveries.jsonl` | 消息原文、唯一 ID、实际发送／接收节点和轮次 |
| `experiments/clarification/runs/formal/<批次编号>/rep_01/C/memory_trace.jsonl` | 记忆写入、检索和注入版本 |
| `experiments/clarification/runs/formal/<批次编号>/rep_01/C/prompts/`、`experiments/clarification/runs/formal/<批次编号>/rep_01/C/responses/` | 实际提示词与原始响应 |
| `experiments/clarification/runs/formal/<批次编号>/rep_01/C/calls.jsonl` | Token、耗时、失败和实际重试次数 |
| `experiments/clarification/runs/formal/<批次编号>/rep_01/C/annotations.jsonl` | 人工核对的澄清保留、错误传播及记忆遗漏／歪曲 |

例如 `states.jsonl` 的位置为：

`experiments/clarification/runs/formal/<批次编号>/rep_01/C/states.jsonl`

固定主要比较为“B 末轮平均误信 − C 末轮平均误信”。另统计每轮平均误信、澄清触达人数、首次跨群体轮次、错误消息及实际投递次数、记忆保留与成本。

触达根据实际投递和内容判定，接受结合分数与观点文本；A 中自发出现“不涨价”不算干预澄清传播，末轮未跨群体记为“未观察到”。

## 8．按顺序试跑与正式运行

**操作位置：终端进入 `experiments/clarification/`，通过已实现的 `run.py` 启动。完整命令及人工标注说明见 `experiments/clarification/protocol.md`。**

在实验目录执行以下命令即可生成一轮 A/B/C 模拟结果（重复执行时换一个运行编号）：

```bash
conda activate alien
python -m unittest discover -s tests -v
python run.py --backend mock --phase mock --conditions A B C --repeats 1 --run-id mock_one_repeat
python analyze.py --batch runs/mock/mock_one_repeat
```

真实运行前，若没有 `.env` 则从 `.env.example` 创建，已有 `.env` 直接编辑以保留凭据；Token 总量预算为 `0` 时无上限，正整数时启用总量限制，按 `protocol.md` 加载环境变量。占位配置不会发起真实请求。

1. 使用 `experiments/clarification/mock_llm.py` 做机制检查：只沿边传播、没有轮内提前传播、未分享消息不投递、条件间记忆隔离。输出到 `experiments/clarification/runs/mock/<运行编号>/`。
2. 使用 `experiments/clarification/llm_adapter.py` 真实运行 C 一次，确认六人三轮、记忆注入、日志和费用完整。输出到 `experiments/clarification/runs/pilot/<运行编号>/C/`。
3. 修正后冻结配置与提示词，试跑不混入正式结果。
4. 正式运行 A、B、C，各重复三次；同次重复保持角色映射一致，轮换条件运行顺序。输出到 `experiments/clarification/runs/formal/<批次编号>/rep_01～03/A、B、C/`。

运行时终端可位于实验目录；本文中的配置和输出位置始终以 `competition/` 为基准。

在 `experiments/clarification/config.json` 设置请求及费用上限。三次配对重复预计 **396 次**文本生成，另加一次 C 试跑共 **444 次**；Embedding、连通测试和重试另计。

## 9．生成并检查结果

**操作位置：在 `experiments/clarification/analyze.py` 实现分析；终端在实验工作目录启动分析入口。读取正式批次日志，输出到下列目录。**

结果目录：`experiments/clarification/results/<批次编号>/`

| 文件位置（相对于 competition） | 交付结果 |
| --- | --- |
| `experiments/clarification/results/<批次编号>/belief_curve.png` | 各条件平均误信曲线，含共同基线与 `t=0～3` |
| `experiments/clarification/results/<批次编号>/node_states.csv` | 节点状态随轮次变化的表 |
| `experiments/clarification/results/<批次编号>/message_paths.md` | 带原文和轮次的传播或中断路径 |
| `experiments/clarification/results/<批次编号>/summary.md` | 三次配对差值、成本、异常和结论限制 |

在编辑器中打开该目录核对结果，确认可从图表追溯到状态和投递日志。

结论仅描述该网络中的位置差异：节点 3 比节点 1 多一个邻居，不能单独归因于桥接作用；三次重复仅用于探索。首轮完成后再扩展到所有节点或记忆消融。
