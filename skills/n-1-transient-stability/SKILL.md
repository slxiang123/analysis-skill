---
name: n-1-transient-stability
description: 当用户需要在 CloudPSS 上执行、编写或解释一次或批量 N-1 暂态稳定性分析时使用：包括为评估线路或变压器 N-1 故障后的暂态稳定（母线电压、机组频率、功角差）而设置故障与切除场景、运行潮流和电磁暂态仿真、生成或修改分析脚本，批量场景（随机采样多次、给定元件清单遍历、遍历全部线路/变压器的 N-1 扫描）的编排，以及基于已有 analysis_result.json、batch_result.json 或 HDF5 结果解读与离线复判稳定性。不适用于单独潮流计算、普通 EMTP 仿真、扫频分析或修改底层工具箱。
---

# N-1 暂态稳定性分析

在用户工作区中先探查目标模型与故障元件，再生成单次或批量 N-1 暂态稳定分析的应用层脚本。脚本直接调用 `n_1analysis` 包完成潮流采样、故障设置、暂态仿真、稳定性判别和结果保存（单次与批量编排的库实现均为 `n_1analysis.batch`），不复制工具箱实现。

## 资源使用

- 编写或修改流程前阅读 [N1AnalysisToolbox API](references/toolbox_api.md)，以公开方法签名、参数和返回值为准。
- 阅读 [完整案例](examples/single_n1_analysis.py) 掌握单次编排结构。案例中的量测元件 RID、量测参数名和故障元件是一个模型约定，不能未经探查套用到其他模型。
- 批量任务（多随机样本、给定元件清单、全元件 N-1 扫描）阅读 [批量 API](references/batch_api.md) 和 [批量案例](examples/batch_n1_analysis.py)：批量案例把单场景 12 阶段流程封装为 `run_scenario()` 函数后交给 `run_batch(scenario_runner=...)`，不要在应用脚本里手写场景循环，也不要在多个场景间共用工具箱实例。
- 只有用户询问判据阈值、结果布局、HDF5 数据集或结果解读细节时，才阅读 [结果布局与判据](references/result_analysis.md)。普通分析直接使用本文的紧凑判据。
- 普通分析不要读取 [结果分析算法副本](references/result_analysis_algorithms.py)，也不要把其中代码复制到生成脚本；直接调用工具箱的 `extract_and_check_data()` 和 `save_flow_emt_hdf5()`。只有用户明确要求自定义结果分析算法、修改稳定性判据、单位换算或 HDF5 布局时，才读取该副本。
- 使用已安装的 `n_1analysis` 包；不把技能目录加入 `sys.path`，不复制工具箱源码，不创建第二套故障或解析实现。
- 编写临时探查脚本和正式分析脚本前，先把 `assets/` 中的 `n_1analysis-*.whl` 安装到用户工作区当前使用的 Python 环境（需 Python ≥ 3.12）：`python -m pip install "<wheel 路径>"`，无 pip 的环境（如未播种的 uv 虚拟环境）改用 `uv pip install`。动态定位 wheel，不假设本技能位于固定路径；安装失败立即停止并报告错误。

## 输入边界

连接凭据只从环境变量读取：Token 优先 `SIMSTUDIO_TOKEN`、兼容 `CLOUDPSS_TOKEN`；API 地址 `CLOUDPSS_API_URL`，缺省 `https://cloudpss.net/`。

生成可执行脚本或运行分析时，用户必须明确提供：

| 参数 | 约束 |
| --- | --- |
| `cloudpss_model` | 完整路径，格式为 `model/{username}/{project_key}` |

故障五元组和运行参数为可选，未指定时按"参数所有权"处理：

| 参数 | 约束 |
| --- | --- |
| `trans_key` | 交流线路或变压器的实例 key 或显示 label；label 重复时需从报错列出的候选 key 中选择一个；省略时随机生成并须告知用户 |
| `side` | `0` 首端、`1` 末端、`(0,1)` 线路中间位置 |
| `fault_start_time` | 非负，单位秒 |
| `cut_time` | 不早于 `fault_start_time` 且不晚于 `end_time`；可传两个值分别切除两端 |
| `fault_type` | 0–7；7 为三相接地故障 |
| `end_time` / `step_time` / `sample_freq` | 正数 |

其他运行参数（`n_cpu`、`solver_option`、潮流采样区间 `p_low`/`p_high`/`v_low`/`v_high`、`v_adjust_ratio`、`show_logs`、`show_plots`）同样由用户显式覆盖，未覆盖时用案例默认值。批量任务还有：模式 `mode`（random/keys/all）、场景数 `count`、元件清单 `trans_keys`、随机种子 `seed`、后端 `backend`、并行数 `max_workers`、`stop_on_error`；`batch_id` 与每场景 `scenario_id` 始终为派生参数。除派生参数和编排不变量外，用户可以覆盖任何公开 API 参数；只传递已确认的键，不转发未知键。

