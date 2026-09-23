# 结果布局与稳定性判据

仅在用户询问判据阈值、结果布局或 HDF5 数据集细节时需要阅读本文；普通分析使用 SKILL.md 中的紧凑判据即可。

## 四张暂态图

当前工具箱按 runner.result.getPlots() 的索引读取数据：

| 索引 | demo_n1.py 中的图名 | 量测元件 RID | 量测参数 | 单位/转换 |
|---|---|---|---|---|
| 0 | BusVoltage | model/CloudPSS/_newBus_3p | Vrms | p.u. |
| 1 | GeneratorPower | model/CloudPSS/SyncGeneratorRouter | PT_o | 模型输出单位 |
| 2 | GeneratorSpeed | model/CloudPSS/SyncGeneratorRouter | wr_o | 乘以 50 转为 Hz |
| 3 | GeneratorAngle | model/CloudPSS/SyncGeneratorRouter | theta_o | 度 |

量测添加顺序必须与此表一致；目标模型使用其他发电机定义时，应先确认语义等价的 RID 和 args 参数。

四张图只是四类量测输出。当前稳定性算法只使用其中三类进行判定：BusVoltage 进入电压判据，GeneratorSpeed 乘以 50 后进入频率判据，GeneratorAngle 进入功角差判据。GeneratorPower 目前只用于绘图和 HDF5 保存，不参与稳定性通过/失败判断，因此结果中不存在 `power_ok`。

## 三项判据

- 电压：逐个母线扫描；低于 0.7 p.u. 的连续时间达到 1.0 s 时返回 False。连续判断使用电磁暂态计算方案中的 step_time。
- 频率：所有样本必须满足 49 <= f <= 51 Hz。工具箱从第 3 张图的转速 trace 乘以 50 后再检查。
- 功角：任意两台机组同一采样点的绝对差值不得超过 360 度；少于两台机组时返回 True。

## HDF5 数据集

潮流文件包含 P_low、P_high、pf_setting、bus_result、acline_result。暂态文件包含：

- initial_state = [trans_id, side, fault_start_time, cut_time, fault_type_index]
- bus_voltage_data
- power_data
- frequency_data（已转换为 Hz）
- power_angle_data

不要在应用脚本中重新实现这些转换或改变数据集名字；如需变更格式，先明确提出兼容性影响。最终 `voltage_ok`、`frequency_ok`、`power_angle_ok` 和顶层 `overall_pass` 不写入 HDF5，而由 analysis_result.json 统一保存。JSON 的 `stability` 对象只放前三项，`overall_pass` 是同级汇总字段。
