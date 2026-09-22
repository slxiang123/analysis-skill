# `sweep_analysis_toolbox.py` — 扫频分析工具箱 API

本文档只记录 `SweepAnalysisToolbox` 中名称不以下划线开头的公开方法。`__init__` 以及 `_...` 开头的方法属于构造或内部实现，不作为应用层 API 使用。

导入方式：

```python
from sweepanalysis.sweep_analysis_toolbox import SweepAnalysisToolbox
```

除 `set_config`、`get_runner_logs` 和两个类方法外，各方法均要求先调用 `set_initial_conditions()` 获取模型，否则会在访问 `project` 时抛出 `AttributeError`。

## 连接与模型初始化

### `set_config`

更新 CloudPSS 连接信息、模型标识和模型编辑选项。只更新显式提供的字段；设置 `token` 或 `api_url` 时会同步更新 CloudPSS SDK 或当前进程环境。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `token` | `str \| None` | `None` | CloudPSS API Token；未提供时保留实例当前值 |
| `api_url` | `str \| None` | `None` | CloudPSS API 地址；未提供时保留实例当前值 |
| `username` | `str \| None` | `None` | 模型所属用户名 |
| `model` | `str \| None` | `None` | 模型标识，只传项目键，不含 `model/{username}/` 前缀 |
| `delete_edges` | `bool \| None` | `None` | 初始化时是否将图形连接线转换为命名引脚连接 |

返回：`None`

异常：字符串参数为空或类型错误时抛出 `ValueError`；`delete_edges` 类型错误时抛出 `TypeError`。

---

### `set_initial_conditions`

校验运行配置并获取 CloudPSS 模型，建立输出通道索引和画布布局状态；启用 `delete_edges` 时还会刷新拓扑并转换图形连接线。

参数：无。

返回：`None`

副作用：设置实例的 `project`、通道索引和画布状态，并可能转换当前内存模型的连接关系。

异常：令牌、API 地址、用户名或模型标识缺失，或拓扑初始化失败时抛出 `RuntimeError`。

## 画布、元件与通道

### `create_canvas`

在当前模型中创建画布，并初始化该画布的自动布局坐标。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `canvas` | `str` | 必需 | 新画布的 key |
| `name` | `str` | 必需 | 新画布的显示名称 |

返回：`None`

副作用：将新画布追加到当前模型 revision 的画布列表。

异常：参数不是非空字符串时抛出 `ValueError`。

---

### `create_sweep_canvas`

确保扫频模块画布和输出通道画布存在。已存在的画布只重新初始化布局，不重复创建。

参数：无。

返回：`None`

副作用：更新当前模型的画布列表及实例布局状态 `pos`。

---

### `new_line_position`

将指定画布中下一个元件的自动布局位置移动到新行起点。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `canvas` | `str` | 必需 | 已初始化布局的画布 key |

返回：`None`

副作用：更新对应画布的横坐标、纵坐标和当前行高度。

异常：画布 key 为空或画布尚未初始化布局时抛出 `ValueError`。

---

### `add_comp_in_canvas`

在指定画布的当前自动布局位置添加元件，并推进后续元件的位置。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `definition` | `str` | 必需 | 元件定义 RID |
| `canvas` | `str` | 必需 | 元件所在画布的 key |
| `args` | `dict \| None` | `None` | 元件参数字典 |
| `pins` | `dict \| None` | `None` | 元件引脚映射 |
| `label` | `str \| None` | `None` | 元件显示标签 |
| `d_x` | `int` | `10` | 添加元件后额外增加的横向间距 |
| `max_x` | `float \| None` | `None` | 单行最大横坐标；超过时自动换行 |

返回：`tuple[str, str]`

- 第一个元素：CloudPSS 生成的元件 ID。
- 第二个元素：本次添加使用的标签。

异常：画布尚未初始化布局时抛出 `KeyError`。

---

### `add_channel`

为指定引脚添加或复用 CloudPSS 输出通道。已有通道时可用 `channel_name` 更新其名称。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `pin_name` | `str` | 必需 | 需要输出的引脚名称 |
| `dim` | `int` | 必需 | 输出通道维度；单值通道通常传 `1` |
| `channel_name` | `str \| None` | `None` | 自定义通道名称；未指定时使用引脚名 |