## 已有结果的分析

用户已持有此前保存的结果、只要求解读结论或复判稳定性时，走本节流程，不需要模型和仿真：

- 只解读结论：直接读取 `analysis_result.json`（`stability` 三判据、顶层 `overall_pass`、`fault`、`artifacts` 文件路径）向用户报告；无需工具箱和网络。
- 离线复判：用 h5py 读取 `data/emt_result.h5` 的 `bus_voltage_data`、`frequency_data`、`power_angle_data`，调用 `N1AnalysisToolbox.check_voltage(data, step_time)`、`check_frequency(data)`、`check_power_angle_diff(data)` 重算三判据。数据集含义见 [结果布局与判据](references/result_analysis.md)。
- 不获取模型、不编辑远程内容、不提交仿真。静态校验器会自动按分析型模式检查这类脚本。

## 正式脚本前的模型探查

收到 `cloudpss_model` 后，先在用户工作区创建并运行一个独立的临时探查脚本；完成探查前不编写正式分析脚本。探查只获取模型和元件元数据，不得创建故障、修改参数、提交仿真或保存远程修改。

探查脚本必须：

1. 从模型路径拆分 `username` 和 `project_key`，用环境中的 Token、URL 配置工具箱并显式设置 `delete_edges=False`，调用 `set_initial_conditions()` 获取模型。
2. 用户指定 `trans_key` 时，先调用 `trans_key = toolbox.resolve_component_key(trans_key)` 统一解析 key/label；label 重复时停止，向用户列出异常中的候选 key 并请用户选择。解析后确认该 key 存在于初始化建立的 `acline_keys`/`trans_keys` 索引，再调用 `project.getComponentByKey()` 输出该元件的结构化信息（key、label、definition、args、pins），并确认具备引脚 `"0"` 和 `"1"`。
3. 未指定 `trans_key` 时，输出候选线路/变压器清单（key、label、definition）供用户选择；候选过多或有歧义时先询问，不随机猜测。
4. 需要更换量测对象时，同样探查目标元件定义，确认量测参数（如 `Vrms`、`PT_o`、`wr_o`、`theta_o`）在元件 `args` 中真实存在且语义正确。
5. 不得输出 Token。探查结论（`trans_key`、量测 RID 与参数）固化为正式脚本的已验证配置，运行前再次校验，不让正式脚本再次依赖 LLM 判断。

完成正式脚本后删除临时探查脚本；用户要求保留时改为有意义的文件名并说明用途。只有用户仅询问概念而未要求生成脚本时才跳过探查。

## 故障设置

`fault_type` 取值 0–7：0 不设故障，1–6 依次为 A/B/C/AB/BC/AC 接地，7 为 ABC 三相接地（标准案例默认）。`side` 为故障位置：0 首端、1 末端、(0,1) 中间（工具箱把线路按比例拆分成两段）。`cut_time` 可为标量（两端同时切除）或两个时间的列表（两端先后切除）。

`set_n_1_ground_fault()` 在故障元件上编排以下 CloudPSS 元件：

| 元件 RID | 用途 |
| --- | --- |
| `model/CloudPSS/_newBreaker_3p`（两个） | 串入元件两端，`cut_time` 时刻由 1→0 断开 |
| `model/CloudPSS/_newStepGen` | 驱动断路器的阶跃信号（`@Sig_Breaker_*`） |
| `model/CloudPSS/_newFaultResistor_3p` | 接地故障电阻：`fs`=故障开始、`fe`=结束（默认 99999 永久）、`ft`=故障类型 |
| `model/CloudPSS/GND` | 接地点（`create_sa_canvas()` 已确保存在） |

## 标准案例参数

标准参数以完整案例为单一来源：复制 `examples/single_n1_analysis.py` 的 `main()` 默认值——`end_time=30`、`step_time=0.00005`、`sample_freq=200`、`n_cpu=1`、`solver_option=0`；故障未指定时由 `generate_random_fault_params()` 生成 `fault_start_time=3.0`、`cut_time` 为其后 0.08~0.2 s 随机、`fault_type=7`；潮流采样 `p_low=p_high=v_low=v_high=1`、`v_adjust_ratio=0.1`。再合并用户明确提供的覆盖项。案例参数是编排基准，不代表对所有工程模型都最优；用户要求调整时说明依据。

