---
name: sweep-frequency-analysis
description: 当用户需要在 CloudPSS 上执行电压或电流扫频分析（即频率扫描、阻抗频率特性测量）时使用：包括为评估次同步、宽频振荡或谐振风险而进行扫描，编写或修改扫频分析脚本，配置扫频仿真参数，以及基于已有扫频结果 JSON 重新评估谐振风险、重绘阻抗、相位、阻尼或奈奎斯特诊断图。不用于修改底层工具箱。
---

# 扫频分析

在用户工作区中先探查目标元件，再生成一次扫频分析的应用层脚本。脚本直接调用 `SweepAnalysisToolbox` 完成模型编辑、远程仿真、结果解析和保存，不复制工具箱实现。

## 资源使用

- 编写临时探查脚本或正式脚本前阅读 [SweepAnalysisToolbox API](references/toolbox_api.md)，以其中的方法签名、默认值和返回值为准。
- 阅读 [完整案例](examples/single_sweep_analysis.py) 掌握编排结构。案例以电压源为特定对象，不能把其中的元件 RID、有效值参数名或引脚当成其他元件的通用规则。
- 只有用户询问、校验或修改 `Mag`、频段、步长、驻留时间、相序等专业参数时，才阅读 [扫频模块参数指南](references/sweep_module_parameters.md)。普通标准扫频直接使用本文的标准案例参数。
- 普通扫频不要读取 [结果分析算法副本](references/result_analysis_algorithms.py)，也不要把其中代码复制到生成脚本；直接调用工具箱的 `parse_frequency_spectrum_result()`、`save_frequency_spectrum_result()` 和 `read_frequency_spectrum_plot_nyquist_file()`。只有用户明确要求理解、审查或修改频谱提取、结果保存、频谱图、阻尼系数、奈奎斯特曲线或谐振风险判定算法时，才读取该副本。
- 编写临时探查脚本和正式扫频脚本前，先将本技能 `assets/` 中的 `sweepanalysis-*.whl` 安装到用户工作区当前使用的 Python 环境：`python -m pip install "<wheel 文件路径>"`。动态定位 wheel，不假设本技能位于固定路径；安装失败时停止后续流程并报告错误。安装前确认该环境 Python 版本不低于 3.12；环境没有 pip（如未播种的 uv 虚拟环境）时改用 `uv pip install "<wheel 文件路径>"`，或先 `python -m ensurepip --upgrade` 再重试。
- 不使用已删除的 `sweep.py` 或旧模块 `SweepAnalysisToolbox.py`。

## 输入边界

通常只有连接信息来自环境变量：

- Token 优先读取 `SIMSTUDIO_TOKEN`，兼容 `CLOUDPSS_TOKEN`；
- API 地址读取 `CLOUDPSS_API_URL`，未设置时使用 `https://cloudpss.net/`。

生成可执行脚本或运行扫频时，用户必须明确提供：

| 参数 | 约束 |
| --- | --- |
| `cloudpss_model` | 完整路径，格式为 `model/{username}/{project_key}` |
| `component_key` | 扫频注入点处现有元件的实例 key |
| `injection_type` | 只允许 `V` 或 `I` |

`tested_pin` 不再是必填输入。优先通过下述元件探查确定；只有元件元数据存在多个合理候选、无法可靠判断注入端口时，才向用户列出候选引脚及含义并要求选择。不得静默使用`"0"`、`"1"` 等占位值。若用户主动给出 `tested_pin` 或 `voltage_name`，把它作为待验证候选，仍需用真实实例与元数据确认其存在且语义正确。

除派生参数和编排不变量外，用户可以覆盖任何公开 API 参数及传给 API 的配置字典字段。确认可配置面时查阅 API 文档，只传递已确认的键，不转发未知键。

## 已有结果的分析

用户已持有此前保存的频谱 JSON，只要求重新评估谐振风险或重绘诊断图时，走本节流程，不需要模型、元件或仿真：

- 跳过元件探查和正式扫频编排；业务输入只有频谱 JSON 路径（以及可选的输出目录）。
- 生成一个只读分析脚本：定义 `main(spectrum_json, html_dir=...)` 形式的显式输入，实例化 `SweepAnalysisToolbox()` 后调用 `read_frequency_spectrum_plot_nyquist_file(source=<json 路径>, show=False, html_dir=<输出目录>)`。该方法不访问网络，无需 Token；`show` 绑定到配置项，不得写死 `True`。
- 向用户报告 `resonance_risk` 结论和 `html_files` 中四张诊断图的路径；JSON 数据不满足字段要求时应保留底层校验错误。
- 不获取模型、不编辑远程内容、不提交仿真。静态校验器会自动按分析型模式检查这类脚本。

