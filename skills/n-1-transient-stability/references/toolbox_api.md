# N1AnalysisToolbox 应用层 API

本文根据当前项目 src/n_1analysis/n_1_analysis_toolbox.py 的公开方法整理。以下划线开头的方法是内部实现，不应从应用脚本调用。

导入：

    from n_1analysis import N1AnalysisToolbox

除 `set_config`、`get_runner_logs` 和三个静态判据方法外，各方法均要求先调用 `set_initial_conditions()` 获取模型，否则会在访问 `project` 时抛出 `AttributeError`。

## 1. 初始化与模型

### set_config

更新 CloudPSS 连接、模型标识和图形连线处理方式。

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| token | str 或 None | None | CloudPSS Token；设置后同步调用 cloudpss.setToken |
| api_url | str 或 None | None | CloudPSS API 地址；设置后写入 CLOUDPSS_API_URL |
| username | str 或 None | None | 模型所属用户名 |
| model | str 或 None | None | 算例名称，只传项目 key，不含 model/username 前缀 |
| delete_edges | bool 或 None | None | 初始化时是否将图形边转换为命名引脚连接 |

返回：None，配置写入 toolbox.config。

异常：字符串为空或类型不对时 ValueError；delete_edges 不是 bool 时 TypeError。

### set_initial_conditions

无参数。校验 token、api_url、username、model，拉取 model/{username}/{model}，并初始化 project、bus_keys、gen_keys、load_keys、acline_keys、trans_keys、initial_pf_setting 和输出通道索引。delete_edges 为 True 时还会刷新拓扑并删除 diagram-edge。

返回：None。

异常：配置缺失或模型/拓扑初始化失败时 RuntimeError。必须先调用 set_config。

### create_canvas

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| canvas | str | 必填 | 新画布 key |
| name | str | 必填 | 画布名称 |

返回：None。将画布加入当前模型并初始化自动布局。

异常：参数不是非空字符串时 ValueError。

### create_sa_canvas

无参数。确保 canvas_AutoSA_Fault（N-1 故障相关设置）和 canvas_AutoSA_ExtraOutput（N-1 分析所需输出通道）存在，并在故障画布中确保 model/CloudPSS/GND 元件存在。

返回：None。会编辑当前模型；需要先完成 set_initial_conditions。

## 2. 画布、元件与输出通道

### resolve_component_key

将用户提供的元件实例 key 或显示 label 统一解析为可用于模型操作的唯一 key。真实 key 优先；唯一 label 返回对应 key；重复 label 不替用户选择。

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| component_key | str | 必需 | 元件实例 key 或用户可见的 label |

返回：str，已确认存在且唯一的元件 key。

异常：输入不是非空字符串或 label 对应多个 key 时抛出 `ValueError`；重复 label 的异常消息会列出全部候选 key，请用户选择后重新传入。输入既不是有效 key 也不是已知 label 时抛出 `KeyError`；项目尚未初始化时抛出 `RuntimeError`。

### new_line_position

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| canvas | str | 必填 | 已初始化布局的画布 key |

返回：None。将自动布局游标移到下一行。画布未初始化时 ValueError。

### add_comp_in_canvas

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| definition | str | 必填 | 元件 RID |
| canvas | str | 必填 | 所在画布 key |
| args | dict | None | 元件参数 |
| pins | dict | None | 引脚映射 |
| label | str | None | 元件标签 |
| d_x | int | 10 | 添加后的额外横向间距 |
| max_x | float | None | 超过后自动换行的横坐标上限 |

返回：tuple[str, str]，为 CloudPSS 元件 id 和使用的 label。

副作用：向当前模型新增元件并推进布局。

### add_channel

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| pin_name | str | 必填 | 要量测的引脚名 |
| dim | int | 必填 | 通道维度，单值通常为 1 |
| channel_name | str | None | 通道显示名 |

返回：tuple[str, str]，为通道元件 id 和 label。相同 pin_name 会复用已有通道。

前置条件：create_sa_canvas 已初始化输出画布。

## 3. 计算方案与参数方案

### create_job

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| stype | str | emtps | 支持 emtp、emtps、power-flow、powerFlow |
| name | str | None | 方案名称；不填则使用模板名称 |
| args | dict | None | 对内置模板 args 的增量覆盖 |

返回：None。方法不做同名判重，重复调用会追加方案。

异常：不支持的 stype 时 ValueError；args 非 dict 时 TypeError。

### create_config

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| name | str | None | 参数方案名称 |
| args | dict | None | 参数配置增量覆盖 |
| pins | dict | None | 引脚配置增量覆盖 |

返回：None。方法不做同名判重。

### add_outputs

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| job_name | str | 必填 | 已创建的 EMTP/EMTPS 方案 |
| channels | dict | 必填 | 必须恰好包含 5 个键：图名、频率、图类型、图宽、通道 id 列表 |

返回：int，本组配置在 output_channels 中的零基索引。