## 参数所有权

- 用户输入：模型、故障五元组及用户主动覆盖的运行/专业参数。
- 随机回退：用户未指定的故障参数由 `generate_random_fault_params()` 生成，生成结果视为本次分析的显式配置，执行前打印/返回告知用户；不得静默把 0、1 或不存在的元件当作故障对象。
- 流程基准：用户未覆盖时采用完整案例默认值以及其中的计算、输出和保存设置。
- 派生参数：必须依据最终输入和上游状态产生，不能由用户独立指定或覆盖。

至少以下值属于派生参数：从模型路径拆分的 `username`、`project_key`；方案名（`SA_电磁暂态仿真`、`SA_潮流计算`、`SA_参数方案`）；`run_id` 与 `run_dir`；批量时的 `batch_id`、每场景 `scenario_id` 与 `run_id`（`{batch_id}__{scenario_id}`）；各保存方法真实返回的文件路径；三判据结果与 `overall_pass`。

## 编排流程与不变量

单次脚本把下表 12 个阶段封装为一个 `run_scenario(cloudpss_model, scenario, ...)` 函数（以完整案例为准），在函数内部使用一个全新 `N1AnalysisToolbox` 实例按顺序执行；批量脚本复用同一函数形状，作为 `run_batch(scenario_runner=...)` 的场景函数逐场景调用。本节说明每个阶段的目的、关键机制和产物；不要改动下述机制。

前置事实：正式流程使用 `delete_edges=True`，`set_initial_conditions()` 获取模型时即把图形连线转换为命名引脚连接，后续接线通过引脚名完成。对模型的全部修改只存在于本次运行获取的内存副本中，`run_project()` 用该内存模型提交计算，不会回写云端工作区。

| # | 阶段 | 关键机制与不变量 | 阶段产物 |
| --- | --- | --- | --- |
| 1 | 校验并拆分模型路径 | 必须是 `model/{username}/{project_key}` 三段 | `username`、`project_key` |
| 2 | 获取模型 | `set_config(delete_edges=True)` + `set_initial_conditions()`；再次校验探查确认的 `trans_key` 与量测参数真实存在 | 命名引脚化的内存模型、元件索引 |
| 3 | 创建分析画布 | `create_sa_canvas` 幂等，并确保 GND 元件存在 | 故障画布与输出画布 |
| 4 | 创建/复用方案 | 先 `getModelJob`/`getModelConfig` 查重再创建；潮流 power-flow、emtps 暂态、参数方案各一 | 三个方案名 |
| 5 | 潮流采样 | `power_flow_sample_simple_random`；仅 `status=="success"` 继续，失败保留原因并停止 | `pf_result` |
| 6 | 确定故障参数 | 用户输入优先，缺失项随机回退并告知；逐项校验区间 | `fault_params` |
| 7 | 设置故障 | `set_n_1_ground_fault` 恰好一次，机制见"故障设置机制" | `fault_result`（解析后参数） |
| 8 | 配置暂态方案 | 更新 emtps 方案的 `end_time`/`step_time`/`n_cpu`/`solver_option`，`output_channels=[]` | 暂态方案 |
| 9 | 添加四类量测 | 按"方案与量测配置"的固定顺序；`freq=sample_freq`；`screenedComps` 为空即报错 | 量测结果与通道 |
| 10 | 运行 | `run_project` 轮询至结束，返回 `-1` 即失败；使用真实 `toolbox.runner.result` | `runner_id` |
| 11 | 判稳与保存 | `extract_and_check_data` → `save_flow_emt_hdf5` → `save_analysis_result`；统一时间戳 | JSON + 两 HDF5 + 四 HTML |

### 故障设置机制（最易错）

- `set_n_1_ground_fault()` 把故障元件两端引脚重命名为新引脚名，再在每端串入三相断路器；断路器由阶跃信号驱动，在 `cut_time` 时刻从 1→0 跳变实现切除。元件本身不删除。
- `cut_time` 为标量时两端同时切除；为两元素列表时按 `@Sig_Breaker_*1`/`*2` 两个信号先后切除；其他格式抛 `ValueError`。
- 接地故障为永久故障：`fe` 默认 99999（环境变量 `PSAT_FAULT_PERMANENT_END_TIME`），故障持续到仿真结束，只靠断路器切除元件来隔离。
- `side` 在 (0,1) 开区间时，工具箱深拷贝该线路并按 `side`/`1-side` 拆分长度，在拆分点接入故障，两端 `ModelType`/`Decoupled` 置 0。
- 该方法只能对当前模型调用一次：重复调用会叠加断路器、故障元件和线路拆分，无法自动撤销。潮流采样必须先于故障设置完成。
- 保存时 `save_flow_emt_hdf5` 的 `trans_id` 使用解析后的实际元件 key（`fault_result["transKey"]`）。