## 正式脚本前的元件探查

收到 `cloudpss_model` 和 `component_key` 后，先在用户工作区创建并运行一个独立的临时探查脚本；在完成探查前不要编写正式扫频脚本。该脚本只获取模型和元件元数据，不得编辑模型、创建画布、提交仿真或保存远程修改。

探查脚本必须：

1. 从模型路径拆分 `username` 和 `project_key`，用环境中的 Token、URL 配置工具箱，调用 `set_initial_conditions()` 获取模型。为避免探查阶段改变内存拓扑，显式设置 `delete_edges=False`。
2. 调用 `toolbox.project.getComponentByKey(component_key)`；找不到时停止并报告错误。
3. 读取 `target_component.definition` 得到该实例的元件 RID，再调用 `SweepAnalysisToolbox.fetch_comp_data([component_rid])` 获取元件定义详情。
4. 将足以判断元件的结构化信息输出为 JSON：实例 key、标签、RID、实例 `args`、实例 `pins`，以及 `fetch_comp_data()` 返回的名称、描述、标签、参数元数据、引脚元数据和 documentation。不得输出 Token。
5. 执行临时脚本，读取真实输出后再运用语义理解判断：元件类型（如电压源、风机、变流器）、表示额定或基准电压有效值的参数 key，以及适合接入扫频模块的引脚 key。

不能仅根据参数名中包含 `V` 或引脚序号作判断。结合元件名称、描述、参数说明、单位、引脚名称/描述、实例值和接线关系综合判断。选中的有效值参数必须存在于 `target_component.args`、能转换为数值，而且元数据语义和单位确实表示电压有效值；选中的引脚必须存在于 `target_component.pins`。如果证据不足或有多个等价候选，向用户说明候选及依据，不猜测。探查得到的 `voltage_name`、`tested_pin` 和元件类型应固化为正式脚本的已验证配置，并在运行前再次检查，不要让正式脚本再次依赖 LLM 判断。

完成正式脚本后删除临时探查脚本；若用户要求保留，则改为有意义的文件名并说明用途。临时探查会访问远程模型；只有用户只是询问概念而未要求生成脚本时才跳过。

## 扫频模块选择

由用户给出的 `injection_type` 选择，不能根据目标元件类型自行改变：

| `injection_type` | 扫频模块 RID | 标签建议 | `Mag` 单位 |
| --- | --- | --- | --- |
| `V` | `model/CloudPSS/Harmonic_continuous_injection_V` | `SA扫频模块_V` | V |
| `I` | `model/CloudPSS/Harmonic_continuous_injection_I` | `SA扫频模块_I` | A |

两个模块参数结构相同，但扰动幅值和标准频率方案不同。参数的专业含义、取值范围和调整建议在扫频模块参数指南中；模块选择和下列标准案例参数属于每次编排都需要的基础信息。

### 扫频模块引脚

电压注入模块和电流注入模块的引脚结构相同。`Pos`、`Neg` 是模块的两个电气接线端（均为 `3×1` 实数信号），不是结果输出端；编排时应按照工具箱的接线流程，将目标元件原有连接保存到 `Pos`，再将目标元件的待测引脚接到 `Neg`，不要把它们当作可记录的频谱通道。

模块提供以下 `1×1` 实数结果输出，应使用这些引脚配置结果通道：

| 引脚 | 含义 |
| --- | --- |
| `Freq` | 扰动频率 |
| `Z` | 总阻抗幅值 |
| `Zp` / `Zn` | 正边 / 负边阻抗幅值 |
| `Ph` | 总阻抗相位 |
| `Php` / `Phn` | 正边 / 负边阻抗相位 |

两种模块的结果引脚含义完全一致；差别仅在扰动注入量，`V` 模块的 `Mag` 使用 V，`I` 模块的 `Mag` 使用 A。除非用户明确要求改变输出内容，正式脚本应保留上述七个结果通道，并保持通道名称与结果解析约定一致。

## 标准案例参数

用户未明确调整扫频模块参数时，以探查确定的电压有效值参数 `target_component.args[voltage_name]` 计算基准电压，并使用以下完整字典。案例参数是编排基准，不代表对所有工程模型都最优；用户要求调整时再读取参数指南。

