"""对单次扫频编排脚本执行静态检查。

校验器自动识别两种脚本：调用 `run_project` 的全流程扫频脚本，以及
只分析已有频谱结果的分析型脚本，并应用对应的必查项。

本校验器只解析源代码，不导入项目、不读取凭据、不连接 CloudPSS，
也不会执行远程仿真。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


REQUIRED_IMPORTS = {"SweepAnalysisToolbox"}
REQUIRED_CALLS = {
    "set_config",
    "set_initial_conditions",
    "create_sweep_canvas",
    "add_comp_in_canvas",
    "add_channel",
    "create_job",
    "create_config",
    "add_outputs",
    "run_project",
    "plot_result",
    "parse_frequency_spectrum_result",
    "save_frequency_spectrum_result",
    "read_frequency_spectrum_plot_nyquist_file",
}
REQUIRED_ANALYSIS_CALLS = {"read_frequency_spectrum_plot_nyquist_file"}
FORBIDDEN_TEXT = {
    "single_sweep_frequency": "已删除的旧高层扫频函数",
    "setConfig": "旧版 CamelCase API setConfig",
    "createSACanvas": "旧版 CamelCase API createSACanvas",
    "addCompInCanvas": "旧版 CamelCase API addCompInCanvas",
    "addChannel": "旧版 CamelCase API addChannel",
    "createJob": "旧版 CamelCase API createJob",
    "createConfig": "旧版 CamelCase API createConfig",
    "addOutputs": "旧版 CamelCase API addOutputs",
    "runProject": "旧版 CamelCase API runProject",
    "plotResult": "旧版 CamelCase API plotResult",
    "plotTool": "旧版绘图配置键 plotTool",
}
# 这两项只在 import 语句中检查，避免注释或文档字符串中的提及误报。
IMPORT_FORBIDDEN_TEXT = {
    "sweepanalysis.sweep": "已删除的 sweep 模块导入",
    "SweepAnalysisToolbox.py": "旧版工具箱模块文件名",
}
FORBIDDEN_ENVIRONMENT_VARIABLES = {
    "CLOUDPSS_MODEL",
    "CLOUDPSS_COMPONENT_KEY",
    "CLOUDPSS_COMP_KEY",
    "SWEEP_TESTED_PIN",
    "SWEEP_INJECTION_TYPE",
    "SWEEP_END_TIME",
}
REQUIRED_BUSINESS_INPUTS = {
    "cloudpss_model",
    "component_key",
    "injection_type",
}
REQUIRED_DISCOVERY_VALUES = {"voltage_name", "tested_pin"}


def _called_method_names(tree: ast.AST) -> set[str]:
    """收集脚本中所有直接调用的方法名。"""
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _import_related_text(tree: ast.AST) -> str:
    """汇总所有 import 语句涉及的模块名和导入名。"""
    parts: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            parts.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            parts.append(node.module or "")
            parts.extend(alias.name for alias in node.names)
    return "\n".join(parts)


def validate(path: Path) -> list[str]:
    """返回目标脚本中发现的静态检查错误。"""
    errors: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError) as error:
        return [f"无法解析 {path}：{error}"]

    imported_names = {
        alias.name.split(".")[-1]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    missing_imports = REQUIRED_IMPORTS - imported_names
    if missing_imports:
        errors.append("缺少 SweepAnalysisToolbox 导入")

    called_methods = _called_method_names(tree)
    # 调用 run_project 的是全流程扫频脚本；否则按只读的分析型脚本检查。
    is_analysis_script = "run_project" not in called_methods
    required_calls = (
        REQUIRED_ANALYSIS_CALLS if is_analysis_script else REQUIRED_CALLS
    )
    missing_calls = required_calls - called_methods
    if missing_calls:
        errors.append("缺少关键工具箱调用：" + "、".join(sorted(missing_calls)))

    for forbidden, description in FORBIDDEN_TEXT.items():
        if forbidden in source:
            errors.append(f"发现{description}: {forbidden}")

    import_related = _import_related_text(tree)
    for forbidden, description in IMPORT_FORBIDDEN_TEXT.items():
        # 用词边界匹配，避免把 sweepanalysis.sweep 误判到
        # sweepanalysis.sweep_analysis_toolbox 这类正常模块名上。
        if re.search(
            rf"(?<![\w.]){re.escape(forbidden)}(?![\w.])", import_related
        ):
            errors.append(f"发现{description}: {forbidden}")

    if re.search(
        r"(?:SIMSTUDIO_TOKEN|CLOUDPSS_TOKEN)\s*=\s*['\"][^'\"]{20,}['\"]",
        source,
    ):
        errors.append("可能存在硬编码的 CloudPSS 令牌")

    for variable in FORBIDDEN_ENVIRONMENT_VARIABLES:
        if re.search(
            rf"(?:getenv|environ\.get)\(\s*['\"]{re.escape(variable)}['\"]",
            source,
        ):
            errors.append(
                f"业务输入或派生参数不应从环境变量 {variable} 读取"
            )

    if re.search(r"read_frequency_spectrum_plot_nyquist_file\([^)]*show\s*=\s*True", source, re.S):
        errors.append("脚本强制显示诊断图形；应将 show 绑定到配置项")

    if "save_frequency_spectrum_result" in source and re.search(
        r"(?:impedance|admittance)\s*['\"]?\s*:", source
    ):
        errors.append("结果保存返回值不应假定存在阻抗或导纳文本文件")

    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if "main" not in function_names:
        errors.append("脚本应定义 main() 函数")
    elif not is_analysis_script:
        main_function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
        )
        main_arguments = {
            argument.arg
            for argument in (
                *main_function.args.posonlyargs,
                *main_function.args.args,
                *main_function.args.kwonlyargs,
            )
        }
        if "end_time" in main_arguments:
            errors.append("end_time 是流程派生值，不应作为 main() 的用户输入")
        positional_arguments = [
            *main_function.args.posonlyargs,
            *main_function.args.args,
        ]
        required_positional_count = (
            len(positional_arguments) - len(main_function.args.defaults)
        )
        required_arguments = {
            argument.arg
            for argument in positional_arguments[:required_positional_count]
        }
        required_arguments.update(
            argument.arg
            for argument, default in zip(
                main_function.args.kwonlyargs,
                main_function.args.kw_defaults,
            )
            if default is None
        )
        if "tested_pin" in required_arguments:
            errors.append(
                "tested_pin 应来自元件探查或作为可选候选，不应是必填输入"
            )
        missing_business_inputs = REQUIRED_BUSINESS_INPUTS - main_arguments
        if missing_business_inputs:
            errors.append(
                "main() 缺少显式业务输入："
                + "、".join(sorted(missing_business_inputs))
            )

    if not is_analysis_script:
        assigned_names = {
            target.id
            for node in ast.walk(tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
            )
            if isinstance(target, ast.Name)
        }
        function_arguments = {
            argument.arg
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            )
        }
        missing_discovery_values = REQUIRED_DISCOVERY_VALUES - (
            assigned_names | function_arguments
        )
        if missing_discovery_values:
            errors.append(
                "正式脚本缺少元件探查结果："
                + "、".join(sorted(missing_discovery_values))
            )

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(
                node.value, ast.Constant
            ):
                if any(
                    isinstance(target, ast.Name) and target.id == "end_time"
                    for target in node.targets
                ):
                    errors.append("end_time 不应被赋为固定常量")
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "end_time"
                        and isinstance(value, ast.Constant)
                    ):
                        errors.append("计算方案中的 end_time 不应是固定常量")

    return errors


def main(argv: list[str] | None = None) -> int:
    """运行命令行校验器并返回进程退出码。"""
    # Windows 下输出被管道捕获时默认使用本地编码，统一切到 UTF-8 避免乱码。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("用法：validate_sweep_script.py <脚本路径>", file=sys.stderr)
        return 2

    script_path = Path(args[0])
    errors = validate(script_path)
    if errors:
        for error in errors:
            print(f"错误：{error}")
        return 1

    mode = "分析型" if "run_project" not in script_path.read_text(encoding="utf-8") else "全流程"
    print(f"通过：扫频编排脚本静态检查无误（{mode}模式）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
