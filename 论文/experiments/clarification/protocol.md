# 澄清传播实验：协议与运行方法

所有文件位置相对于 `competition/`。终端命令在 `competition/experiments/clarification/` 执行，使用 Conda `alien` 环境。本协议版本为 1.0。

## 1．本次实现范围

已实现 Casevo Agent/Model/Chroma 记忆、同步传播、真实 HTTP 接口、固定模拟接口、预算与失败日志、结果分析和机制测试。真实接口采用可配置的 chat-completions 与 embeddings 请求格式；其他厂商格式需适配。

当前文本配置为智谱 `glm-5.3`，地址为 `https://open.bigmodel.cn/api/paas/v4`；示例 API Key 为 `111111` 占位，实际智谱标准 API Key 已配置在本地 `.env`。Embedding 使用同平台的 `embedding-3`，实际密钥从本地 `.env` 加载，示例文件只保留占位。原配置备份在被 Git 忽略的 `.env.before_glm*`、`.env.example.before_glm*` 中。程序会阻止空值或占位配置发出真实请求。模拟接口不访问网络，其“遇到澄清就低误信并转发”的规则仅用来验证机制，不能作为研究结果。

## 2．冻结的实验规则

- 网络、角色和材料分别读取 `config.json`、`personas.json`、`materials.json`。1～3与4～6各成完全子图，仅3～4连接。节点1度数2，节点3度数3。
- A不注入，B向1注入，C向3注入。三条件的角色映射及参数在同次重复中一致，独立重建模型和数据库。
- 每次重复共享一次 `pre`：六人只读传闻，各判断一次，无广播、无反思；只复制本人基线状态给各条件。
- `t=0`：六人再次判断，仅干预接收者看到公告，无反思。材料及自己的输出记入短期记忆。
- `t=1～3`：冻结上一轮发言→沿边投递→记录接收→检索最多5条相关记忆→冻结所有判断输入→生成六人判断→提交→记录各自输出→各反思一次。反思接收本人自上次反思后的经历与旧长期记忆。
- 仅 `share=true` 向全部邻居发送同一文本，一跳耗时一轮。`t=3` 新发言不再投递。串行计算也保持同步输入，不使用 Casevo 随机激活驱动传播。
- 人物只看到本人状态、可见材料、实际收件、本人可检索记忆和旧长期记忆。不展示条件、全图、实验真值、他人的私有得分。
- `belief_price_increase` 是0～1自报相信程度，不是校准概率。JSON严格要求四字段，拒绝字符串布尔值、越界或缺失值；无效输出不填默认分数。
- Casevo提供向量记忆及Agent内长期记忆字段；实验层显式组装提示并更新长期记忆。反思结果下一轮生效，不向邻居广播。失败不做断点续跑。

## 3．先做模拟检查和一轮示例

```bash
conda activate alien
python -m unittest discover -s tests -v
python run.py --backend mock --phase check --run-id mock_connectivity
python run.py --backend mock --phase mock --conditions A B C --repeats 1 --run-id mock_one_repeat
python analyze.py --batch runs/mock/mock_one_repeat
```

这些命令中的目录相对于当前实验工作目录。对应的项目内位置是 `experiments/clarification/runs/` 和 `experiments/clarification/results/`。

若运行编号已存在，程序拒绝覆盖；再次运行请换 `--run-id`。分析输出也拒绝覆盖，可用 `--output results/<新结果编号>`。仅需C示例时使用 `--conditions C`。

## 4．替换占位后接入真实服务

1. 在实验目录使用现有 `.env`，仅在它不存在时从 `.env.example` 创建；编辑文本与Embedding的地址、模型、API Key。两个模型及服务可不同，地址包含所需前缀但不包含 `/chat/completions` 或 `/embeddings`。环境变量覆盖 `config.json` 的地址与模型。
2. `CASEVO_MAX_TOTAL_TOKENS=0` 表示 Token 总量无上限；如需限制可填写正整数，负数无效。请求上限、文本请求上限、超时、最长运行时间在 `config.json` 设置。真实调用前人工检查。
3. 加载变量并先做连通检查：

```bash
set -a
source .env
set +a
python run.py --backend real --phase check --run-id real_connectivity
```

4. 检查返回的JSON、文本、Embedding维度与查询结果后，做C试跑：

```bash
python run.py --backend real --phase pilot --conditions C --repeats 1 --run-id real_C_pilot
python analyze.py --batch runs/pilot/real_C_pilot
```

5. 检查节点4在 `t=2` 的实际提示和记忆轨迹。确认包含本人 `t=1` 长期记忆、没有提前传播或私有信息泄漏。C未继续转发也可以是有效行为结果，不为结果强制分享。
6. 必要修改完成后重新冻结版本，再运行正式A/B/C三次重复：

```bash
python run.py --backend real --phase formal --repeats 3 --run-id real_formal_01
python analyze.py --batch runs/formal/real_formal_01
```