电压注入：

```python
base_voltage = float(target_component.args[voltage_name])
harmonic_args = {
    "Mag": base_voltage * np.sqrt(2 / 3) * 1000 * 0.03,
    "InitTime": 10,
    "RampTime": 1,
    "Sequence": 1,
    "InitVal1": 5,
    "EndVal1": 100,
    "DeltaStep1": 1,
    "DeltaTime1": 5,
    "InitVal2": 0,
    "EndVal2": 200,
    "DeltaStep2": 5,
    "DeltaTime2": 3,
    "InitVal3": 0,
    "EndVal3": 1000,
    "DeltaStep3": 10,
    "DeltaTime3": 1,
    "RampRatio": 0.2,
    "UnitTest": 0,
}
```

电流注入：

```python
base_voltage = float(target_component.args[voltage_name])
harmonic_args = {
    "Mag": 100 / base_voltage * np.sqrt(2) / 3 * 1000 * 0.03,
    "InitTime": 10,
    "RampTime": 1,
    "Sequence": 1,
    "InitVal1": 10,
    "EndVal1": 70,
    "DeltaStep1": 1,
    "DeltaTime1": 5,
    "InitVal2": 0,
    "EndVal2": 200,
    "DeltaStep2": 10,
    "DeltaTime2": 3,
    "InitVal3": 0,
    "EndVal3": 2000,
    "DeltaStep3": 20,
    "DeltaTime3": 1,
    "RampRatio": 0.2,
    "UnitTest": 0,
}
```

先复制对应注入类型的完整标准字典，再合并用户明确提供的专业参数覆盖项。保留一个数值类型的 `harmonic_args` 用于校验、时长计算和结果解析；仅在传给注入元件时把值转换为字符串。

## 参数所有权

- 用户输入：模型、目标元件、注入类型，以及用户主动覆盖的公开运行或专业参数。
- 探查结果：`component_rid`、元件类型、`voltage_name` 和 `tested_pin`；来自真实元数据及语义判断，歧义时由用户确认。
- 流程基准：用户未覆盖时采用上述标准案例参数以及完整案例中的计算、输出和保存设置。
- 派生参数：必须依据最终输入和上游状态计算，不能由用户独立指定或覆盖。

至少以下值属于派生参数：从模型路径拆分的 `username`、`project_key`；由注入类型选择的扫频模块 RID 和标签；由最终选定引脚构造的 `harmonic_pins`；实际添加或复用通道返回的 `output_channel_ids`；由最终 `harmonic_args` 计算的 `end_time`；以及各阶段真实产生的结果。

`end_time` 不能作为用户输入、环境变量或独立覆盖项。必须先完成 `harmonic_args` 合并和校验，再使用完整案例中的分段点数与驻留时间公式计算。频率边界、步长、驻留时间或 `InitTime` 变化后必须重算；固定值可能使仿真提前结束并产生不完整结果。

## 编排流程与不变量

使用同一个 `SweepAnalysisToolbox` 实例，按下表顺序生成正式脚本。本节说明每个阶段的目的、关键机制和产物；调用级代码以完整案例为准，不要改动下述机制。

前置事实：正式流程使用 `delete_edges=True`，`set_initial_conditions()` 获取模型时即把图形连线转换为命名引脚连接，后续接线全部通过引脚名完成（改为 `delete_edges=False` 前必须确认模型连接方式允许直接改接）。对模型的全部修改只存在于本次运行获取的内存副本中，`run_project()` 用该内存模型提交计算，不会回写云端工作区。