异常：方案不存在、不是 EMTP/EMTPS 或 channels 键数不是 5 时 ValueError；channels 非 dict 时 TypeError。

## 4. 量测

### add_component_output_measures

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| job_name | str | 必填 | 仿真方案名称 |
| comp_rid | str | 必填 | 元件定义 RID |
| measured_key | str | 必填 | 元件 args 中的量测参数键，例如 Vrms、PT_o、wr_o、theta_o |
| conditions | list 或 dict | None | 参数筛选条件；支持 arg、Min、Max、Set |
| comp_list | list | None | 预筛选的元件 key 或 label |
| dim | int | 1 | 输出通道维度 |
| curve_name | str | None | 缺省时使用 measured_key |
| plot_name | str | None | 输出图名称 |
| freq | int | 200 | 输出采样频率 Hz |

返回：dict，包含 screenedComps（命中的元件 key 列表）和 output_index（追加的输出图配置索引）。

行为：对命中元件，将 args[measured_key] 作为输出引脚名；为空时生成 #标签.曲线名，再通过 add_channel 建立通道并追加 compressed 输出图。

异常：命中元件缺少 measured_key 时 KeyError；方案不存在或类型不符时 ValueError。

## 5. 故障与运行

### get_transmission_keys

无参数。返回全部传输元件 key 的拷贝，供批量场景构建与只读探查使用。

返回：dict，键为 `acline_keys`（交流线路 key 列表）和 `trans_keys`（变压器 key 列表），均为内部列表的拷贝。需要先 set_initial_conditions。

### generate_random_fault_params

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| seed | int 或 None | None | 随机种子；指定后使用独立随机源，不影响全局随机状态 |

从已初始化的 acline_keys 和 trans_keys 中随机选择候选；side 在 0/1 中随机，fault_start_time 固定 3.0，cut_time 为故障后 0.08~0.2 秒，fault_type 固定 7。

返回：dict，键为 transKey、side、fault_start_time、cut_time、fault_type。不修改模型；没有线路或变压器时 RuntimeError。

### set_n_1_ground_fault

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| trans_key | str | 必填 | 线路或变压器的实例 key 或显示 label；label 重复时抛 ValueError 并列出候选 key |
| side | float | 0.0 | 0 首端、1 末端、(0,1) 中间位置 |
| fault_start_time | float | 4.0 | 故障开始时间，必须 >= 0 |
| cut_time | float 或 list[float] | 4.06 | 切除时间；列表长度只能为 1 或 2 |
| fault_type_index | int | 7 | 0~7，7 为三相接地故障 |
| other_breaker_paras | dict | None | 覆盖断路器 Name、ctrlsignal、Init、Status |
| other_fault_paras | dict | None | 覆盖故障电阻 Init、chg、fct、I、V |

返回：dict，包含 result、解析后的 transKey、side、fault_start_time、cut_time、fault_type。

副作用：修改线路引脚，新增断路器、阶跃信号和接地故障；重复调用会叠加模型修改。

异常：side 越界、cut_time 格式错误或 trans_key 的 label 对应多个元件时 ValueError；trans_key 无法解析为元件时 KeyError。

### power_flow_sample_simple_random

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| flow_job_name | str | 必填 | 潮流计算方案名称 |
| flow_config_name | str | 必填 | 参数方案名称 |
| p_low | float | 1.0 | 发电机/负荷随机乘数下限 |
| p_high | float | 1.0 | 发电机/负荷随机乘数上限 |
| v_low | float | 1.0 | PV 发电机电压随机乘数下限 |
| v_high | float | 1.0 | PV 发电机电压随机乘数上限 |
| v_adjust_ratio | float | 0.1 | 调整 PV 电压的概率 |

返回：成功为 {status: success, P_low, P_high}；潮流不满足校验为 {status: failed, message}；异常为 {status: error, error_message}。详细潮流数据写入 toolbox.pf_result。

### run_project

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| job_name | str | 必填 | 运行的计算方案 |
| config_name | str | 必填 | 使用的参数方案 |
| show_logs | bool | False | 是否打印 runner 日志 |
| api_url | str | None | 本次运行覆盖 API 地址 |
| websocket_error_time | float | None | WebSocket 异常时的重跑阈值 |

返回：成功为 runner id 字符串；平台失败为 -1。运行器对象保存在 toolbox.runner。

副作用：提交远程仿真并阻塞轮询；启动异常最多重试 5 次。

### get_runner_logs

无参数。读取当前 toolbox.runner 的日志列表；尚未创建 runner 时返回空列表。

返回：list[dict[str, Any]]。

## 6. 结果、判据与文件

### plot_result

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| result | Any 或 str | None | 结果对象或 runner/result id；None 使用当前 runner.result |
| k | int | None | 结果图索引，None 等于 0 |
| html_path | str/PathLike | None | Plotly HTML 保存路径 |
| show | bool | True | 是否显示图形 |
| timestamp | str | None | 输出时间戳 |