返回：`tuple[str, str]`

- 第一个元素：输出通道元件 ID。
- 第二个元素：输出通道标签。

异常：输出画布尚未初始化布局时抛出 `KeyError`。

## 计算方案与运行

### `create_job`

根据内置模板创建 CloudPSS 计算方案，并用 `args` 增量覆盖模板参数。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `stype` | `str` | `'emtps'` | 计算方案类型；支持 `emtp`、`emtps`、`power-flow`、`powerFlow` |
| `name` | `str \| None` | `None` | 计算方案名称；未指定时使用模板名称 |
| `args` | `dict \| None` | `None` | 使用原始参数 key 增量覆盖的计算方案配置 |

返回：`None`

副作用：将计算方案添加到当前模型。

异常：方案类型不受支持时抛出 `ValueError`。

---

### `create_config`

根据默认模板创建模型参数方案，可增量配置参数和引脚。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | `str \| None` | `None` | 参数方案名称；未指定时使用模板名称 |
| `args` | `dict \| None` | `None` | 参数配置，只需提供需要覆盖的字段 |
| `pins` | `dict \| None` | `None` | 引脚配置，只需提供需要覆盖的字段 |

返回：`None`

副作用：将参数方案添加到当前模型。

---

### `add_outputs`

向指定的 EMTP 或 EMTPS 计算方案追加一组输出通道配置。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `job_name` | `str` | 必需 | 已创建的计算方案名称 |
| `channels` | `dict` | 必需 | 输出配置，格式为 `[输出图像名称, 输出频率, 输出图像类型, 图像宽度, 输出通道key]`；方法按原样追加，不校验字段 |

返回：`int`

- 新增配置在该方案 `output_channels` 列表中的零基索引。

异常：找不到方案或方案不是 EMTP/EMTPS 类型时抛出 `ValueError`。

---

### `run_project`

运行指定计算方案和参数方案，并等待 CloudPSS 运行器结束。电磁暂态计算会根据结果时间输出进度。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `job_name` | `str` | 必需 | 要运行的计算方案名称 |
| `config_name` | `str` | 必需 | 要使用的参数方案名称 |
| `show_logs` | `bool` | `False` | 是否持续输出运行器日志 |
| `api_url` | `str \| None` | `None` | 本次运行单独使用的 API 地址 |
| `websocket_error_time` | `float \| None` | `None` | WebSocket 异常重跑时用于判断有效进度的时间阈值 |

返回：`str | int`

- 成功时返回 CloudPSS runner ID。
- 平台报告失败且无法继续时返回 `-1`。

副作用：提交远程仿真并等待执行，可能产生时间和计算费用。

异常：找不到计算方案或参数方案时抛出 `ValueError`；启动重试 5 次仍失败时抛出 `RuntimeError`。

---

### `get_runner_logs`

读取当前运行器产生的日志。

参数：无。

返回：`list[dict[str, Any]]`

- 运行器日志记录列表。
- 尚未创建运行器时返回空列表。

## 绘图与结果处理

### `plot_result`

绘制 CloudPSS 原始时域波形。Plotly 模式可将结果保存为独立 HTML；频谱和奈奎斯特图不由此方法生成。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `result` | `Any` | `None` | 结果对象或结果 ID；未提供时使用当前 `runner.result` |
| `k` | `int \| None` | `None` | 结果图索引；`None` 等价于 `0` |
| `html_path` | `str \| os.PathLike[str] \| None` | `None` | Plotly HTML 输出路径；未指定时不保存 |
| `show` | `bool` | `True` | 是否显示图形；批处理或无图形环境可设为 `False` |
| `timestamp` | `str \| None` | `None` | 保存文件使用的统一时间戳；未指定时自动生成。与其他保存方法传入同一值可统一文件名 |

返回：`Any`

- `plot_tool='plotly'` 时返回 `plotly.graph_objects.Figure`。
- `plot_tool='matplotlib'` 时返回 `matplotlib.axes.Axes`。

异常：`show` 类型错误时抛出 `TypeError`；图索引、结果 ID 或绘图工具无效时抛出 `ValueError`；结果或 runner 不可用时抛出 `RuntimeError`。