| # | 阶段 | 关键机制与不变量 | 阶段产物 |
| --- | --- | --- | --- |
| 1 | 校验并拆分模型路径 | 必须是 `model/{username}/{project_key}` 三段 | `username`、`project_key` |
| 2 | 获取模型 | `set_config` + `set_initial_conditions`；`delete_edges` 在此生效；再次校验探查得到的 `voltage_name`、`tested_pin` 真实存在 | 命名引脚化的内存模型 |
| 3 | 创建扫频画布 | `create_sweep_canvas` 幂等，已存在只重置布局 | 模块画布与输出画布 |
| 4 | 构造并校验 `harmonic_args` | 复制标准字典，合并用户覆盖项，按参数指南校验 | 数值型 `harmonic_args` |
| 5 | 接线并添加注入元件 | 见"接线机制" | 注入元件、`harmonic_pins` |
| 6 | 添加结果通道 | `add_channel` 按引脚名复用已有通道或新建，`dim=1`；`Pos`、`Neg` 是电气端不建通道；保留全部七个结果通道 | 真实返回的 `output_channel_ids` |
| 7 | 计算 `end_time` | 用最终 `harmonic_args` 按完整案例的分段点数与驻留时间公式重算，不得独立指定 | `end_time` |
| 8 | 创建方案与输出配置 | 只建一个 emtps 计算方案和一个参数方案，见"方案与输出配置" | job、config、输出配置 |
| 9 | 运行 | `run_project` 轮询至结束，返回 `-1` 即失败；成功后使用真实 `toolbox.runner.result` | `runner_id`、仿真结果 |
| 10 | 解析与保存 | 用同一 `harmonic_args` 解析；`sample_freq` 与输出配置中的采样频率同源；保存频谱时显式传入 `project_key`；同一流程统一时间戳 | 频谱 JSON、波形 HTML、四张诊断图、结构化结论 |

### 接线机制（最易错）

- `harmonic_pins` 的取值分三类：模块的七个结果输出引脚（`Freq`、`Z`、`Zn`、`Zp`、`Ph`、`Phn`、`Php`）绑定 `f"{harmonic_name}.{引脚}"`；`Pos` 绑定目标元件待测引脚**当前**的连接名，即保存原连接；`Neg` 绑定模块自身同名引脚，供下一步重定向。
- 两步顺序不可换：先构造 `harmonic_pins`（此时读入 `Pos` 的原连接名），再把待测引脚改绑到 `harmonic_pins["Neg"]`。若先改绑待测引脚，原连接名已被覆盖，`Pos` 将失去网侧参考——仿真仍会运行，结果静默错误。
- 注入元件以字符串参数字典（`component_args`）添加到模块画布；数值版 `harmonic_args` 保留给校验、`end_time` 计算和结果解析。
- 通道名与结果解析的通道识别约定（按通道名包含 `Zn`/`Zp`/`Z` 等识别）一致，不要另行命名。

### 方案与输出配置

- 计算方案只需一个 emtps 电磁暂态方案：`begin_time=0`，`end_time` 用阶段 7 的值。`step_time` 标准值 `5e-5`，对 2000 Hz 以内扰动约每周期 10 个采样点；用户可修改，智能体也可按最高关注频率自行调整，但应保持采样密度并向用户说明理由。`solver_option`、`n_cpu` 是可配置运行参数。扫频流程不需要潮流计算方案，不要创建。
- 参数方案使用默认空模板即可。
- `add_outputs` 五字段含义：输出图名（如"频率分析"）、采样频率（与解析 `sample_freq` 同源）、输出类型（"compressed"）、图像宽度、输出通道 ID 列表。
- 计算方案名和参数方案名在创建、添加输出、运行三处保持一致。

## 输出、安全与验证

标准输出包含频谱 JSON、原始波形 HTML、四张诊断 HTML，以及至少含 runner ID、 `harmonic_args`、频谱数据、保存路径和谐振风险的结构化返回值。

- 不硬编码、打印或复制 Token，不读取 `.env` 内容。
- 临时探查只读；正式脚本会在内存中修改获取的模型并提交远程计算（不回写云端工作区），产生计算成本。若用户仅要求生成脚本，完成探查后只做静态验证，不运行正式脚本。
- 不修改底层工具箱、远程模型库或 `src/sweepanalysis`，除非用户明确要求。
- 不复制工具箱源码，不写入技能安装路径，不用 `sys.path` 指向技能目录绕过依赖。
- 普通任务不得导入 `references/result_analysis_algorithms.py`。用户要求修改分析算法时，读取其中代码，识别采样窗口、通道约定、数据结构、绘图和风险判定之间的依赖，再按用户指定的范围实施修改。
- 元件、参数或引脚无法可靠识别时保留明确错误并向用户确认，不伪造结果。

完成后用 `compile()` 和 `scripts/validate_sweep_script.py` 静态检查，并确认正式脚本：

1. 业务输入不从环境变量读取；
2. 使用探查确认的 `voltage_name` 和 `tested_pin`，且运行前再次校验；
3. `end_time`、引脚映射、通道 ID 和结果对象均由最终配置或真实返回值产生；
4. 只有用户明确要求真实执行时才启动正式扫频仿真。

静态检查通过不保证指定模型、网络连接或远程服务一定可用。