返回：Plotly Figure 或 Matplotlib Axes；保存后路径写入 toolbox.last_plot_html_path。

### extract_and_check_data

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| job_name | str | 必填 | 用于读取 step_time 的计算方案 |
| timestamp | str | None | HTML 文件统一时间戳 |
| show_plots | bool | True | 是否显示图形 |

前置条件：toolbox.runner.result 至少包含四张图，顺序必须是母线电压、发电机功率、发电机转速、发电机功角。

返回：dict，包含 `voltage_ok`、`frequency_ok`、`power_angle_ok`、`plots`、`html_files`、`run_id`、`run_dir` 等字段。

四张图是量测输出，不等于四项检查：BusVoltage 用于电压检查，GeneratorSpeed 用于频率检查，GeneratorAngle 用于功角差检查；GeneratorPower 仅保存/展示，当前没有 `power_ok` 字段。

判据：电压低于 0.7 p.u. 持续至少 1.0 秒失败；频率（第 3 张图数据乘 50）必须在 49~51 Hz；任意两台机组功角差必须不超过 360 度。

### check_voltage

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| bus_voltage_data | numpy.ndarray | 必填 | 母线电压矩阵，形状为 [母线数, 采样点数]，单位 p.u. |
| step_time | float | 必填 | 仿真步长，单位秒 |

返回：bool。若任一母线电压低于 0.7 p.u. 且连续时间达到 1.0 s，返回 False，否则返回 True。

### check_frequency

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| frequency_data | numpy.ndarray | 必填 | 频率矩阵，形状为 [机组数, 采样点数]，单位 Hz |

返回：bool。所有采样值在 49~51 Hz（含边界）时返回 True。

### check_power_angle_diff

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| power_angle_data | numpy.ndarray | 必填 | 功角矩阵，形状为 [机组数, 采样点数]，单位度 |

返回：bool。任意两台机组的最大绝对功角差不超过 360 度时返回 True；机组数少于 2 时直接返回 True。

### save_flow_emt_hdf5

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| trans_id | str | 必填 | 实际故障元件 key |
| side | float | 必填 | 故障位置 |
| fault_start_time | float | 必填 | 故障开始时间 |
| cut_time | float 或 list | 必填 | 切除时间 |
| fault_type_index | int | 必填 | 故障类型 |
| P_low | float | 1.0 | 潮流随机乘数下限 |
| P_high | float | 1.0 | 潮流随机乘数上限 |
| timestamp | str | None | 统一文件时间戳 |
| save_path | str/PathLike | None | 本地结果根目录；应用脚本应显式传入。skill 示例缺省为脚本同级 `results/`，相对路径也相对脚本目录解析 |
| run_id | str | None | 本次运行标识；缺省自动生成 |

前置条件：pf_result 已存在，runner.result 至少四张图。

返回：包含 flow_url、emt_url、flow_status、run_id 和 run_dir。HDF5 文件位于 results/{project_key}/runs/{run_id}/data/。

文件数据集：潮流文件包含 P_low、P_high、pf_setting、bus_result、acline_result；暂态文件包含 initial_state、bus_voltage_data、power_data、frequency_data、power_angle_data。

工具箱负责使用传入的 `save_path` 创建独立的 `runs/{run_id}/` 目录；应用脚本必须显式解析结果根目录，不能依赖工具箱安装位置或当前工作目录。skill 示例默认使用脚本同级 `results/`，并允许用 `N1_SAVE_PATH` 或 `--save-path` 覆盖。

### save_analysis_result

将最终分析摘要保存为 analysis_result.json。必须先调用 extract_and_check_data()，并应在 save_flow_emt_hdf5() 后调用，以便摘要包含完整文件索引。

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| runner_id | str/int | 必填 | CloudPSS runner ID |
| cloudpss_model | str | 必填 | 完整模型 RID |
| fault | dict | 必填 | 实际故障参数和可选 fault_result |
| simulation | dict | 必填 | 暂态仿真参数 |
| power_flow | dict | 必填 | 潮流状态和采样参数 |
| artifacts | dict | 必填 | save_flow_emt_hdf5() 返回值及 HTML 路径 |
| timestamp | str | None | 运行时间戳 |
| save_path | str/PathLike | None | 本地结果根目录 |
| run_id | str | None | 复用指定运行目录 |

返回：可 JSON 序列化的摘要字典，包含 `schema_version=2`、run_id、created_at、project、runner、fault、simulation、power_flow、stability、overall_pass 和 artifacts。`stability` 只包含 `voltage_ok`、`frequency_ok`、`power_angle_ok` 三项；顶层 `overall_pass` 是这三项的逻辑与，不是第四项判据。旧版结果可能将 overall_pass 放在 stability 内，仅代表历史格式。

目录布局：

    results/{project_key}/runs/{run_id}/
    ├── analysis_result.json
    ├── data/flow_result.h5
    ├── data/emt_result.h5
    └── plots/BusVoltage_*.html
