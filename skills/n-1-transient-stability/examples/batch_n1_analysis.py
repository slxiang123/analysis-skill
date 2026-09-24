"""当前项目 N1AnalysisToolbox 的批量 N-1 编排示例。

单场景 12 阶段流程封装为 ``run_scenario()`` 函数（与单次示例同形状，
量测 RID 等模型约定按探查结果调整后可各自适配），批量编排交给
``n_1analysis.batch`` 的 ``build_scenarios()`` 与 ``run_batch()``；
导入不会拉取模型或提交仿真。Token/API 地址仍从环境读取。

三种批量模式：
- random：随机生成 count 组故障参数依次仿真
- keys：遍历 trans_keys 元件列表（key 或 label 字符串）
- all：遍历当前算例全部交流线路与变压器

keys 模式下每个元件需要不同故障类型/时间等特殊要求时，请直接调用
build_scenarios 传入逐项覆盖字典（形如 {"trans_key": ..., "cut_time":
...}）构建迭代项，再交给 run_batch 执行；本示例 CLI 只接收平面
key 列表，未指定的故障参数全列表共用相同默认值。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from n_1analysis import N1AnalysisToolbox
from n_1analysis.batch import ScenarioSpec, build_scenarios, run_batch

TRANSIENT_JOB_NAME = "SA_电磁暂态仿真"
POWER_FLOW_JOB_NAME = "SA_潮流计算"
CONFIG_NAME = "SA_参数方案"

# 四类量测顺序与 extract_and_check_data 的解析顺序严格对应；
# RID 与量测参数是模型约定，换模型时先探查再调整，保持顺序不变。
MEASUREMENTS = (
    ("model/CloudPSS/_newBus_3p", "Vrms", "BusVoltage"),
    ("model/CloudPSS/SyncGeneratorRouter", "PT_o", "GeneratorPower"),
    ("model/CloudPSS/SyncGeneratorRouter", "wr_o", "GeneratorSpeed"),
    ("model/CloudPSS/SyncGeneratorRouter", "theta_o", "GeneratorAngle"),
)


def _resolve_save_path(
    configured: str | os.PathLike[str] | None = None,
) -> Path:
    """解析本示例的结果目录，默认使用脚本同级的 results。"""
    value = configured or os.getenv("N1_SAVE_PATH")
    path = Path(value).expanduser() if value else Path("results")
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path.resolve()


def _validate_inputs(
    cloudpss_model: str,
    end_time: float,
    step_time: float,
    sample_freq: int,
    n_cpu: int,
    p_low: float,
    p_high: float,
    v_low: float,
    v_high: float,
    v_adjust_ratio: float,
) -> tuple[str, str]:
    """校验模型路径与运行参数，返回拆分后的用户名和项目 key。"""
    if not cloudpss_model:
        raise ValueError("cloudpss_model 不能为空")
    parts = cloudpss_model.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "model":
        raise ValueError("cloudpss_model 必须使用 model/用户名/模型标识 格式")
    if end_time <= 0 or step_time <= 0 or sample_freq <= 0 or n_cpu <= 0:
        raise ValueError("end_time、step_time、sample_freq 和 n_cpu 必须大于 0")
    if p_low > p_high or v_low > v_high:
        raise ValueError("随机参数下限不能大于上限")
    if not 0 <= v_adjust_ratio <= 1:
        raise ValueError("v_adjust_ratio 必须在 0 到 1 之间")
    _, username, project_key = parts
    return username, project_key


def _validate_fault_params(fault_params: dict[str, Any], end_time: float) -> None:
    """校验合并随机回退后的故障参数区间。"""
    if not 0 <= float(fault_params["side"]) <= 1:
        raise ValueError("side 必须在 0 到 1 之间")
    if float(fault_params["fault_start_time"]) < 0:
        raise ValueError("fault_start_time 不能小于 0")
    if float(fault_params["cut_time"]) < float(fault_params["fault_start_time"]):
        raise ValueError("cut_time 不能早于 fault_start_time")
    if float(fault_params["cut_time"]) > end_time:
        raise ValueError("cut_time 不能晚于 end_time")
    if not 0 <= int(fault_params["fault_type"]) <= 7:
        raise ValueError("fault_type 必须在 0 到 7 之间")


def run_scenario(
    cloudpss_model: str,
    scenario: ScenarioSpec,
    *,
    token: str | None = None,
    api_url: str | None = None,
    run_id: str | None = None,
    save_path: str | os.PathLike[str] | None = None,
    seed: int | None = None,
    end_time: float = 30.0,
    step_time: float = 0.00005,
    sample_freq: int = 200,
    n_cpu: int = 1,
    solver_option: int = 0,
    p_low: float = 1.0,
    p_high: float = 1.0,
    v_low: float = 1.0,
    v_high: float = 1.0,
    v_adjust_ratio: float = 0.1,
    show_logs: bool = True,
    show_plots: bool = False,
) -> dict[str, Any]:
    """执行单个 N-1 场景：每次调用新建工具箱实例（场景隔离不变量）。

    ``scenario`` 中为 None 的故障字段随机回退并打印告知；token 未提供
    时从环境读取。本函数即 ``run_batch(scenario_runner=...)`` 的场景
    函数，批量时 run_batch 会传入 token/run_id（{batch_id}__{场景号}）/
    save_path/seed 以及 runner_kwargs 的仿真参数。
    """
    started = time.time()
    save_path = _resolve_save_path(save_path)
    username, project_key = _validate_inputs(
        cloudpss_model,
        end_time,
        step_time,
        sample_freq,
        n_cpu,
        p_low,
        p_high,
        v_low,
        v_high,
        v_adjust_ratio,
    )
    actual_token = (
        token or os.getenv("SIMSTUDIO_TOKEN") or os.getenv("CLOUDPSS_TOKEN", "")
    )
    if not actual_token:
        raise RuntimeError("缺少 SIMSTUDIO_TOKEN 或 CLOUDPSS_TOKEN")
    actual_api_url = api_url or os.getenv("CLOUDPSS_API_URL", "https://cloudpss.net/")

    prefix = f"[N-1][{scenario.scenario_id}]"
    print(f"{prefix} 初始化工具箱（模型 {cloudpss_model}）...", flush=True)
    toolbox = N1AnalysisToolbox()
    toolbox.set_config(
        token=actual_token,
        api_url=actual_api_url,
        username=username,
        model=project_key,
        delete_edges=True,
    )
    toolbox.set_initial_conditions()
    toolbox.create_sa_canvas()

    # 计算方案：查询已有避免重名；暂态方案参数整体覆盖并重置量测通道。
    print(f"{prefix} 创建/更新计算方案...", flush=True)
    transient_args = {
        "end_time": end_time,
        "step_time": step_time,
        "n_cpu": n_cpu,
        "solver_option": solver_option,
        "output_channels": [],
    }
    if not toolbox.project.getModelJob(TRANSIENT_JOB_NAME):
        toolbox.create_job("emtps", TRANSIENT_JOB_NAME, args=transient_args)
    else:
        toolbox.project.getModelJob(TRANSIENT_JOB_NAME)[0]["args"].update(
            transient_args
        )
    if not toolbox.project.getModelJob(POWER_FLOW_JOB_NAME):
        toolbox.create_job("power-flow", POWER_FLOW_JOB_NAME)
    if not toolbox.project.getModelConfig(CONFIG_NAME):
        toolbox.create_config(CONFIG_NAME)

    print(f"{prefix} 潮流采样...", flush=True)
    power_flow_result = toolbox.power_flow_sample_simple_random(
        POWER_FLOW_JOB_NAME,
        CONFIG_NAME,
        p_low=p_low,
        p_high=p_high,
        v_low=v_low,
        v_high=v_high,
        v_adjust_ratio=v_adjust_ratio,
    )
    if power_flow_result.get("status") != "success":
        raise RuntimeError(f"潮流样本计算失败: {power_flow_result}")

    print(f"{prefix} 生成/合并故障参数...", flush=True)
    generated = toolbox.generate_random_fault_params(seed=seed)
    fault_params = {
        "transKey": (
            scenario.trans_key
            if scenario.trans_key is not None
            else generated["transKey"]
        ),
        "side": scenario.side if scenario.side is not None else generated["side"],
        "fault_start_time": (
            scenario.fault_start_time
            if scenario.fault_start_time is not None
            else generated["fault_start_time"]
        ),
        "cut_time": (
            scenario.cut_time if scenario.cut_time is not None else generated["cut_time"]
        ),
        "fault_type": (
            scenario.fault_type
            if scenario.fault_type is not None
            else generated["fault_type"]
        ),
    }
    print(f"{prefix} N-1 故障参数（含随机回退项）: {fault_params}", flush=True)
    _validate_fault_params(fault_params, end_time)

    # transKey 既可填实例 key，也可填模型中的显示 label；重复 label
    # 会由工具箱列出候选 key，并要求调用方先完成选择。
    fault_params["transKey"] = toolbox.resolve_component_key(
        str(fault_params["transKey"])
    )

    fault_result = toolbox.set_n_1_ground_fault(
        trans_key=str(fault_params["transKey"]),
        side=float(fault_params["side"]),
        fault_start_time=float(fault_params["fault_start_time"]),
        cut_time=float(fault_params["cut_time"]),
        fault_type_index=int(fault_params["fault_type"]),
    )
    fault_params.update(
        {
            "transKey": fault_result["transKey"],
            "side": fault_result["side"],
            "fault_start_time": fault_result["fault_start_time"],
            "cut_time": fault_result["cut_time"],
            "fault_type": fault_result["fault_type"],
        }
    )

    print(f"{prefix} 配置四类量测...", flush=True)
    measurement_results = []
    for comp_rid, measured_key, plot_name in MEASUREMENTS:
        result = toolbox.add_component_output_measures(
            TRANSIENT_JOB_NAME,
            comp_rid=comp_rid,
            measured_key=measured_key,
            plot_name=plot_name,
            freq=sample_freq,
        )
        if not result["screenedComps"]:
            raise RuntimeError(f"未找到 {plot_name} 的有效量测元件")
        measurement_results.append(result)

    print(f"{prefix} 提交电磁暂态仿真...", flush=True)
    runner_id = toolbox.run_project(
        TRANSIENT_JOB_NAME, CONFIG_NAME, show_logs=show_logs
    )
    if runner_id == -1:
        raise RuntimeError("N-1 电磁暂态仿真运行失败")

    timestamp = time.strftime("%Y_%m_%d_%H_%M_%S")
    stability = toolbox.extract_and_check_data(
        TRANSIENT_JOB_NAME,
        timestamp=timestamp,
        show_plots=show_plots,
        save_path=save_path,
        run_id=run_id,
    )
    saved = toolbox.save_flow_emt_hdf5(
        trans_id=str(fault_params["transKey"]),
        side=float(fault_params["side"]),
        fault_start_time=float(fault_params["fault_start_time"]),
        cut_time=float(fault_params["cut_time"]),
        fault_type_index=int(fault_params["fault_type"]),
        P_low=p_low,
        P_high=p_high,
        timestamp=timestamp,
        save_path=save_path,
        run_id=run_id,
    )
    saved["plots"] = stability["html_files"]
    summary = toolbox.save_analysis_result(
        runner_id=runner_id,
        cloudpss_model=cloudpss_model,
        fault={
            **fault_params,
            "fault_result": fault_result,
        },
        simulation={
            "end_time": end_time,
            "step_time": step_time,
            "sample_freq": sample_freq,
            "n_cpu": n_cpu,
            "solver_option": solver_option,
        },
        power_flow={
            **power_flow_result,
            "p_low": p_low,
            "p_high": p_high,
            "v_low": v_low,
            "v_high": v_high,
            "v_adjust_ratio": v_adjust_ratio,
        },
        artifacts=saved,
        timestamp=timestamp,
        save_path=save_path,
        run_id=run_id,
    )
    saved["analysis_json"] = summary["artifacts"]["analysis_json"]

    elapsed = round(time.time() - started, 1)
    print(
        f"{prefix} 稳定性检查:",
        {
            key: stability[key]
            for key in ("voltage_ok", "frequency_ok", "power_angle_ok")
        },
        flush=True,
    )
    print(f"{prefix} 场景完成，用时 {elapsed}s，结果目录 {stability['run_dir']}", flush=True)
    return {
        "scenario_id": scenario.scenario_id,
        "runner_id": str(runner_id),
        "timestamp": timestamp,
        "power_flow_result": power_flow_result,
        "fault_params": fault_params,
        "fault_result": fault_result,
        "measurement_results": measurement_results,
        "stability_result": stability,
        "saved_files": saved,
        "run_id": stability["run_id"],
        "run_dir": stability["run_dir"],
        "elapsed_seconds": elapsed,
    }


def _probe_toolbox(cloudpss_model: str) -> N1AnalysisToolbox:
    """只读探查：delete_edges=False，仅构建元件索引，不修改模型。"""
    token = os.getenv("SIMSTUDIO_TOKEN") or os.getenv("CLOUDPSS_TOKEN", "")
    api_url = os.getenv("CLOUDPSS_API_URL", "https://cloudpss.net/")
    if not token:
        raise RuntimeError("缺少 SIMSTUDIO_TOKEN 或 CLOUDPSS_TOKEN")
    parts = cloudpss_model.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "model":
        raise ValueError("cloudpss_model 必须使用 model/用户名/模型标识 格式")
    toolbox = N1AnalysisToolbox()
    toolbox.set_config(
        token=token,
        api_url=api_url,
        username=parts[1],
        model=parts[2],
        delete_edges=False,
    )
    toolbox.set_initial_conditions()
    return toolbox


def main(
    cloudpss_model: str,
    *,
    mode: str = "random",
    count: int = 2,
    trans_keys: list[str] | None = None,
    seed: int | None = None,
    backend: str = "sequential",
    max_workers: int = 2,
    stop_on_error: bool = False,
    end_time: float = 30.0,
    step_time: float = 0.00005,
    sample_freq: int = 200,
    n_cpu: int = 1,
    solver_option: int = 0,
    p_low: float = 1.0,
    p_high: float = 1.0,
    v_low: float = 1.0,
    v_high: float = 1.0,
    v_adjust_ratio: float = 0.1,
    show_logs: bool = True,
    show_plots: bool = False,
    save_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """执行一次批量 N-1 分析；每个场景都会编辑远程模型并产生计算成本。"""
    # 后台运行（nohup、输出重定向）时保持行缓冲，日志才能实时写入文件。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except (AttributeError, OSError):
            pass

    # 只读探查实例仅用于场景构建，不复用于执行（场景隔离不变量）。
    probe = _probe_toolbox(cloudpss_model)
    scenarios = build_scenarios(
        mode,
        toolbox=probe,
        count=count,
        trans_keys=trans_keys,
        seed=seed,
    )
    transmission = probe.get_transmission_keys()
    print(
        f"模型共 {len(transmission['acline_keys'])} 条交流线路、"
        f"{len(transmission['trans_keys'])} 台变压器"
    )
    print(f"批量模式 {mode}，场景清单（{len(scenarios)} 个）:", [s.label for s in scenarios])
    del probe

    batch_result = run_batch(
        cloudpss_model,
        scenarios,
        scenario_runner=run_scenario,
        save_path=_resolve_save_path(save_path),
        runner_kwargs={
            "end_time": end_time,
            "step_time": step_time,
            "sample_freq": sample_freq,
            "n_cpu": n_cpu,
            "solver_option": solver_option,
            "p_low": p_low,
            "p_high": p_high,
            "v_low": v_low,
            "v_high": v_high,
            "v_adjust_ratio": v_adjust_ratio,
            "show_logs": show_logs,
            "show_plots": show_plots,
        },
        backend=backend,
        max_workers=max_workers,
        stop_on_error=stop_on_error,
        seed=seed,
    )
    print("批量汇总:", batch_result["summary"])
    print("批次文件:", batch_result["artifacts"])
    print("=== N-1 批量分析流程完成 ===")
    return batch_result


def _parse_args() -> argparse.Namespace:
    """读取批量模式参数与共享运行参数。"""
    parser = argparse.ArgumentParser(description="执行 CloudPSS 批量 N-1 暂态稳定分析")
    parser.add_argument("--cloudpss-model", required=True)
    parser.add_argument("--mode", choices=["random", "keys", "all"], default="random")
    parser.add_argument("--count", type=int, default=2, help="random 模式的场景数")
    parser.add_argument("--trans-keys", help="keys 模式的元件列表，逗号分隔")
    parser.add_argument(
        "--save-path",
        help="结果根目录；相对路径相对本脚本目录，缺省为脚本同级 results",
    )
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--backend", choices=["sequential", "ray"], default="sequential"
    )
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--end-time", type=float, default=30.0)
    parser.add_argument("--step-time", type=float, default=0.00005)
    parser.add_argument("--sample-freq", type=int, default=200)
    parser.add_argument("--n-cpu", type=int, default=1)
    parser.add_argument("--solver-option", type=int, default=0)
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    main(
        cli_args.cloudpss_model,
        mode=cli_args.mode,
        count=cli_args.count,
        trans_keys=(
            [item.strip() for item in cli_args.trans_keys.split(",") if item.strip()]
            if cli_args.trans_keys
            else None
        ),
        save_path=cli_args.save_path,
        seed=cli_args.seed,
        backend=cli_args.backend,
        max_workers=cli_args.max_workers,
        stop_on_error=cli_args.stop_on_error,
        end_time=cli_args.end_time,
        step_time=cli_args.step_time,
        sample_freq=cli_args.sample_freq,
        n_cpu=cli_args.n_cpu,
        solver_option=cli_args.solver_option,
    )