### 方案与量测配置

- 方案名在创建、运行、解析、保存各阶段保持一致：`SA_电磁暂态仿真`（emtps）、`SA_潮流计算`（power-flow）、`SA_参数方案`。先查后建，避免同名追加。
- 四类量测按固定顺序添加，顺序与 `extract_and_check_data` 的解析严格对应：

| 顺序 | 图名 | 元件 RID | 量测参数 | 判据用途 |
| --- | --- | --- | --- | --- |
| 1 | `BusVoltage` | `model/CloudPSS/_newBus_3p` | `Vrms` | 电压判据 |
| 2 | `GeneratorPower` | `model/CloudPSS/SyncGeneratorRouter` | `PT_o` | 仅展示/保存 |
| 3 | `GeneratorSpeed` | `model/CloudPSS/SyncGeneratorRouter` | `wr_o` | 频率判据（×50 转 Hz） |
| 4 | `GeneratorAngle` | `model/CloudPSS/SyncGeneratorRouter` | `theta_o` | 功角差判据 |

- 这些 RID 与参数必须在目标模型中真实存在；模型不同时先探查替换为语义等价对象，保持顺序不变。`add_component_output_measures` 返回的 `screenedComps` 为空必须报错，不伪造通道。
- 三项判据对应结果字段 `voltage_ok`、`frequency_ok`、`power_angle_ok`：任一母线电压低于 0.7 p.u. 持续 1.0 s 不通过；任一频率采样点超出 49~51 Hz 不通过；任意两机组同一时刻功角差超过 360° 不通过（少于两台机组通过）。没有第四项功率判据，结果中不得虚构 `power_ok` 字段；`overall_pass` 是三判据的逻辑与，作为同级字段存放于 `stability` 之外。

## 批量 N-1 分析

以下情况走批量而不是逐个生成单次脚本：遍历全部传输元件做 N-1 扫描、用户给出元件清单依次校核、需要多组随机故障样本做统计。批量编排由库层 `n_1analysis.batch` 提供，应用脚本只做参数组装与调用，不要手写场景循环或复用工具箱实例。

### 场景构建（build_scenarios）

先用只读探查实例（`delete_edges=False` + `set_initial_conditions()`，与"正式脚本前的模型探查"同一约束）构建场景清单，三种模式：

| 模式 | 输入 | 场景来源 |
| --- | --- | --- |
| `random` | `count`（必填，≥1）、可选 `seed` | 每场景随机选故障元件；给 `seed` 时元件在构建期预采样，清单可审计且可复现 |
| `keys` | `trans_keys` 列表（必填） | 逐项遍历；元素为 key/label 字符串或 `{"trans_key": ..., "side": ...}` 覆盖字典 |
| `all` | 无 | 遍历 `get_transmission_keys()` 返回的全部交流线路与变压器 |

故障参数合并顺序：逐项覆盖 > `defaults`（全列表共用）> 模式默认。keys/all 模式未指定时全列表共用 `side=0`、`fault_start_time=3.0`、`cut_time=3.1`、`fault_type=7`；random 模式留空项在每场景运行时随机回退并打印告知。用户对某些元件有特殊故障要求时，把覆盖字典与 key 列表一同构建迭代项传入，不要为个别元件单独跑单次脚本混用结果。

### 执行与隔离（run_batch + 应用层场景函数）

- **场景函数**：批量脚本内置 `run_scenario(cloudpss_model, scenario, *, token, api_url, run_id, save_path, seed, **仿真参数)` 函数（与单次示例同形状，契约见批量 API），`run_batch` 通过 `scenario_runner` 参数调用它并用 `runner_kwargs` 透传仿真参数；换模型需要调整量测 RID 等约定时改的是脚本内这个函数，不动工具箱。
- **场景隔离不变量（最关键）**：每个场景都必须在全新 `N1AnalysisToolbox` 实例上执行——`set_n_1_ground_fault()` 对单次模型拉取只能调用一次且不可撤销，运行目录也按实例记忆。场景函数在内部新建实例并重新拉取模型，天然满足隔离；应用层绝不能把一个实例传给多个场景，也不能把探查实例复用于执行。
- 后端：默认 `sequential` 顺序循环，最稳；`ray` 为可选并行后端（需 `pip install "n_1analysis[batch]"`），未安装或 `ray.init` 失败时自动回退顺序并打印警告。`max_workers` 默认 2——CloudPSS 对单 Token 的并发作业配额未知，未与平台确认前不要调大。Windows 上 Ray 依赖 VC++ 运行库且 worker 启动慢，大规模批量建议 WSL/Linux。
- 错误隔离：单场景失败默认记录为 failed 记录后继续（含 error/error_type 和用时），批末汇总；`stop_on_error=True` 时先保存部分汇总再抛错终止。
- 潮流基态一致性：默认采样区间全 1.0 时各场景基态一致；放宽区间后各场景独立随机采样，跨场景比较结论时应保持区间为 1。
- 随机可复现：仅显式给 `seed` 时保证（random 模式元件预采样 + 每场景 seed+i）。

