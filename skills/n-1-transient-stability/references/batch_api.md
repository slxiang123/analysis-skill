# 批量 N-1 分析 API

本文根据 `src/n_1analysis/batch.py` 的公开函数整理。本模块只提供批量域能力（场景构建、批量执行与隔离、汇总保存）；单场景 12 阶段流程属于应用层编排，在 `demo_n1.run_scenario` 与 skill 示例中以同形状的 `run_scenario()` 函数实现，量测 RID、方案名等模型相关约定可在各脚本内按探查结果调整，再通过 `scenario_runner` 参数注入 `run_batch`。

导入：

    from n_1analysis.batch import ScenarioSpec, build_scenarios, run_batch, save_batch_result

## ScenarioSpec

单个 N-1 场景的故障设定（frozen dataclass），也是场景函数的输入契约。

| 字段 | 类型 | 说明 |
|---|---|---|
| scenario_id | str | 场景编号（build_scenarios 自动生成 s0000 起） |
| label | str | 人类可读标签（元件 key/label 或 random-N） |
| trans_key | str 或 None | 故障元件 key/label；None 表示运行时随机回退 |
| side | float 或 None | 故障位置；None 表示运行时随机回退 |
| fault_start_time | float 或 None | 故障开始时间；None 表示运行时随机回退 |
| cut_time | float 或 None | 切除时间；None 表示运行时随机回退 |
| fault_type | int 或 None | 故障类型 0–7；None 表示运行时随机回退 |

### build_scenarios

按指定模式构建场景清单，只读探查、不修改模型。

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| mode | str | 必填 | random（count 组随机故障）、keys（遍历给定元件列表）、all（遍历全部交流线路与变压器） |
| toolbox | N1AnalysisToolbox | 必填（关键字） | 已完成 set_initial_conditions() 的只读探查实例（delete_edges=False），仅用于元件索引与 label 解析，不得复用于执行 |
| count | int 或 None | None | random 模式必填，>= 1 |
| trans_keys | list[str 或 dict] 或 None | None | keys 模式必填；元素为 key/label 字符串或逐项覆盖字典（必须含非空 trans_key，可选 side、fault_start_time、cut_time、fault_type） |
| defaults | dict 或 None | None | 全列表共用的默认故障参数（键同上，不含 trans_key） |
| seed | int 或 None | None | random 模式给定时预采样故障元件（独立随机源，可能重复），保证运行前可审计元件清单 |

故障字段取值合并顺序：逐项覆盖 > defaults > 模式默认。keys/all 模式默认 `side=0.0`、`fault_start_time=3.0`、`cut_time=3.1`、`fault_type=7`；random 模式默认留空（运行时随机回退）。

返回：list[ScenarioSpec]，按顺序编号。

异常：模式参数缺失/非法、覆盖字段未知或越界时 ValueError；元素类型错误时 TypeError；模型没有交流线路或变压器时 RuntimeError（random/all）；key/label 无法解析时沿用 resolve_component_key 的 ValueError/KeyError。

### run_batch

批量执行 N-1 场景并保存汇总结果。单场景异常默认收敛为 failed 记录后继续，stop_on_error 为真时先保存部分汇总再抛出。给定 seed 时第 i 个场景以 seed + i 作为 seed 参数传给场景函数。

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| cloudpss_model | str | 必填 | model/{username}/{project_key} |
| scenarios | list[ScenarioSpec] | 必填 | 非空且 scenario_id 不重复 |
| scenario_runner | Callable | 必填（关键字） | 应用层单场景函数，契约见下 |
| token | str 或 None | None | 透传给每个场景；None 时各场景自行读环境 |
| api_url | str 或 None | None | 透传给每个场景 |
| runner_kwargs | dict 或 None | None | 仿真参数（end_time 等），原样透传给每个场景调用；不得与场景函数的保留关键字重名 |
| backend | str | sequential | sequential 顺序循环；ray 并行（需安装 n-1analysis[batch]，未安装或 ray.init 失败自动回退顺序并打印警告） |
| max_workers | int | 2 | ray 后端的并行任务数；CloudPSS 对单 Token 的并发作业配额未知，未与平台确认前不要调大 |
| stop_on_error | bool | False | True 时首个失败场景后保存部分汇总并抛 RuntimeError；ray 后端要等全部任务返回后才检查 |
| batch_id | str 或 None | None | 批次标识；缺省 {时间戳}_{8位uuid}，只能含字母/数字/下划线/连字符/点 |
| save_path | str/PathLike 或 None | None | 本地结果根目录；应用脚本应显式解析，skill 示例默认使用脚本同级 `results/` |
| seed | int 或 None | None | 第 i 个场景使用 seed + i |

