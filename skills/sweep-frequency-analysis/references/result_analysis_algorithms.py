"""扫频结果解析、保存与绘图算法参考代码。

本文件只用于智能体在用户明确要求理解、审查或修改结果分析算法时阅读。
普通扫频脚本应直接调用工具箱的
``parse_frequency_spectrum_result``、``save_frequency_spectrum_result`` 和
``read_frequency_spectrum_plot_nyquist_file``，不得导入或复制本文件。

本文件是 ``src/sweepanalysis/sweep_analysis_toolbox.py`` 中相应方法的忠实
镜像（去掉 ``self``，保留注释），由仓库根目录的
``tools/check_skill_sync.py`` 校验与源码一致；两者不一致时以源码为准。
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import plotly.graph_objects as go
from matplotlib.path import Path as MatplotlibPath
from pydantic import Field


def _timestamped_file_path(
    path: str | os.PathLike[str], timestamp: str | None = None
) -> Path:
    """为输出文件名添加时间戳，并避免同名文件被覆盖。"""
    output_path = Path(path)
    timestamp_text = timestamp or time.strftime("%Y_%m_%d_%H_%M_%S")
    timestamp_pattern = re.compile(
        rf"_{re.escape(timestamp_text)}(?:_\d+)?$"
    )
    if not timestamp_pattern.search(output_path.stem):
        output_path = output_path.with_name(
            f"{output_path.stem}_{timestamp_text}{output_path.suffix}"
        )

    candidate = output_path
    index = 1
    while candidate.exists():
        candidate = output_path.with_name(
            f"{output_path.stem}_{index}{output_path.suffix}"
        )
        index += 1
    return candidate


def parse_frequency_spectrum_result(
    simulation_result: Annotated[
        Any, Field(description="CloudPSS 扫频仿真结果对象")
    ],
    harmonic_args: Annotated[
        Mapping[str, float], Field(description="扫频元件的分段频率和持续时间参数")
    ],
    sample_freq: Annotated[
        float, Field(description="仿真结果的实际输出采样频率，单位为 Hz")
    ] = 100,
) -> dict[str, list[Any]]:
    """从扫频仿真结果中解析频率、阻抗幅值和相位。

    按三段扫频参数定位每个频点的稳态采样窗口，对正序、负序和综合
    阻抗及相位通道求平均。

    Returns:
        含 ``F``（频率）、``Z``（阻抗幅值）和 ``Ph``（相位）的字典。

    Raises:
        ValueError: 采样频率或平均窗口无效、输出通道缺失或样本不足时。
    """
    if sample_freq <= 0:
        raise ValueError("sample_freq 必须大于 0")

    point_counts = (
        round(
            (harmonic_args["EndVal1"] - harmonic_args["InitVal1"])
            / harmonic_args["DeltaStep1"]
        )
        + 1,
        round(
            (harmonic_args["EndVal2"] - harmonic_args["EndVal1"])
            / harmonic_args["DeltaStep2"]
        ),
        round(
            (harmonic_args["EndVal3"] - harmonic_args["EndVal2"])
            / harmonic_args["DeltaStep3"]
        ),
    )
    point_count = sum(point_counts)
    frequency = np.zeros(point_count)
    impedance = np.zeros((point_count, 3))
    phase = np.zeros((point_count, 3))

    time1 = harmonic_args["InitTime"]
    time2 = time1 + (
        (harmonic_args["EndVal1"] - harmonic_args["InitVal1"])
        / harmonic_args["DeltaStep1"]
        + 1
    ) * harmonic_args["DeltaTime1"]
    time3 = time2 - harmonic_args["DeltaTime2"] + (
        (harmonic_args["EndVal2"] - harmonic_args["EndVal1"])
        / harmonic_args["DeltaStep2"]
        + 1
    ) * harmonic_args["DeltaTime2"]

    plot_index = 0
    output_channels: dict[str, str] = {}
    for channel_name in simulation_result.getPlotChannelNames(plot_index):
        if "Zn" in channel_name:
            output_channels["Zn"] = channel_name
        elif "Zp" in channel_name:
            output_channels["Zp"] = channel_name
        elif "Z" in channel_name:
            output_channels["Z"] = channel_name
        elif "Php" in channel_name:
            output_channels["Php"] = channel_name
        elif "Phn" in channel_name:
            output_channels["Phn"] = channel_name
        elif "Ph" in channel_name:
            output_channels["Ph"] = channel_name
        elif "F" in channel_name:
            output_channels["Freq"] = channel_name

    required_channels = {"Freq", "Z", "Zn", "Zp", "Ph", "Phn", "Php"}
    missing_channels = sorted(required_channels - output_channels.keys())
    if missing_channels:
        raise ValueError(f"仿真结果缺少输出通道: {', '.join(missing_channels)}")

    frequency_values = np.asarray(
        simulation_result.getPlotChannelData(
            plot_index, output_channels["Freq"]
        )["y"]
    )
    impedance_values = [
        np.asarray(
            simulation_result.getPlotChannelData(
                plot_index, output_channels[name]
            )["y"]
        )
        for name in ("Z", "Zn", "Zp")
    ]
    phase_values = [
        np.asarray(
            simulation_result.getPlotChannelData(
                plot_index, output_channels[name]
            )["y"]
        )
        for name in ("Ph", "Phn", "Php")
    ]
    available_samples = min(
        len(frequency_values),
        *(len(values) for values in impedance_values),
        *(len(values) for values in phase_values),
    )

    segment_starts = (time1, time2, time3)
    segment_durations = (
        harmonic_args["DeltaTime1"],
        harmonic_args["DeltaTime2"],
        harmonic_args["DeltaTime3"],
    )
    offset = 0
    average_rate = 0.1
    for count, start_time, duration in zip(
        point_counts, segment_starts, segment_durations
    ):
        position = round(sample_freq * start_time)
        step = round(sample_freq * duration)
        window_size = round(average_rate * step)
        if step <= 0 or window_size <= 0:
            raise ValueError("采样频率过低，无法为扫频点生成有效的平均窗口")

        for point_index in range(count):
            end = position + step * (point_index + 1) - 1
            start = end - window_size
            if start < 0 or end > available_samples:
                raise ValueError("仿真结果长度不足，无法解析全部扫频点")

            result_index = offset + point_index
            frequency[result_index] = np.mean(frequency_values[start:end])
            for sequence_index in range(3):
                impedance[result_index, sequence_index] = np.mean(
                    impedance_values[sequence_index][start:end]
                )
                phase[result_index, sequence_index] = np.mean(
                    phase_values[sequence_index][start:end]
                )
        offset += count

    return {
        "F": frequency.tolist(),
        "Z": impedance.tolist(),
        "Ph": phase.tolist(),
    }


def _normalize_frequency_spectrum_data(
    spectrum_data: Annotated[
        Mapping[str, Any], Field(description="包含 F、Z 和 Ph 字段的频谱数据")
    ],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """校验频谱数据，并统一转换为 NumPy 数组。"""
    missing_keys = {"F", "Z", "Ph"} - spectrum_data.keys()
    if missing_keys:
        raise ValueError(f"频谱数据缺少字段: {', '.join(sorted(missing_keys))}")

    frequency = np.asarray(spectrum_data["F"], dtype=float)
    impedance = np.asarray(spectrum_data["Z"], dtype=float)
    phase = np.asarray(spectrum_data["Ph"], dtype=float)
    if frequency.ndim != 1:
        raise ValueError("F 必须是一维数组")
    if impedance.ndim != 2 or impedance.shape[1] != 3:
        raise ValueError("Z 必须是包含 Z、Zn、Zp 三列的二维数组")
    if phase.ndim != 2 or phase.shape[1] != 3:
        raise ValueError("Ph 必须是包含 Ph、Phn、Php 三列的二维数组")
    if not (len(frequency) == len(impedance) == len(phase)):
        raise ValueError("F、Z、Ph 的频率点数量必须一致")
    return frequency, impedance, phase


def save_frequency_spectrum_result(
    spectrum_data: Annotated[
        Mapping[str, Any], Field(description="包含 F、Z 和 Ph 字段的频谱数据")
    ],
    save_path: Annotated[
        str | os.PathLike[str] | None,
        Field(description="结果根目录；未指定时使用当前目录下的 results")
    ] = None,
    project_key: Annotated[
        str, Field(description="用于创建结果子目录的模型标识")
    ] = "qingyuanGRID",
    timestamp: Annotated[
        str | None,
        Field(description="保存文件使用的统一时间戳；未指定时自动生成")
    ] = None,
) -> dict[str, str]:
    """校验并规范化频谱数据，保存为带时间戳的 JSON 文件。

    结果按 ``save_path/project_key`` 归档；``timestamp`` 未提供时
    自动生成。

    Returns:
        ``{"json": <已保存文件路径>}``。

    Raises:
        ValueError: 频谱字段缺失、形状错误或频率点数不一致时。
        OSError: 目录或文件无法写入时。
    """
    # 先统一输入数据的类型和形状，避免生成结构不完整的结果文件。
    frequency, impedance, phase = _normalize_frequency_spectrum_data(
        spectrum_data
    )

    # 每次保存均按项目归档，并使用时间戳避免覆盖此前的扫频结果。
    base_path = (
        Path("results")
        if save_path is None or save_path == ""
        else Path(save_path)
    )
    output_path = base_path / project_key
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp_text = timestamp or time.strftime("%Y_%m_%d_%H_%M_%S")
    json_path = _timestamped_file_path(
        output_path / "HarmFre.json", timestamp_text
    )

    # JSON 保留解析后的原始频率、阻抗幅值和相位，便于后续重新绘图。
    serializable_data = {
        "F": frequency.tolist(),
        "Z": impedance.tolist(),
        "Ph": phase.tolist(),
    }
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(serializable_data, file, indent=4, ensure_ascii=False)

    return {"json": str(json_path)}


def read_frequency_spectrum_plot_nyquist_file(
    source: Annotated[
        Mapping[str, Any] | str | os.PathLike[str],
        Field(description="频谱数据字典或保存该数据的 JSON 文件路径"),
    ],
    *,
    show: Annotated[
        bool, Field(description="是否立即显示图表并输出谐振风险判断")
    ] = True,
    html_dir: Annotated[
        str | os.PathLike[str] | None,
        Field(description="分析图 HTML 输出目录；为 None 时不保存")
    ] = None,
    timestamp: Annotated[
        str | None,
        Field(description="保存文件使用的统一时间戳；未指定时自动生成")
    ] = None,
) -> dict[str, Any]:
    """读取频谱并生成阻抗、相位、阻尼系数和奈奎斯特图，判断谐振风险。

    ``source`` 为频谱字典或已保存的 JSON 文件路径；提供 ``html_dir``
    时四张图分别保存为带时间戳的 Plotly HTML。

    Returns:
        含 ``magnitude``/``phase``/``damping``/``nyquist`` 图形对象、
        ``html_files`` 路径映射和 ``resonance_risk`` 判断结果的字典；
        未指定 ``html_dir`` 时 ``html_files`` 为空字典。

    Raises:
        TypeError: ``source`` 类型不受支持时。
        ValueError: 频谱内容无效时。
        OSError: 文件无法读写时。
    """
    if isinstance(source, Mapping):
        spectrum_data = source
    elif isinstance(source, (str, os.PathLike)):
        with Path(source).open("r", encoding="utf-8") as file:
            spectrum_data = json.load(file)
    else:
        raise TypeError("source 必须是解析结果字典或 JSON 文件路径")

    # 统一数据结构，并排除基频附近 40～60 Hz 的区间，以突出扫频特征。
    frequency, impedance, phase = _normalize_frequency_spectrum_data(
        spectrum_data
    )
    selected = (frequency <= 40) | (frequency >= 60)
    frequency = frequency[selected]
    impedance = impedance[selected]
    phase = phase[selected]

    # 分别绘制正序和负序阻抗的幅频曲线。
    magnitude_figure = go.Figure(
        layout=go.Layout(
            template="plotly_white",
            title="阻抗幅值频谱",
            xaxis=dict(title="频率 (Hz)", type="log"),
            yaxis=dict(title="阻抗幅值 (dB)"),
        )
    )
    for index, name in ((1, "Zn"), (2, "Zp")):
        magnitude_figure.add_trace(
            go.Scatter(
                x=frequency, y=impedance[:, index], mode="lines", name=name
            )
        )

    # 分别绘制正序和负序阻抗的相频曲线。
    phase_figure = go.Figure(
        layout=go.Layout(
            template="plotly_white",
            title="阻抗相位频谱",
            xaxis=dict(title="频率 (Hz)", type="log"),
            yaxis=dict(title="阻抗相位 (°)"),
        )
    )
    for index, name in ((1, "Phn"), (2, "Php")):
        phase_figure.add_trace(go.Scatter(x=frequency, y=phase[:, index], mode="lines", name=name))

    # 将 dB 和角度转换为极坐标量，计算正负序阻抗组合的阻尼系数。
    negative_magnitude = 10 ** (impedance[:, 1] / 20)
    positive_magnitude = 10 ** (impedance[:, 2] / 20)
    negative_phase = np.deg2rad(phase[:, 1])
    positive_phase = np.deg2rad(phase[:, 2])
    damping_numerator = (
        negative_magnitude * np.cos(negative_phase)
        + positive_magnitude * np.cos(positive_phase)
    )
    denominator_radicand = -(
        negative_magnitude
        * np.sin(negative_phase)
        * positive_magnitude
        * np.sin(positive_phase)
    )

    # 该指标仅在根号项为正且参与计算的数据有限时具有实数意义。
    # 其余频率点保留为 NaN，使 Plotly 将其显示为曲线断点，避免把
    # 无实数意义的复数结果误画成零值。
    damping_coefficient = np.full_like(
        denominator_radicand, np.nan, dtype=float
    )
    valid_damping = (
        np.isfinite(damping_numerator)
        & np.isfinite(denominator_radicand)
        & (denominator_radicand > 0)
    )
    damping_coefficient[valid_damping] = damping_numerator[valid_damping] / (
        2 * np.sqrt(denominator_radicand[valid_damping])
    )

    damping_figure = go.Figure(
        layout=go.Layout(
            template="plotly_white",
            title="阻尼系数",
            xaxis=dict(title="频率 (Hz)", type="log"),
            yaxis=dict(title="阻尼系数"),
        )
    )
    damping_figure.add_trace(
        go.Scatter(
            x=frequency, y=damping_coefficient, mode="lines", name="阻尼系数"
        )
    )

    # 构造半径为 0.2 的风险边界，并计算网侧/机侧阻抗比的极坐标轨迹。
    # 扫频模块的 Pos 端对应网侧，Neg 端对应机侧，因此该比值为 Zp/Zn。
    radians = np.arange(0, 2 * np.pi, 0.01)
    radius = 0.2
    boundary_angle = np.pi - np.arctan(
        radius * np.sin(radians) / (1 - radius * np.cos(radians))
    )
    boundary_radius = np.sqrt(
        (radius * np.sin(radians)) ** 2
        + (1 - radius * np.cos(radians)) ** 2
    )
    ratio_angle = np.deg2rad(phase[:, 2] - phase[:, 1])
    ratio_radius = 10 ** ((impedance[:, 2] - impedance[:, 1]) / 20)
    boundary_cartesian = np.column_stack(
        (
            boundary_radius * np.cos(boundary_angle),
            boundary_radius * np.sin(boundary_angle),
        )
    )
    ratio_cartesian = np.column_stack(
        (
            ratio_radius * np.cos(ratio_angle),
            ratio_radius * np.sin(ratio_angle),
        )
    )

    # 与历史算法一致：将两条极坐标曲线转换为笛卡尔坐标路径，再用
    # Matplotlib Path 判断阻抗比轨迹是否与风险边界相交。
    resonance_risk = MatplotlibPath(boundary_cartesian).intersects_path(
        MatplotlibPath(ratio_cartesian)
    )

    # 在极坐标中叠加风险边界与阻抗比轨迹，形成奈奎斯特诊断图。
    nyquist_figure = go.Figure(
        layout=go.Layout(
            template="plotly_white",
            title="网侧/机侧阻抗比奈奎斯特图 ($Z_{grid}/Z_{machine}$)",
            polar=dict(
                angularaxis=dict(thetaunit="radians"),
                radialaxis=dict(title="阻抗比幅值"),
            ),
        )
    )
    nyquist_figure.add_trace(
        go.Scatterpolar(
            theta=boundary_angle,
            r=boundary_radius,
            thetaunit="radians",
            mode="lines",
            name="风险边界",
            line=dict(color="green", dash="dash"),
            fill="toself",
            fillcolor="rgba(0, 128, 0, 0.2)",
        )
    )
    nyquist_figure.add_trace(
        go.Scatterpolar(
            theta=ratio_angle,
            r=ratio_radius,
            thetaunit="radians",
            mode="lines",
            name="$Z_{grid}/Z_{machine}$",
            line=dict(color="black", dash="dash"),
        )
    )

    html_files: dict[str, str] = {}
    if html_dir is not None:
        # 四张分析图分别保存，便于在浏览器中单独查看或归档。
        output_dir = Path(html_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp_text = timestamp or time.strftime("%Y_%m_%d_%H_%M_%S")
        figures = {
            "magnitude": magnitude_figure,
            "phase": phase_figure,
            "damping": damping_figure,
            "nyquist": nyquist_figure,
        }
        for name, figure in figures.items():
            output_path = _timestamped_file_path(
                output_dir / f"{name}.html",
                timestamp_text,
            )
            figure.write_html(str(output_path), include_plotlyjs=True)
            html_files[name] = str(output_path)

    # show=False 时仅返回图形对象，适合批处理或无图形界面的运行环境。
    if show:
        magnitude_figure.show()
        phase_figure.show()
        damping_figure.show()
        nyquist_figure.show()
        print(" 是否有谐振风险: ", resonance_risk)

    return {
        "magnitude": magnitude_figure,
        "phase": phase_figure,
        "damping": damping_figure,
        "nyquist": nyquist_figure,
        "html_files": html_files,
        "resonance_risk": resonance_risk,
    }