### 批量输出

每场景产物与单次运行同构，位于 `results/{project_key}/runs/{batch_id}__{scenario_id}/`（`analysis_result.json` 的 schema 与判稳逻辑不变）；批次索引位于 `results/{project_key}/batches/{batch_id}/`，含 `batch_result.json`（全量汇总，含每场景故障参数、三判据、`overall_pass`、错误信息与 summary 计数）、`batch_summary.csv`（平面表格）和 `scenarios.json`（运行前场景清单快照）。解读批量结论时先读 `batch_result.json` 的 `summary` 与 `scenarios` 记录，再按需进入单场景目录复判。

## 运行与日志跟踪

正式脚本运行时间较长（标准参数下模拟 30 s、步长 5e-5 s，实际耗时取决于平台），必须以后台任务运行并把输出实时写入日志文件：

- 完整案例在 `main()` 开头对 stdout/stderr 启用行缓冲（`reconfigure(line_buffering=True)`），生成脚本必须保留。输出重定向到文件时 Python 默认按块缓冲，不做此设置日志会长时间不落盘；等效做法是用 `python -u` 启动。
- 标准启动模式：

  ```bash
  cd <工作区> && nohup python3 <脚本>.py --cloudpss-model <模型路径> \
    [--trans-key <元件key> --side <0|1|小数> --fault-type <0-7>] \
    > n1_<元件key或auto>.log 2>&1 & echo "PID=$!"
  ```

- 启动后等待约 20 秒并查看日志开头（`sleep 20; head -40 <日志>`）：缺 Token、模型路径格式错误、故障元件未找到等立即失败都会在前几行暴露。跟踪进度用 `tail -f`，进度行约每 10 秒输出一次。
- 正常结束以日志末尾出现"=== N-1 分析流程完成 ==="标记为准，随后从日志读取稳定性三判据和结果文件路径；需要中止时 `kill <PID>`。
- 批量脚本同样后台运行，场景进度行带 `[batch {batch_id}] (i/n)` 与 `[N-1][{scenario_id}]` 前缀；正常结束以"=== N-1 批量分析流程完成 ==="标记为准，随后从 `batches/{batch_id}/batch_result.json` 读取汇总。批量耗时 ≈ 场景数 × 单场景耗时（顺序后端），估算后再启动。

## 输出、安全与验证

标准输出包含 `analysis_result.json`、`data/flow_result.h5`、`data/emt_result.h5`、`plots/` 下四张 HTML，以及包含 runner ID、故障参数、潮流结果、三判据和文件路径的结构化返回值。每次运行使用独立目录 `results/{project_key}/runs/{run_id}/`。批量运行额外在 `results/{project_key}/batches/{batch_id}/` 写入批次汇总（`batch_result.json`、`batch_summary.csv`、`scenarios.json`），每场景仍占用一个 `runs/{batch_id}__{scenario_id}/` 目录。

- 不硬编码、打印或复制 Token，不读取 `.env` 内容。
- 临时探查只读；正式脚本会在内存中修改获取的模型并提交远程计算（不回写云端工作区），产生计算成本。用户仅要求生成脚本时，完成探查后只做静态验证，不运行正式脚本。
- 不修改底层工具箱、远程模型库或 `src/n_1analysis`，除非用户明确要求。
- 不复制工具箱源码，不写入技能安装路径，不用 `sys.path` 指向技能目录绕过依赖。
- 普通任务不得导入 `references/result_analysis_algorithms.py`。用户要求修改分析算法时，读取其中代码并结合源码核对，按用户指定范围实施修改。
- 元件、参数或引脚无法可靠识别时保留明确错误并向用户确认，不伪造结果。

完成后用 `compile()` 和 `scripts/validate_n1_script.py` 静态检查；校验器规则与本文各节不变量一致，未通过先修复再重验。静态检查通过不保证指定模型、网络或远程服务一定可用。
