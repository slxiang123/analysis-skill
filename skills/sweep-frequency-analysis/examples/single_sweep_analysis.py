"""CloudPSS 单次电压/电流扫频分析的完整编排案例。

Token 和 API 地址从环境变量读取；模型、元件和注入类型由调用方显式提供。
本案例针对已通过元数据探查确认的电压源，不能把其中的有效值参数和引脚选择
直接用于其他元件。导入本文件不会获取模型或启动远程仿真。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import nest_asyncio
import numpy as np

from sweepanalysis.sweep_analysis_toolbox import SweepAnalysisToolbox

nest_asyncio.apply()


SWEEP_PARAMETER_KEYS = {
    "Mag", "InitTime", "RampTime", "Sequence",
    "InitVal1", "EndVal1", "DeltaStep1", "DeltaTime1",
    "InitVal2", "EndVal2", "DeltaStep2", "DeltaTime2",
    "InitVal3", "EndVal3", "DeltaStep3", "DeltaTime3",
    "RampRatio", "UnitTest",
}

# 这是本电压源案例的探查结果，不是跨元件通用默认值。智能体为其他目标元件
# 生成正式脚本前，必须通过临时探查脚本重新确定并替换这两个值。
VOLTAGE_NAME = "Vm"
TESTED_PIN = "0"


def _merge_harmonic_args(
    baseline: Mapping[str, float | int],
    overrides: Mapping[str, float | int] | None,
) -> dict[str, float | int]:
    """合并并校验扫频模块参数。"""
    harmonic_args = dict(baseline)
    if overrides:
        unknown = set(overrides) - SWEEP_PARAMETER_KEYS
        if unknown:
            raise ValueError(f"未知扫频模块参数: {', '.join(sorted(unknown))}")
        harmonic_args.update(overrides)

    missing = SWEEP_PARAMETER_KEYS - harmonic_args.keys()
    if missing:
        raise ValueError(f"缺少扫频模块参数: {', '.join(sorted(missing))}")
    for key, value in harmonic_args.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"扫频模块参数 {key} 必须是数值")

    if not (
        harmonic_args["InitVal1"]
        < harmonic_args["EndVal1"]
        < harmonic_args["EndVal2"]
        < harmonic_args["EndVal3"]
    ):
        raise ValueError(
            "频率边界必须满足 InitVal1 < EndVal1 < EndVal2 < EndVal3"
        )
    for key in (
        "DeltaStep1", "DeltaStep2", "DeltaStep3",
        "DeltaTime1", "DeltaTime2", "DeltaTime3",
    ):
        if harmonic_args[key] <= 0:
            raise ValueError(f"{key} 必须大于 0")
    if harmonic_args["Mag"] <= 0:
        raise ValueError("Mag 必须大于 0")
    if harmonic_args["InitTime"] < 0 or harmonic_args["RampTime"] < 0:
        raise ValueError("InitTime 和 RampTime 不能为负数")
    if harmonic_args["Sequence"] not in {0, 1, 2}:
        raise ValueError("Sequence 只能为 0、1 或 2")
    if not 0 < harmonic_args["RampRatio"] <= 1:
        raise ValueError("RampRatio 必须在 (0, 1] 范围内")
    if harmonic_args["UnitTest"] not in {0, 1}:
        raise ValueError("UnitTest 只能为 0 或 1")

    harmonic_args["Sequence"] = int(harmonic_args["Sequence"])
    harmonic_args["UnitTest"] = int(harmonic_args["UnitTest"])
    return harmonic_args


def _calculate_end_time(harmonic_args: Mapping[str, float | int]) -> float:
    """根据最终扫频配置计算完整扫频所需的仿真结束时间。"""
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
    return float(
        time3
        - harmonic_args["DeltaTime3"]
        + (
            (harmonic_args["EndVal3"] - harmonic_args["EndVal2"])
            / harmonic_args["DeltaStep3"]
            + 1
        )
        * harmonic_args["DeltaTime3"]
    )


def main(
    cloudpss_model: str,
    component_key: str,
    injection_type: str,
    *,
    harmonic_overrides: Mapping[str, float | int] | None = None,
    sample_freq: float = 100,
    n_cpu: int = 1,
    solver_option: int = 0,
    save_path: str | os.PathLike[str] = "results",
    show_plots: bool = True,
) -> dict[str, Any]:
    """使用显式业务输入运行一次完整扫频分析。

    这里只展示标准案例常用的可选项。其他公开 API 参数或配置字段应按
    ``references/toolbox_api.md`` 中的真实签名扩展，不要透传未知键。
    """
    # 后台运行（nohup、输出重定向）时保持行缓冲，日志才能实时写入文件。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except (AttributeError, OSError):
            pass

    required_values = {
        "cloudpss_model": cloudpss_model,
        "component_key": component_key,
        "injection_type": injection_type,
    }
    missing = [name for name, value in required_values.items() if not value]
    if missing:
        raise ValueError(f"缺少必填业务输入: {', '.join(missing)}")

    cloudpss_token = os.getenv("SIMSTUDIO_TOKEN") or os.getenv(
        "CLOUDPSS_TOKEN", ""
    )
    cloudpss_api_url = os.getenv("CLOUDPSS_API_URL", "https://cloudpss.net/")
    if not cloudpss_token:
        raise RuntimeError("缺少 SIMSTUDIO_TOKEN 或 CLOUDPSS_TOKEN")

    injection_type = injection_type.upper()
    if injection_type not in {"V", "I"}:
        raise ValueError("injection_type 仅支持 'V' 或 'I'")
    if sample_freq <= 0:
        raise ValueError("sample_freq 必须大于 0")
    if n_cpu <= 0:
        raise ValueError("n_cpu 必须大于 0")

    model_parts = cloudpss_model.strip("/").split("/")
    if len(model_parts) != 3 or model_parts[0] != "model":
        raise ValueError("cloudpss_model 必须使用 model/用户名/模型标识 格式")
    _, username, project_key = model_parts

    toolbox = SweepAnalysisToolbox()
    toolbox.set_config(
        cloudpss_token,
        cloudpss_api_url,
        username,
        project_key,
        delete_edges=True,
    )
    toolbox.set_initial_conditions()
    toolbox.create_sweep_canvas()

    target_component = toolbox.project.getComponentByKey(component_key)
    if target_component is None:
        raise ValueError(f"未找到扫频接入元件: {component_key}")
    voltage_name = VOLTAGE_NAME
    tested_pin = TESTED_PIN
    if tested_pin not in target_component.pins:
        raise ValueError(
            f"元件 {component_key} 不包含案例已探查引脚 {tested_pin}；"
            "请先重新探查该元件"
        )
    if voltage_name not in target_component.args:
        raise ValueError(
            f"元件 {component_key} 缺少案例已探查电压参数 {voltage_name}；"
            "请先重新探查该元件"
        )
    base_voltage = float(target_component.args[voltage_name])

    if injection_type == "V":
        harmonic_name = "SA扫频模块_V"
        baseline_harmonic_args = {
            "Mag": base_voltage * np.sqrt(2 / 3) * 1000 * 0.03,
            "InitTime": 10, "RampTime": 1, "Sequence": 1,
            "InitVal1": 5, "EndVal1": 100,
            "DeltaStep1": 1, "DeltaTime1": 5, "InitVal2": 0,
            "EndVal2": 200, "DeltaStep2": 5, "DeltaTime2": 3,
            "InitVal3": 0, "EndVal3": 1000,
            "DeltaStep3": 10, "DeltaTime3": 1,
            "RampRatio": 0.2, "UnitTest": 0,
        }
    else:
        harmonic_name = "SA扫频模块_I"
        baseline_harmonic_args = {
            "Mag": 100 / base_voltage * np.sqrt(2) / 3 * 1000 * 0.03,
            "InitTime": 10, "RampTime": 1, "Sequence": 1,
            "InitVal1": 10, "EndVal1": 70,
            "DeltaStep1": 1, "DeltaTime1": 5, "InitVal2": 0,
            "EndVal2": 200, "DeltaStep2": 10, "DeltaTime2": 3,
            "InitVal3": 0, "EndVal3": 2000,
            "DeltaStep3": 20, "DeltaTime3": 1,
            "RampRatio": 0.2, "UnitTest": 0,
        }
    harmonic_args = _merge_harmonic_args(
        baseline_harmonic_args, harmonic_overrides
    )

    component_args = {key: str(value) for key, value in harmonic_args.items()}
    harmonic_pins = {
        "Freq": f"{harmonic_name}.F",
        "Neg": f"{harmonic_name}.Neg",
        "Ph": f"{harmonic_name}.Ph",
        "Phn": f"{harmonic_name}.Phn",
        "Php": f"{harmonic_name}.Php",
        "Pos": target_component.pins[tested_pin],
        "Z": f"{harmonic_name}.Z",
        "Zn": f"{harmonic_name}.Zn",
        "Zp": f"{harmonic_name}.Zp",
    }
    target_component.pins[tested_pin] = harmonic_pins["Neg"]

    harmonic_definition = (
        "model/CloudPSS/Harmonic_continuous_injection_V"
        if injection_type == "V"
        else "model/CloudPSS/Harmonic_continuous_injection_I"
    )
    toolbox.add_comp_in_canvas(
        harmonic_definition,
        canvas=toolbox.c_fid,
        args=component_args,
        pins=harmonic_pins,
        label=harmonic_name,
    )
    toolbox.new_line_position(toolbox.c_fid)

    output_channel_ids = []
    for pin_key, pin_name in harmonic_pins.items():
        if pin_key in {"Pos", "Neg"}:
            continue
        channel_id, _ = toolbox.add_channel(pin_name, 1)
        output_channel_ids.append(channel_id)

    # 结束时间只能由合并、校验后的最终扫频参数推导，不能单独配置。
    end_time = _calculate_end_time(harmonic_args)
    job_name = "Sweep_电磁暂态仿真"
    config_name = "Sweep_参数方案"
    toolbox.create_job(
        "emtps",
        name=job_name,
        args={
            "begin_time": 0,
            "end_time": end_time,
            "step_time": 0.00005,
            "solver_option": solver_option,
            "n_cpu": n_cpu,
        },
    )
    toolbox.create_config(name=config_name)
    toolbox.add_outputs(
        job_name,
        {
            "0": "频率分析",
            "1": str(sample_freq),
            "2": "compressed",
            "3": 1,
            "4": output_channel_ids,
        },
    )

    runner_id = toolbox.run_project(
        job_name=job_name,
        config_name=config_name,
        show_logs=True,
    )
    if runner_id == -1:
        raise RuntimeError("扫频仿真运行失败")

    simulation_result = toolbox.runner.result
    result_timestamp = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime())
    result_dir = Path(save_path or "results") / project_key
    toolbox.config["plot_tool"] = "plotly"
    toolbox.plot_result(
        simulation_result,
        k=0,
        html_path=result_dir / "simulation_waveform.html",
        show=show_plots,
        timestamp=result_timestamp,
    )
    spectrum_data = toolbox.parse_frequency_spectrum_result(
        simulation_result,
        harmonic_args,
        sample_freq=sample_freq,
    )
    saved_files = toolbox.save_frequency_spectrum_result(
        spectrum_data,
        save_path=save_path,
        project_key=project_key,
        timestamp=result_timestamp,
    )
    saved_files["simulation_waveform"] = toolbox.last_plot_html_path

    diagnostics = toolbox.read_frequency_spectrum_plot_nyquist_file(
        spectrum_data,
        show=show_plots,
        html_dir=result_dir,
        timestamp=result_timestamp,
    )
    saved_files["analysis_plots"] = diagnostics["html_files"]

    result = {
        "runner_id": str(runner_id),
        "timestamp": result_timestamp,
        "harmonic_args": harmonic_args,
        "spectrum_data": spectrum_data,
        "saved_files": saved_files,
        "resonance_risk": diagnostics["resonance_risk"],
    }
    print(saved_files)
    print("是否有谐振风险:", result["resonance_risk"])
    print("=== 扫频流程完成 ===")
    return result


def _parse_args() -> argparse.Namespace:
    """读取三项必须由用户明确指定的业务参数。"""
    parser = argparse.ArgumentParser(description="执行一次 CloudPSS 扫频分析")
    parser.add_argument("--cloudpss-model", required=True)
    parser.add_argument("--component-key", required=True)
    parser.add_argument("--injection-type", choices=("V", "I"), required=True)
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    main(
        cli_args.cloudpss_model,
        cli_args.component_key,
        cli_args.injection_type,
    )
