"""N-1 结果分析算法参考代码。

本文件只用于用户明确要求自定义、审查或修改当前结果分析算法时阅读。
普通 N-1 分析必须直接调用 N1AnalysisToolbox 的
``extract_and_check_data`` 和 ``save_flow_emt_hdf5``，不得导入或复制本文件。

本文件是 ``src/n_1analysis/n_1_analysis_toolbox.py`` 中三个稳定性判据
方法和 HDF5 写入辅助函数的忠实镜像（去掉 ``self`` 和装饰器，保留实现），
由仓库根目录的 ``tools/check_skill_sync.py`` 校验与源码一致；两者不一致时
以源码为准。``extract_and_check_data`` 与 ``save_flow_emt_hdf5`` 的编排
逻辑（四张图固定顺序、单位换算、run 目录与文件命名）见
``references/toolbox_api.md``，不在本镜像中重复。

四类量测不代表四项判据：算法只返回 ``voltage_ok``、``frequency_ok``、
``power_angle_ok`` 三项，没有 ``power_ok``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import numpy as np
from pydantic import Field


def _create_or_append_hdf5_dataset(
    group: Any,
    dataset_name: str,
    data: np.ndarray,
) -> None:
    """在 HDF5 组中创建数据集，批量模式下追加到首维。"""
    array = np.asarray(data)
    dataset_dtype = None
    if array.dtype.kind in {"O", "U"}:
        try:
            array = array.astype(float)
        except (TypeError, ValueError):
            import h5py

            dataset_dtype = h5py.string_dtype(encoding="utf-8")
            array = array.astype(str).astype(object)

    if dataset_name in group:
        dataset = group[dataset_name]
        if dataset.shape[1:] != array.shape[1:]:
            raise ValueError(
                f"数据集 {dataset_name} 的已有形状 {dataset.shape[1:]} "
                f"与待追加形状 {array.shape[1:]} 不一致"
            )
        old_size = dataset.shape[0]
        dataset.resize((old_size + array.shape[0],) + dataset.shape[1:])
        dataset[old_size:] = array
        return

    create_options: dict[str, Any] = {
        "data": array,
        "maxshape": (None,) + array.shape[1:],
        "chunks": True,
    }
    if dataset_dtype is not None:
        create_options["dtype"] = dataset_dtype
    group.create_dataset(dataset_name, **create_options)


def _write_flow_hdf5(
    target: Path,
    p_low: float,
    p_high: float,
    pf_setting: list[Any],
    bus_result: list[Any],
    acline_result: list[Any],
    append: bool = False,
) -> None:
    """写入潮流 HDF5 数据。"""
    try:
        import h5py
    except ImportError as error:
        raise RuntimeError("保存 HDF5 结果需要安装 h5py") from error

    mode = "a" if append and target.exists() else "w"
    with h5py.File(target, mode) as hdf5_file:
        _create_or_append_hdf5_dataset(
            hdf5_file, "P_low", np.asarray([p_low])
        )
        _create_or_append_hdf5_dataset(
            hdf5_file, "P_high", np.asarray([p_high])
        )
        _create_or_append_hdf5_dataset(
            hdf5_file, "pf_setting", np.asarray(pf_setting)
        )
        _create_or_append_hdf5_dataset(
            hdf5_file, "bus_result", np.asarray(bus_result)
        )
        _create_or_append_hdf5_dataset(
            hdf5_file, "acline_result", np.asarray(acline_result)
        )


def _write_emt_hdf5(
    target: Path,
    initial_state: list[Any],
    bus_voltage_data: np.ndarray,
    power_data: np.ndarray,
    frequency_data: np.ndarray,
    power_angle_data: np.ndarray,
    append: bool = False,
) -> None:
    """写入电磁暂态 HDF5 数据。"""
    try:
        import h5py
    except ImportError as error:
        raise RuntimeError("保存 HDF5 结果需要安装 h5py") from error

    mode = "a" if append and target.exists() else "w"
    with h5py.File(target, mode) as hdf5_file:
        _create_or_append_hdf5_dataset(
            hdf5_file, "initial_state", np.asarray([initial_state])
        )
        _create_or_append_hdf5_dataset(
            hdf5_file, "bus_voltage_data", np.asarray([bus_voltage_data])
        )
        _create_or_append_hdf5_dataset(
            hdf5_file, "power_data", np.asarray([power_data])
        )
        _create_or_append_hdf5_dataset(
            hdf5_file, "frequency_data", np.asarray([frequency_data])
        )
        _create_or_append_hdf5_dataset(
            hdf5_file, "power_angle_data", np.asarray([power_angle_data])
        )


def check_voltage(
    bus_voltage_data: Annotated[np.ndarray, Field(description="母线电压矩阵（p.u.），形状 [母线数, 采样点数]")],
    step_time: Annotated[float, Field(description="仿真步长（秒）")],
) -> bool:
    """校验不存在持续 1 秒及以上的低电压。

    Returns:
        bool：任一母线电压低于 0.7 p.u. 且持续达到 1.0 秒时返回
        ``False``，否则返回 ``True``。
    """
    for voltage in bus_voltage_data:
        below_threshold_time = 0.0
        for value in voltage:
            below_threshold_time = (
                below_threshold_time + step_time if value < 0.7 else 0.0
            )
            if below_threshold_time >= 1.0:
                return False
    return True


def check_frequency(
    frequency_data: Annotated[np.ndarray, Field(description="频率矩阵（Hz），形状 [机组数, 采样点数]")],
) -> bool:
    """校验频率全程位于 49~51 Hz。

    Returns:
        bool：任一采样点越界返回 ``False``，否则返回 ``True``。
    """
    return bool(np.all((frequency_data >= 49) & (frequency_data <= 51)))


def check_power_angle_diff(
    power_angle_data: Annotated[np.ndarray, Field(description="功角矩阵（度），形状 [机组数, 采样点数]")],
) -> bool:
    """校验任意两台机组同一时刻的功角差不超过 360°。

    Returns:
        bool：超限返回 ``False``；机组数少于 2 时直接返回 ``True``。
    """
    if len(power_angle_data) < 2:
        return True
    return all(
        np.max(np.abs(power_angle_data[index] - power_angle_data[other])) <= 360
        for index in range(len(power_angle_data))
        for other in range(index + 1, len(power_angle_data))
    )