真实服务的温度、seed、JSON模式支持不同；通过 `send_temperature`、`send_seed`、`json_mode` 显式选择。当前GLM-5.3使用 `thinking_type=enabled`、`reasoning_effort=low`，单次输出上限4096、请求超时120秒；不发送温度或seed，判断请求启用服务端JSON模式，反思使用普通文本。GLM-5.3不支持禁用思考。若服务不支持对应参数，先在连通阶段修改并记录，不在正式运行中自动降级。

适配器不读取`.env`，需按上述命令加载。`.env`被Git忽略，密钥不写入快照或请求日志。不要把真实密钥写入`.env.example`。

## 5．预算、重复和失败

- 每条件42次文本生成：初态6次，3轮各6次判断和6次反思。每次配对重复还共享6次基线；一次A/B/C为132次，三次为396次。独立C试跑48次，总计444次，另计连通、Embedding及重试。
- 角色位置按预先保存的三份映射轮换。三次正式重复的条件顺序依次A/B/C、B/C/A、C/A/B。
- 所有实际请求共用命令级预算，包含基线、Embedding、失败及重试。Token 总量为0时只跳过此项上限，仍统计用量，并保留请求次数、文本请求次数、单次输出长度与运行时长限制。每个逻辑调用最多尝试3次，不再叠加Casevo ThoughtChain重试。认证等非暂时性HTTP错误不重试。
- Token预算按请求前UTF-8字节数加输出上限及余量预留，收到服务用量后结算。此估算不是服务方分词器，未知用量保留估算并标记未知；不能保证供应商侧硬费用限额，应同时设置服务方额度。金额不冒充实测费用。
- 达到预算、超时、重试耗尽或中断时标记失败，保留已有日志；分析拒绝未完成批次。失败或协议改变后使用新批次编号重新运行，不覆盖旧数据、不把残缺运行混入配对比较。

## 6．日志与人工标注

每批次根目录有 `batch.json`、协议副本与模板副本；每重复有共同 `baseline.json` 和基线调用记录。各条件内有独立 `manifest.json`、`states.jsonl`、`messages.jsonl`、`deliveries.jsonl`、`memory_trace.jsonl`、`calls.jsonl`、`memory/`、`prompts/`、`responses/`。

第一次分析会生成 `annotations.jsonl` 待标注项；再次分析不会覆盖已有标注。真实结果默认 `pending`，语义传播指标留空。逐条复核后：

- 消息项：把 `correction_content`、`full_correction`、`asserts_increase` 填为JSON布尔值。明确表达或完整引用“下周价格不变”算澄清内容，纯询问不算；保留营业时间调整与价格不变两点算完整；仅把涨价肯定为事实才算错误肯定，传闻、引用、询问、否定不算。
- 状态项：`opinion_stance` 选 `accepted`、`uncertain`、`rejected`、`inconsistent`。`memory_retention` 选 `preserved`、`omitted`、`distorted`、`not_applicable`；初态无反思选最后一项。只有已触达且反思过者才纳入记忆保留统计，未触达者不解释为遗忘。
- 填写 `evidence` 原文依据和 `reviewer`，将 `status` 改为 `reviewed`，使用新输出目录重新分析。模拟标签使用 `mock_fixture`，不能改名冒充人工复核。

## 7．指标与交付

- 主要位置比较：末轮B平均误信减C平均误信；同时报告A减B、A减C，每次重复单列。
- 平均误信显示 `pre` 和0～3；补充排除直接干预者的其他五人均值，此辅助群体不完全相同，不作严格同对象比较。
- 澄清触达要求源自C0且连续真实投递路径上的文本保留澄清命题。记录首次到达轮次，区分直接接收与网络新增接收。A自发猜中不算C0传播，未跨群体以空值和“未观察到”表示，不填0。
- 触达不等于接受：结合触达、`belief≤0.3`和人工认可标签。低分但观点矛盾单列。来源追溯只能表示可能依据，不证明心理因果。
- 错误说法分别统计生成条数、已经投递的分享消息条数、实际边投递次数；末轮未投递消息不计传播。记忆保留区分保留、遗漏和歪曲。
- 输出 `belief_curve.png`、`node_states.csv`、`message_paths.md`、`summary.md`、`metrics.json`，可用原始日志重新计算，不需要追加LLM调用。

结果仅限该网络与提示设置。节点3的桥接性与更高的度数混杂，三次重复不能支持普遍或显著性结论。记忆进入提示只证明通路有效，因果作用需后续消融。

## 8．已完成的真实试跑

`runs/check/glm_connectivity_03/` 连通检查通过。`runs/pilot/glm_C_pilot_01/` 已完成C条件6人3轮，文本请求48次、向量请求84次，无失败或重试，供应商报告总用量36102 Token。结果在 `results/glm_C_pilot_01/`。结构与记忆检查见 `mechanism_checks.json`，实际投递记录见 `message_deliveries.md`；语义标签仍待人工复核。本次仅为C试跑，尚未完成正式A/B/C对照。
