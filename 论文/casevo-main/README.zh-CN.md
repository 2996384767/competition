# Casevo：认知智能体与社会演化模拟器
![Casevo 标志](logo_casevo.svg)

## 0. 最新动态

- **2025-04-22** 发布 0.3.19 版本
  - 新增 TotLogStream（`src/casevo/util/tot_log_stream.py`）。
    - 由于使用简单的 `open(fila, 'a')` 追加写入方式，再次运行时需要清空日志目录。
    - 输出格式由原来的 JSON 改为 TXT。
    - 原来的日志采用数组格式；现在每一行对应原日志数组中的一个元素，其余格式保持不变。
  - 在 `model_base.py` 中新增 VariableNetwork。
  - 在 `chain.py` 中新增 ToolStep，用于工具调用。
  - 在记忆反思中新增 CoT 功能（原文标注为 `momory.py`）。

## 1. 简介

**Casevo（Cognitive agents and social evolution simulator，认知智能体与社会演化模拟器）** 是一个 Python 框架，专门用于构建基于复杂网络的多智能体社会仿真实验或应用。本教程旨在帮助你入门。完成教程后，你将了解 Casevo 的核心功能，并逐步创建一个基础模型，随着学习进度不断增加功能。

本教程的目标是帮助你构建一个简单的基础模型，并能够对结果进行简单分析。

