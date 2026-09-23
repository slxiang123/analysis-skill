"""对 N-1 编排脚本执行静态检查。

校验器自动识别以下脚本类型并应用对应的必查项：

1. 全流程：调用 run_project 的单次脚本，必须内联全部 12 个关键
   工具箱调用（12 阶段编排封装在场景函数中）。
2. 全流程批量：同时调用 run_project 与 run_batch 的批量脚本，在
   全流程要求之上还必须调用 build_scenarios 构建场景清单，并包含
   批量完成标记（复用场景函数而不内联 run_project 的批量脚本按
   "批量（复用场景函数）"检查后三项）。
3. 复用单场景函数：只调用 run_scenario 的脚本。
4. 分析型：只解读/复判已有结果的脚本。

只解析源代码，不导入 CloudPSS，不读取凭据，也不会提交远程仿真。
环境变量采用白名单策略（只允许三个连接变量），比黑名单更严格。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REQUIRED_IMPORTS = {"N1AnalysisToolbox"}
BATCH_IMPORTS = {
    "run_scenario",
    "run_batch",
    "build_scenarios",
    "save_batch_result",
    "ScenarioSpec",
    "RunOptions",
}
REQUIRED_CALLS = {
    "set_config",
    "set_initial_conditions",
    "create_sa_canvas",
    "create_job",
    "create_config",
    "power_flow_sample_simple_random",
    "set_n_1_ground_fault",
    "add_component_output_measures",
    "run_project",
    "extract_and_check_data",
    "save_flow_emt_hdf5",
    "save_analysis_result",
}
# 分析型脚本只需引用任一判据方法或已保存的结果 JSON。
ANALYSIS_CALLS = {"check_voltage", "check_frequency", "check_power_angle_diff"}
ANALYSIS_RESULT_FILE = "analysis_result.json"
BATCH_COMPLETION_MARKER = "=== N-1 批量分析流程完成 ==="
ALLOWED_ENVIRONMENT_VARIABLES = {
    "SIMSTUDIO_TOKEN",
    "CLOUDPSS_TOKEN",
    "CLOUDPSS_API_URL",
}


def validate(path: Path) -> tuple[list[str], str]:
    """返回目标脚本中发现的静态检查错误和识别出的脚本模式。"""
    errors: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError) as error:
        return [f"无法解析 {path}: {error}"], "未知"

    imported_names = {
        alias.name.split(".")[-1]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    if not (REQUIRED_IMPORTS & imported_names) and not (
        BATCH_IMPORTS & imported_names
    ):
        errors.append(
            "缺少 N1AnalysisToolbox 或 n_1analysis.batch 编排函数导入"
        )

    called_methods = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    called_functions = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    # 调用 run_project 的是全流程脚本（12 阶段编排内联在场景函数中）；
    # 调用 run_batch 的是批量脚本（内联或复用场景函数），追加批量必查
    # 项；只复用 run_scenario 的按复用模式检查；其余按只读的分析型
    # 脚本检查。
    if "run_batch" in called_functions:
        if "run_project" in called_methods:
            mode = "全流程批量"
            if missing := REQUIRED_CALLS - called_methods:
                errors.append("缺少关键工具箱调用: " + "、".join(sorted(missing)))
        else:
            mode = "批量（复用场景函数）"
        if "build_scenarios" not in called_functions:
            errors.append("批量脚本应先调用 build_scenarios 构建场景清单")
        if BATCH_COMPLETION_MARKER not in source:
            errors.append(f"批量脚本缺少完成标记: {BATCH_COMPLETION_MARKER}")
    elif "run_project" in called_methods:
        mode = "全流程"
        if missing := REQUIRED_CALLS - called_methods:
            errors.append("缺少关键工具箱调用: " + "、".join(sorted(missing)))
    elif "run_scenario" in called_functions:
        mode = "复用单场景函数"
    else:
        mode = "分析型"
        if not (called_methods & ANALYSIS_CALLS) and ANALYSIS_RESULT_FILE not in source:
            errors.append(
                "分析型脚本应调用任一 check_* 判据方法或读取 analysis_result.json"
            )

    if re.search(
        r"(?:SIMSTUDIO_TOKEN|CLOUDPSS_TOKEN)\s*=\s*['\"][^'\"]{20,}['\"]",
        source,
    ):
        errors.append("可能存在硬编码的 CloudPSS 令牌")

    environment_variables = set(
        re.findall(
            r"""(?:getenv|environ\.get)\(\s*['"]([A-Z][A-Z0-9_]*)['"]""",
            source,
        )
    )
    disallowed_environment_variables = (
        environment_variables - ALLOWED_ENVIRONMENT_VARIABLES
    )
    if disallowed_environment_variables:
        errors.append(
            "只允许从环境变量读取连接信息，发现业务变量: "
            + "、".join(sorted(disallowed_environment_variables))
        )

    if "line_buffering" not in source and "flush=True" not in source:
        errors.append(
            "脚本未启用行缓冲输出；后台运行（nohup/重定向）时日志无法实时写入文件"
        )

    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "main"
    ]
    if not functions:
        errors.append("脚本应定义 main() 函数")
    elif mode != "分析型":
        args = functions[0].args
        names = {
            argument.arg
            for argument in (*args.posonlyargs, *args.args, *args.kwonlyargs)
        }
        if "cloudpss_model" not in names:
            errors.append("main() 缺少显式 cloudpss_model 输入")

    return errors, mode


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
        print("用法: validate_n1_script.py <脚本路径>", file=sys.stderr)
        return 2
    script_path = Path(args[0])
    errors, mode = validate(script_path)
    if errors:
        for error in errors:
            print(f"错误: {error}")
        return 1
    print(f"通过: N-1 编排脚本静态检查无误（{mode}模式）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