---

### `parse_frequency_spectrum_result`

根据三段扫频参数，从仿真通道的稳态采样窗口中解析频率、阻抗幅值和相位。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `simulation_result` | `Any` | 必需 | CloudPSS 扫频仿真原始结果对象 |
| `harmonic_args` | `Mapping[str, float]` | 必需 | 扫频元件的分段端点、步长和持续时间等参数 |
| `sample_freq` | `float` | `100` | 仿真结果实际输出采样频率，单位 Hz |

返回：`dict[str, list[Any]]`

```python
{
    "F": [frequency, ...],
    "Z": [[Z, Zn, Zp], ...],
    "Ph": [[Ph, Phn, Php], ...],
}
```

异常：采样频率无效、缺少 `Freq`、`Z`、`Zn`、`Zp`、`Ph`、`Phn`、`Php` 通道或结果样本不足时抛出 `ValueError`。

---

### `save_frequency_spectrum_result`

校验并规范化频谱数据，将其保存为带时间戳的 JSON 文件。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `spectrum_data` | `Mapping[str, Any]` | 必需 | 含 `F`、`Z`、`Ph` 的频谱数据 |
| `save_path` | `str \| os.PathLike[str] \| None` | `None` | 结果根目录；空值使用当前目录下的 `results` |
| `project_key` | `str` | `'qingyuanGRID'` | 用于创建结果子目录的模型标识；应用脚本应显式传入实际值 |
| `timestamp` | `str \| None` | `None` | JSON 文件使用的统一时间戳；未指定时自动生成 |

返回：`dict[str, str]`

```python
{"json": "<save_path>/<project_key>/HarmFre_<timestamp>.json"}
```

异常：频谱字段缺失、数组形状错误或频率点数量不一致时抛出 `ValueError`；目录或文件无法写入时抛出 `OSError`。

---

### `read_frequency_spectrum_plot_nyquist_file`

读取频谱数据，生成阻抗幅频图、相频图、阻尼系数图和奈奎斯特图，并判断谐振风险。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `source` | `Mapping[str, Any] \| str \| os.PathLike[str]` | 必需 | 内存中的频谱字典或已保存的 JSON 文件路径 |
| `show` | `bool` | `True` | 是否显示四张图并打印谐振风险 |
| `html_dir` | `str \| os.PathLike[str] \| None` | `None` | 四张 Plotly HTML 的输出目录；未指定时不保存 |
| `timestamp` | `str \| None` | `None` | 四张 HTML 使用的统一时间戳；未指定时自动生成 |

返回：`dict[str, Any]`

```python
{
    "magnitude": magnitude_figure,
    "phase": phase_figure,
    "damping": damping_figure,
    "nyquist": nyquist_figure,
    "html_files": {
        "magnitude": ".../magnitude.html",
        "phase": ".../phase.html",
        "damping": ".../damping.html",
        "nyquist": ".../nyquist.html",
    },
    "resonance_risk": bool,
}
```

未指定 `html_dir` 时，`html_files` 为空字典。

异常：`source` 类型错误时抛出 `TypeError`；频谱内容无效时抛出 `ValueError`；JSON 或 HTML 无法读写时抛出 `OSError`。

## 元件元数据

### `fetch_comp_data`

类方法。通过 GraphQL 批量读取指定 RID 对应的 CloudPSS 元件定义；输入为空时不发送请求。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `rids` | `list[str]` | 必需 | 要查询的元件定义 RID 列表 |

返回：`dict[str, Any]`

- 以 GraphQL 查询别名为键、元件定义数据为值的字典。
- `rids` 为空时返回空字典。

---

### `generate_parameter_dict`

类方法。获取指定项目，批量读取其中使用的元件定义，并整理参数和引脚元数据。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `token` | `str` | 必需 | CloudPSS API Token |
| `api_url` | `str` | 必需 | CloudPSS API 地址 |
| `project_rid` | `str` | 必需 | 完整项目 RID，如 `model/{username}/{project_key}` |

返回：`tuple[dict[str, Any], dict[str, Any]]`

- `parameter_dict`：按元件 RID 保存元件名称和参数定义。
- `pin_dict`：按元件 RID 保存引脚定义。