我们的论文可通过[此链接](https://arxiv.org/abs/2412.19498)获取，欢迎引用。

```bibtex
@misc{jiang2024casevocognitiveagentssocial,
      title={Casevo: A Cognitive Agents and Social Evolution Simulator},
      author={Zexun Jiang and Yafang Shi and Maoxu Li and Hongjiang Xiao and Yunxiao Qin and Qinglan Wei and Ye Wang and Yuan Zhang},
      year={2024},
      eprint={2412.19498},
      archivePrefix={arXiv},
      primaryClass={cs.SI},
      url={https://arxiv.org/abs/2412.19498},
}
```

## 2. 背景知识

Casevo 基于 [Mesa](https://github.com/projectmesa/mesa) 构建，因此在基本组成和运行逻辑上与 Mesa 相似。相关知识如下：

- **Mesa**：一个基于 Python 的智能体建模（[**agent-based model，ABM，个体为本模型**](https://zh.wikipedia.org/wiki/%E4%B8%AA%E4%BD%93%E4%B8%BA%E6%9C%AC%E6%A8%A1%E5%9E%8B)）工具，逻辑直观，便于二次开发。
  - [GitHub 链接](https://github.com/projectmesa/mesa)
- Mesa 仿真实验的组成：
  - Model（模型）：类似于场景的概念，定义实验中的全局场景信息，包括调度方法和建模方式。
  - Agent（智能体）：场景中的各个智能体。
  - 入口文件：仿真实验的入口，通常命名为 `run.py`。

仿真实验的基本运行逻辑：

- 入口文件反复调用模型中定义的 `step` 函数，每次调用代表一轮仿真。
- 模型的 `step` 函数调用调度器，由调度器按照调度规则安排相应智能体的 `step` 函数。

概括来说，**Model 定义全局信息和事件，Agent 定义自身的局部信息和事件**。

如需进一步了解 Mesa 的运行逻辑，请仔细阅读[文档](https://mesa.readthedocs.io/stable/tutorials/intro_tutorial.html)。

## 3. 工具安装

创建并激活 Python [虚拟环境](https://docs.python-guide.org/dev/virtualenvs/)或 [conda 环境](https://docs.conda.org.cn/projects/conda/en/stable/user-guide/index.html)。需要高于 3.11 的 Python 版本。

- 下载工具的 whl 文件 `casevo-0.3.*-py3-none-any.whl`（[下载链接](https://github.com/rgCASS/casevo/releases)）。
- 使用 `pip install casevo-0.3.*-py3-none-any.whl` 安装工具。

## 4. 构建示例仿真实验

### 4.1 仿真场景描述与配置文件构建

本节的目标是构建一个入门级社会仿真实验。在美国总统选举中，候选人会组织辩论，并通过电视播出，让候选人表达观点、争取选票。然而，辩论效果并不容易量化或衡量。为此，可以创建一组虚拟选民，模拟选民观看辩论内容、彼此讨论并最终投票的过程，从而评估候选人辩论的效果。这一设计不仅使智能体有条理地进行决策，还通过记忆机制和反思过程，体现信息交流与个人经历对最终决策的影响。

仿真实验中的关键信息包括：

- 辩论内容：使用 2020 年美国总统电视辩论的文字记录（[链接 1](https://www.debates.org/voter-education/debate-transcripts/october-22-2020-debate-transcript/)、[链接 2](https://www.presidency.ucsb.edu/documents/presidential-debate-belmont-university-nashville-tennessee-0)）。
  - 分为 6 个部分，放在 `content` 文件夹中。
- 选民画像：来源于[政治选民研究文章](https://www.pewresearch.org/politics/2021/11/09/beyond-red-vs-blue-the-political-typology-2/)。
  - 共 9 类选民画像，选取其中 3 类，以 JSON 格式配置在 `person.json` 文件中。
- 网络结构：
  - 包含 9 个节点的随机网络，采用完全网络。

> 原文的网络描述同时提到了随机网络和完全网络，并写为 9 个节点；下方示例实际生成的是 3 个节点的完全图。

可使用 `build_case.py` 中的以下代码构建仿真场景配置：

```python
import networkx as nx
from networkx.readwrite import json_graph
import matplotlib.pyplot as plt
import json
# 生成图
# 节点数量
node_num = 3
graph = nx.complete_graph(node_num)
graph_data = json_graph.node_link_data(graph)

# 配置人物画像
with open('person.json') as f:
    person_data = json.load(f)

output_item = {
    "graph": graph_data,
    "person": person_data[:node_num]
}

# 输出实验配置文件
with open('case_lite.json', 'w') as f:
    json.dump(output_item, f, ensure_ascii=False)
```

输出结果为 `case_lite.json`：

```json
{
    "graph": {
        "directed": false,
        "multigraph": false,
        "graph": {},
        "nodes": [
            { "id": 0 },
            { "id": 1 },
            { "id": 2 }
        ],
        "links": [
            { "source": 0, "target": 1 },
            { "source": 0, "target": 2 },
            { "source": 1, "target": 2 }
        ]
    },
    "person": [
        {
            "general": "一名居住在农村社区的 55 岁保守派白人男性。",
            "character": "1) 虔诚的基督徒，认为宗教信仰非常重要。支持宗教在公共生活中发挥更大作用，认为政府政策应支持宗教价值观。\n 2) 关注政府和公共事务，希望减少政府在社会中的作用，对堕胎和同性婚姻持限制性观点，认为同性婚姻合法化对国家有害，认为白人并未因种族在社会中获得优势，并且更容易认为如今白人面临严重歧视。\n 3) 认为强大的国家军事力量在国际事务中至关重要，保障和平的最佳方式是军事实力而非外交。支持军事扩张。",
            "issue": "a) 认为本国是世界上最强大的国家。\n b) 将非法移民视为非常严重的国家问题。\n c) 认为政府应减少对弱势群体的公共援助。\n d) 认为参与宗教活动的人口比例下降对社会不利。\n e) 支持允许城镇在公共财产上设置宗教标志。\n f) 认为保守派无法自由表达观点。"
        },
        {
            "general": "一名 50 岁以上、经济状况稳定且受过良好教育的白人男性。",
            "character": "1) 持亲商观点，对国际贸易态度积极，主张限制政府作用。在国际关系上重视与美国盟友合作、维持美国军事实力，并在外交政策中考虑盟友利益。\n 2) 在移民和种族问题上立场较为温和，但总体保持保守态度。3) 积极参与政治活动。",
            "issue": "a) 认同国会共和党议员的行动。\n b) 认为政府对贫困人口的援助会导致对政府救济的过度依赖，弊大于利。\n c) 认为每个人都有能力靠自己取得成功。\n d) 部分认同疫苗是保护人们免受 COVID-19 影响的最佳方式。"
        },
        {
            "general": "一名居住在农村地区、收入和教育水平较低的白人女性。",
            "character": "1) 移民问题上的强硬派，对经济体制持批评态度，将非法移民视为非常严重的国家问题，认为应减少赴美合法移民，并认为白人在美国人口中的比例下降对社会有害。\n 2) 对政府和经济体制持批评与怀疑态度，主张提高大型企业的税收，认为娱乐业、科技公司和工会对国家发展产生了负面影响。",
            "issue": "a) 认为政府几乎总是低效且浪费资源。\n b) 认为政府过多干涉个人和企业事务。\n c) 认为非法移民经常使所在社区变得更糟。\n d) 认为本国经济体制不公平地偏袒强大的利益集团。\n e) 主张提高年收入超过 40 万美元家庭的税收。"
        }
    ]
}
```

整体仿真流程如下：

- 仿真分为 6 轮，每轮对应一部分辩论内容，包括以下事件：
  - 公开辩论（Public Debate）：智能体接收总统候选人的辩论信息，主要理解并记录候选人的发言和政策立场。每个智能体根据自身观点和偏好做出初步判断。
  - 讨论（Talk）：辩论结束后，智能体与其他选民讨论。这是智能体之间交流信息、碰撞观点的重要阶段。讨论主题可包括对辩论的看法、候选人政策或个人经历的分享。
  - 反思（Reflect）：讨论后，每个智能体进行自我反思，综合考虑讨论内容、对辩论的理解以及记忆中的信息。反思过程引入记忆机制，使智能体能够根据过去的经历和记忆调整对候选人的看法。
  - 投票（Vote）：每个智能体根据辩论、讨论和反思的结果做出投票决策。这一步是整个过程的最终输出，所有智能体的决策都体现在投票结果中。

### 4.2 初始化目录与文件

- 创建项目文件夹 `election_example`。
- 在项目文件夹中创建主要目录：
  - `content`：辩论内容文本，按轮次命名为 `1.txt, 2.txt, ...`。
  - `prompt`：所有提示词模板。
  - `log`：日志输出目录。
  - `memory`：记忆向量数据库目录。
- 创建主要项目文件：
  - `election_model.py`：仿真场景文件。
  - `election_agent.py`：智能体文件。
  - `baichuan.py`：大模型接口文件，本示例实现百川智能 API。
  - `run.py`：仿真入口。

*代码将在教程后续章节中补充。*

### 4.3 实现大模型接口文件

本示例接入[百川智能 API](https://platform.baichuan-ai.com/docs/api)，具体实现参见 [LLM_INTERFACE](#51-大模型接口llm_interfacepy-模块)。

### 4.4 创建智能体（`election_agent.py`）

#### 4.4.1 智能体初始化

使用 [casevo.AgentBase](#56-智能体基类-agentbaseagent_basepy) 初始化智能体，主要步骤包括：

- 初始化父类。
- 加载提示词。
- 设置思维链（CoT）。

```python
from casevo import AgentBase
from casevo import BaseStep, JsonStep
from casevo import TotLog
# 定义思维链中的步骤
class OpinionStep(BaseStep):
    def pre_process(self, input, agent=None, model=None):
        cur_input = input['input']
        cur_input['issue'] = input['last_response']
        return cur_input

class AgreeStep(JsonStep):
    def pre_process(self, input, agent=None, model=None):
        cur_input = input['input']
        cur_input['opinion'] = input['last_response']
        return cur_input

class ElectionAgent(AgentBase):
    def __init__(self, unique_id, model, description, context):
        # 初始化父类
        super().__init__(unique_id, model, description, context)
        # 加载提示词
        issue_prompt = self.model.prompt_factory.get_template("issue.txt")
        opinion_prompt = self.model.prompt_factory.get_template("opinion.txt")
        agree_prompt = self.model.prompt_factory.get_template("agree.txt")
        talk_prompt = self.model.prompt_factory.get_template("talk.txt")
        # 设置思维链
        issue_step = BaseStep(0, issue_prompt)
        opinion_step = OpinionStep(1, opinion_prompt)
        agree_step = AgreeStep(2, agree_prompt)
        talk_step = BaseStep(3, talk_prompt)
        chain_dict = {
            'listen': [issue_step, opinion_step, agree_step],
            'talk': [talk_step]
        }
        self.setup_chain(chain_dict)
```

#### 4.4.2 定义智能体行为函数

通过 `ElectionAgent` 类的成员函数定义智能体行为。利用思维链和多轮“输入—处理—输出”管理行为逻辑，决定智能体如何接收信息、处理信息、进行反思以及与其他智能体交互。

###### （1）**`listen`** 函数

- **功能**：模拟智能体倾听内容的行为。该函数接收候选人辩论或与其他智能体讨论的内容，通过思维链处理，并记录智能体的理解和反应。
  - 智能体将处理后的观点、赞同程度等内容存入记忆模块，并记录相关日志。

###### （2）**`talk`** 函数

- **功能**：实现智能体之间的对话行为。智能体根据听到的辩论信息、反思结果和长期记忆，与目标智能体交流观点。
  - 函数先通过思维链处理信息，再生成对话内容并记录日志。对话结束后，目标智能体将对话内容传入自身的 `listen` 函数，进行进一步处理。

###### （3）**`reflect`** 函数

- **功能**：智能体反思其长期观点并更新长期记忆。通过比较反思前后的观点变化，智能体能够学习并适应新信息，同时记录反思过程。

#### 4.4.3 定义智能体调度函数

通过重写 `casevo.AgentBase.step` 函数，实现模型对智能体的调度。本示例中，智能体以一定概率与邻域中的另一个智能体交互，通过 `talk` 函数进行对话和信息交流。

### 4.5 创建模型（`election_model.py`）

#### 4.5.1 模型初始化

使用 [casevo.ModelBase](#57-模型基类-modelbasemodel_basepy) 初始化模型，主要步骤包括：

- 初始化父类。
- 生成智能体并加入调度序列。

```python
from election_agent import ElectionAgent
from casevo import ModelBase
from casevo import TotLog

# 测试示例模型
class ElectionModel(ModelBase):

    # 根据配置生成模型
    def __init__(self, tar_graph, person_list, llm):
        """
        初始化对话系统中的每个人物及其对话过程。
        :param tar_graph: 表示对话系统结构的目标图。
        :param person_list: 包含所有对话参与者信息的人物列表。
        :param llm: 用于生成对话内容的语言模型。
        """
        super().__init__(tar_graph, llm)
        # 设置智能体
        for cur_id in range(len(person_list)):
            cur_person = person_list[cur_id]
            cur_agent = ElectionAgent(cur_id, self, cur_person, None)
            self.add_agent(cur_agent, cur_id)
```

#### 4.5.2 定义全局事件函数

通过 `ElectionModel` 类的成员函数定义全局事件。本示例包含以下两个全局函数：

###### （1）**`public_debate`** 函数

- **功能**：模拟公开辩论过程，让每个智能体倾听辩论内容，并将事件加入日志。

###### （2）**`reflect`** 函数

- **功能**：让所有智能体执行各自的 `reflect` 成员函数，进行反思。

#### 4.5.3 定义仿真入口函数

通过重写 `casevo.ModelBase.step` 函数，实现一轮仿真实验。本示例包括倾听辩论、智能体自由讨论以及形成观点。

```python
# 整体模型的 step 函数
    def step(self):
        # 倾听辩论内容
        self.public_debate()
        # 智能体自由讨论
        self.schedule.step()
        # 智能体反思
        self.reflect()
        return 0
```

### 4.6 编写仿真入口文件并运行（`run.py`）

编写仿真入口文件，主要功能包括：

- 初始化大模型接口。
- 读取仿真配置。
- 初始化模型。
- 每轮调用 `ElectionModel.step` 函数。

在命令行执行以下命令运行实验：

```cmd
python run.py case_lite.json 6
```

其中，`case_lite.json` 为配置文件，`6` 为仿真轮数。

补充说明：示例中需要将 `run.py` 中的 `API_KEY` 替换为有效的百川大模型 API_KEY。

### 4.7 分析结果

结果输出到 `log` 文件夹，包括以下文件：

- `agent_id.json`：对应 ID 的智能体事件日志，包含该智能体各阶段的观点变化。
- `event.json`：所有事件的日志。
- `model.json`：模型的全局事件日志。

## 5. 模块与 API 概览

### 5.1 大模型接口：`llm_interface.py` 模块

该模块定义用于与大语言模型（LLM）交互的接口基类，为接入不同的 LLM 实现提供标准化方法，便于扩展与集成。

#### 5.1.1 类：`LLM_INTERFACE`

这是一个**抽象基类**，定义与 LLM 交互所需的基本方法，子类必须**重写**这些方法。

- `send_message(prompt, json_flag=False)`：
  - **参数**：
    - `prompt`：发送给 LLM 的提示词文本。
    - `json_flag`：布尔值，表示返回数据是否应采用 JSON 格式，默认为 `False`。
  - **返回值**：LLM 对提示词的响应。
- `send_embedding(text_list)`：
  - **参数**：
    - `text_list`：需要生成嵌入向量的文本字符串列表。
  - **返回值**：与输入文本对应的嵌入向量。
- `get_lang_embedding()`：
  - **返回值**：用于生成 LangChain 嵌入向量的工具类实例。

### 5.2 提示词模板：Prompt + PromptFactory（`prompt.py`）

该模块定义生成和发送提示词信息的类，并集成模板渲染功能。

- 用途：
  - 使用模板定义提示词。
  - 使用 Jinja2 进行模板处理。
- 模型共享工厂类 PromptFactory：
  - 标准化 LLM 调用接口。
- 每个智能体使用自己的 `Prompt` 类。

#### 5.2.1 类：`Prompt`

负责提示词信息的生成与发送。

**属性**：

- `template`：提示词模板对象。
- `factory`：用于发送生成的提示词信息的工厂对象。

**方法**：

- `init(tar_template, tar_factory)`：初始化 `Prompt` 实例。通过传入模板和工厂参数，为后续操作准备必要属性。
  - **参数**：
    - `tar_template`：用于生成目标文件的模板对象，应具有特定的结构和规则，以指导目标文件的创建。
    - `tar_factory`：根据模板生成目标文件的工厂对象，应包含相应的方法与逻辑。
  - **返回值**：无。主要初始化实例属性。
- `get_prompt(tar_dict)`：使用给定字典渲染模板，生成提示词文本。
- `send_prompt(ertra=None, agent=None, model=None)`：根据给定参数生成并发送提示词消息。支持通过智能体和模型定制提示词内容，附加参数 `ertra` 可提供更多定制信息。
  - **参数**：
    - `ertra`：提供额外定制信息的附加参数，默认为 None。
    - `agent`：智能体对象；如提供，则使用其描述和上下文定制提示词消息。
    - `model`：模型对象；如提供，则使用其上下文定制提示词消息。
  - **返回值**：发送提示词消息后获得的响应结果。

#### 5.2.2 类：`PromptFactory`

管理提示词模板并生成 `Prompt` 对象。

**属性**：

- `prompt_folder`：模板文件夹路径。
- `env`：用于加载模板的 Jinja2 环境对象。
- `llm`：语言模型实例。

**方法**：

- `init(tar_folder, llm)`：初始化 `PromptFactory` 实例，设置模板文件夹路径和语言模型，并检查模板文件夹是否存在。
  - **参数**：
    - `tar_folder`：模板文件夹路径，必须是已存在的目录。
    - `llm`：用于自然语言处理的语言模型实例。
- `get_template(tar_temp)`：根据模板名称从指定文件夹获取模板文件。先构建模板文件完整路径，再检查文件是否存在。
  - 文件不存在时抛出异常。
  - 文件存在时，使用环境对象加载模板，并返回由该模板和当前对象初始化的 `Prompt` 对象。
  - **参数**：`tar_temp (str)`，模板文件名。
  - **返回值**：`Prompt` 对象。
  - **异常**：指定模板文件不存在时抛出 `Exception`。
- `send_message(prompt_text)`：将提示词文本发送给语言模型，并返回响应结果。

### 5.3 思维链：Step + ThoughtChain（`chain.py`）

该模块定义用于处理步骤的链式结构，包括基础步骤、选择步骤、评分步骤，以及执行这些步骤的 ThoughtChain 类。这些类可用于创建和管理复杂的交互过程。

用途：快速定义和调用思维链过程。

#### 5.3.1 步骤类：`BaseStep`

`BaseStep` 是所有步骤的**基类**，提供输入预处理、动作执行和后处理的基本方法。

- 构造函数：`def __init__(self, step_id, tar_prompt)`。
  - **参数**：
    - `step_id`：步骤的唯一标识符。
    - `tar_prompt`：需要用户回答的问题或提示词。
- **方法**：
  - `pre_process(input, agent=None, model=None)`：对输入数据进行**预处理**并返回处理后的数据。*目前直接返回输入，后续可随着功能扩展增加预处理步骤。*
    - **参数**：
      - `input`：需要预处理的输入数据。
      - `agent`：可选，用于特定预处理任务的智能体对象。
      - `model`：可选，用于特定预处理任务的模型对象。
    - **返回值**：处理后的输入数据。
  - `action(input, agent=None, model=None)`：根据输入和上下文执行具体动作。主要通过调用提示词模块的 `send_prompt` 方法，结合输入、智能体和模型信息发送提示词并获取响应，常用于对话系统生成回复。
    - **参数**：
      - `input (str)`：用户输入，作为生成响应的依据。
      - `agent (Agent, optional)`：用于传递上下文信息的智能体对象，默认为 None。
      - `model (Model, optional)`：用于处理输入和生成响应的模型对象，默认为 None。
    - **返回值**：生成的响应文本。
  - `after_process(input, response, agent=None, model=None)`：对话后的处理回调函数，以字典形式收集并返回输入和最终响应等关键信息。
    - **参数**：
      - `input`：用户原始输入，用于日志记录或后续处理。
      - `response`：机器人对用户输入的响应，用于分析或日志记录。
      - `agent`：智能体对象，通常用于访问对话管理相关功能；默认为 None，表示不使用。
      - `model`：模型对象，通常用于访问自然语言处理相关功能；默认为 None，表示不使用。
    - **返回值**：包含用户原始输入和系统最后生成的响应的字典。

#### 5.3.2 三种常见思维链步骤类型：选择、评分、JSON

1. **选择步骤类**：`ChoiceStep` 用于需要模型做出选择的交互步骤，增加了处理模型选择响应的逻辑。
2. **评分步骤类**：`ScoreStep` 根据给定的步骤 ID、目标提示词和评分模板，进行评估并生成评分响应。
3. **JSON 步骤类**：`JsonStep` 用于处理 JSON 格式的数据。

#### 5.3.3 思维链：`ThoughtChain`

该类继承 `BaseAgentComponent`，表示由一系列步骤组成的操作链。

- **构造函数**：`def __init__(self, agent, step_list)`。创建由多个步骤组成的操作链实例，在继承基类的基础上使用特定参数定制实例。
  - **参数**：
    - `agent`：负责执行链中步骤的智能体。
    - `step_list`：定义链的执行顺序和内容的步骤列表。
- **方法**：
  - `set_input(input)`：设置输入内容并更新状态。
  - `run_step()`：执行思维链中的步骤，依次调用步骤类的三个函数，并更新步骤历史与输出。
  - `get_output()`：获取输出内容，状态必须为 `finish`。
  - `get_history()`：获取步骤历史，状态必须为 `finish`。

### 5.4 模块执行逻辑

1. **定义大模型接口**：用户根据需求定制接口，确保能够发送和接收消息。
2. **定义提示词模板**：创建 Prompt 模板，包含发送给大模型的信息结构和格式。
3. **自动调用大模型接口**：设置 Prompt 模板后，系统可自动调用大模型接口生成适当响应。
4. **结合思维链步骤**：将生成的 Prompt 与思维链中的具体步骤结合，形成完整的思考过程。
5. **通过思维链调用大模型**：最终使用思维链逻辑调用大模型，完成信息处理和响应生成。

### 5.5 记忆机制：Memory + MemoryFactory（`memory.py`）

该模块实现智能体的记忆系统，管理短期记忆与长期记忆，并通过集成 ChromaDB 实现持久化。

- 用途：
  - 实现记忆机制。
  - 检索。
  - 反思。
- 共享工厂类 MemoryFactory：
  - 提供统一的 LLM 接口。
- 每个智能体拥有独立的 Memory 类。
- 所有记忆条目存储在向量数据库表中。
- RAG（检索增强生成）：
  - 背景信息（Background）。

#### 5.5.1 记忆元素：`MemoryItem` 类

表示单个记忆条目。

- **属性**：
  - `id`：记忆条目的唯一标识符，默认为 -1。
  - `ts`：时间戳。
  - `source`：来源智能体。
  - `target`：目标智能体。
  - `action`：事件类型。
  - `content`：记忆内容。
- **方法**：
  - `init(ts, source, target, action, content)`：初始化记忆条目。
  - `toDict()`：将记忆条目转换为字典。
  - `toList(memory_list, start_id)`：将记忆条目列表转换为内容、元数据和 ID 的列表。

#### 5.5.2 记忆模块：`Memory` 类

智能体的记忆模块，负责管理短期记忆与长期记忆。

- **方法**：
  - `__init__(component_id, agent, tar_factory)`：初始化 Memory 实例。
  - `add_short_memory(source, target, action, content, ts=None)`：向短期记忆添加一个记忆条目。
  - `search_short_memory_by_doc(content_list: List[str])`：根据文档内容列表检索短期记忆。
  - `reflect_memory()`：更新长期记忆并获取最新记忆 ID。
  - `get_long_memory()`：获取长期记忆。

#### 5.5.3 全局记忆工厂：`MemoryFactory` 类

全局记忆工厂模块，负责为智能体创建记忆实体并管理记忆存储。

- **方法**：
  - `__init__(tar_llm: LLM_INTERFACE, memory_num, prompt, model, tar_path=None)`：初始化记忆模块。
  - `create_memory(agent)`：为指定智能体创建 Memory 实例。
  - `add_short_memory(tar_memory: List[MemoryItem])`：向短期记忆添加目标记忆条目。
  - `search_short_memory_by_doc(content_list: List[str], tar_agent)`：根据内容检索短期记忆。
  - `reflect_memory(tar_agent, tar_pos, tar_long_opinion)`：对短期记忆进行反思，以更新长期记忆。

#### 5.5.4 外部记忆：`BackgroundItem/Background/BackgroundFactory` 类

处理外部记忆的 RAG 功能，设计参考 `MemoryItem/Memory/MemoryFactory` 类。

### 5.6 智能体基类 AgentBase（`agent_base.py`）

该模块定义智能体基类 `AgentBase`，为其他智能体类提供基本功能与结构。`AgentBase` 继承 `mesa.Agent`，负责初始化和管理智能体的基本属性与行为。

- **构造函数**：`def __init__(self, unique_id, model, description, context)`。
  - **参数**：
    - `unique_id`：智能体的唯一标识符。
    - `model`：智能体所在的模型环境。
    - `description`：智能体的人物设定描述。
    - `context`：智能体的上下文信息，用于生成提示词。
  - **功能**：
    - 调用父类初始化方法，设置智能体的唯一 ID 和模型。
    - 生成智能体专属的组件 ID。
    - 初始化日志对象，可选，用于记录智能体操作。
    - 设置智能体描述和上下文。
    - 使用模型的记忆工厂创建记忆对象，存储智能体状态信息。
- **方法**：
  - `setup_chain`：**初始化智能体的思维链集合。** 为给定字典中的每条思维链创建 `ThoughtChain` 实例，并存入 `self.chains`，供后续操作使用。
    - **参数**：`chain_dict (dict)`，包含思维链标识符和数据的字典。
    - **返回值**：None。
  - **抽象方法**：`step`。
    - 要求所有子类实现具体的智能体行为。
    - 可直接设置相应的思维链和调度函数，必须实现。

### 5.7 模型基类 ModelBase（`model_base.py`）

`model_base.py` 模块定义基于 Mesa 框架的模型类 `ModelBase`，继承 `mesa.Model`，用于创建和管理智能体模型。该模型支持网络结构、调度机制、记忆管理和提示词生成，主要功能包括：

- **网络设置**：使用 `NetworkGrid` 创建网络结构。
- **智能体调度**：通过 `RandomActivation` 调度器管理智能体活动。
- **上下文管理**：支持传递上下文信息。
- **提示词工厂**：集成提示词模板，便于与大模型接口交互。
- **记忆工厂**：管理短期记忆和长期记忆。

**属性**：

- `grid`：智能体的网络空间。
- `schedule`：智能体调度器。
- `context`：上下文信息。
- `llm`：语言模型。
- `prompt_factory`：生成提示词的提示词工厂。
- `memory_factory`：管理记忆条目的记忆工厂。
- `agent_list`：存储智能体对象的列表。

**方法**：

- `init(tar_graph, llm, context=None, prompt_path='./prompt/', memory_path=None, memory_num=10, reflect_file='reflect.txt')`：初始化模型及相关组件。
- `add_agent(tar_agent, node_id)`：向模型添加新智能体，并将其放在指定节点上。
  - **参数**：
    - `tar_agent`：要添加的智能体对象。
    - `node_id`：智能体所在节点的 ID。
- `step()`：执行一个仿真步骤，推进仿真时间并管理所有智能体活动。每次调用使仿真前进一步，更新所有被调度对象。该方法不接收参数，也不返回具有实质意义的值，主要用于推动仿真进程。
  - **返回值**：始终返回 0，表示步骤执行结果。

### 5.8 日志类 TotLog（`util/tot_log.py`）

`TotLog` 类用于**记录和管理日志数据**，支持将日志保存到文件以及管理时间偏移，提供添加日志、设置日志和将日志写入文件的功能。

## 6. 致谢

在 Casevo 的开发过程中，我们有幸得到一批优秀代码贡献者的支持。

- [Yafang Shi](https://github.com/Freya236)
- [Maoxu Li](https://github.com/limaoSure)
- [Hang Su](https://github.com/suhangha)