**场景函数契约**（见 `demo_n1.run_scenario` 与 skill 示例的实现）：

- 签名：`scenario_runner(cloudpss_model, scenario, *, token, api_url, run_id, save_path, seed, **runner_kwargs)`。run_batch 按关键字传入全部保留参数与 runner_kwargs。
- 隔离不变量：函数内部必须新建 `N1AnalysisToolbox` 实例执行 12 阶段流程（故障设置对单次模型拉取一次性生效，实例间绝不共享状态），并把 `run_id`/`save_path` 透传给三个保存方法，使每场景产物落在传入结果根目录下的 `{project_key}/runs/{run_id}/`。
- 返回 dict 约定键：`fault_params`（实际故障五元组）、`stability_result`（含 voltage_ok、frequency_ok、power_angle_ok）、`saved_files`（含 analysis_json）、`run_id`、`run_dir`、`runner_id`；缺失的键按空值记入批次汇总。

返回：dict（batch_result），包含 `schema_version=1`、`batch_id`、`created_at`、`project`（model/project_key）、`config`（backend/max_workers/stop_on_error/seed/scenario_count/runner_kwargs）、`scenarios`（每场景记录，含 scenario_id、label、status、fault_params、runner_id、run_id、run_dir、analysis_json、stability 三判据、overall_pass、elapsed_seconds、error、error_type）、`summary`（total/succeeded/failed/passed/failed_stability）、`elapsed_seconds` 和 `artifacts`。config.backend 记录实际生效的后端（可能已从 ray 回退为 sequential）。

异常：场景清单为空、scenario_id 重复、runner_kwargs 与保留关键字冲突或后端参数非法时 ValueError；stop_on_error 为真且存在失败场景时 RuntimeError。

注意：ray 后端在 Windows 上依赖 VC++ 运行库且 worker 启动较慢，大规模批量建议在 WSL/Linux 中运行；未安装 ray 时自动回退顺序执行。ray 后端下场景函数由 cloudpickle 按值序列化到 worker，定义在脚本顶层即可。

### save_batch_result

将批量汇总写入 results/{project_key}/batches/{batch_id}/，通常由 run_batch 自动调用。

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| batch_result | dict | 必填 | run_batch 组装的汇总字典 |
| scenario_specs | list[ScenarioSpec] 或 None | None（关键字） | 提供时额外写入 scenarios.json（运行前场景清单审计快照） |
| save_path | str/PathLike 或 None | None（关键字） | 本地结果根目录；由应用脚本解析后传入 |

返回：dict，包含 `batch_dir`、`batch_json`、`batch_csv`，提供 scenario_specs 时另含 `scenarios_json`。

## 批量输出布局

每场景产物与单次运行同构（analysis_result.json 的 schema_version=2 不变），批次索引独立存放：

    results/{project_key}/runs/{batch_id}__{scenario_id}/
    ├── analysis_result.json
    ├── data/flow_result.h5
    ├── data/emt_result.h5
    └── plots/*.html
    results/{project_key}/batches/{batch_id}/
    ├── batch_result.json      # 全量汇总（schema_version=1）
    ├── batch_summary.csv      # 平面表格（utf-8-sig，含 error_type/error 列）
    └── scenarios.json         # 运行前场景清单审计快照

批量完成标记：`=== N-1 批量分析流程完成 ===` 由调用方脚本在 `run_batch` 正常返回后打印（`run_batch` 自身不打印；单次标记 `=== N-1 分析流程完成 ===` 同理由单次脚本打印）。

## 说明与限制

- 潮流基态一致性：默认 p/v 采样区间全为 1.0 时各场景潮流基态一致（采样乘数恒为 1）；放宽区间后各场景基态按设计独立随机，如需跨场景共享同一基态应保持区间为 1。
- random 模式可复现性：仅在显式给定 seed 时保证（元件预采样 + 每场景 seed+i）；ray 后端未给 seed 时采样顺序取决于 worker 调度。
- 跨场景共享 HDF5 追加（工具箱 is_batch_mode）当前未启用，批量聚合以 batch_result.json / batch_summary.csv 为准。
