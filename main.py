#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
公募基金理财系统 - 净值发布与合规回退自动化管理系统
=====================================================
"""
import sys
import json
from datetime import datetime, timedelta
from tabulate import tabulate

from models import init_db
from release_manager import (
    init_sample_funds, create_net_value_release,
    run_pre_check, get_release_detail
)
from approval_engine import (
    init_approval_flow, process_approval,
    auto_approve_all, get_approval_flow_detail
)
from push_manager import (
    execute_full_grayscale_push, get_push_status
)
from monitor_rollback import (
    execute_monitor_check, trigger_compliance_rollback,
    restore_previous_stable_version, get_monitor_history,
    get_active_monitoring_releases
)
from rollback_exercise import (
    create_rollback_exercise, execute_rollback_exercise,
    get_exercise_detail, list_exercises
)
from report_generator import generate_weekly_report
from history_manager import (
    query_release_history, get_release_full_detail,
    export_release_history, get_statistics_summary
)
from audit_logger import query_audit_logs, write_audit_log


def print_separator(title=""):
    line = "=" * 80
    if title:
        print(f"\n{line}")
        print(f"  {title}")
        print(f"{line}\n")
    else:
        print(f"\n{line}\n")


def print_result(result, title="操作结果"):
    print(f"\n[{title}]")
    if isinstance(result, dict):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result)


def demo_normal_release_flow():
    print_separator("演示1: 标准净值发布流程")

    fund_code = "000001"
    net_value_date = datetime.now().strftime('%Y-%m-%d')
    net_value = round(1.5 + (datetime.now().minute % 100) * 0.001, 4)

    print(f"1.1 提交净值发布申请 - 基金: {fund_code}, 净值日期: {net_value_date}, 净值: {net_value}")
    result = create_net_value_release(
        fund_code=fund_code,
        net_value_date=net_value_date,
        net_value=net_value,
        accumulated_net_value=round(net_value + 2.0, 4),
        daily_growth_rate=round((net_value - 1.5) / 1.5 * 100, 2),
        version="1.0.0",
        risk_level="NORMAL",
        applicant="运营-李经理",
        operator="user_li"
    )
    print_result(result, "创建发布申请")
    release_id = result['release_id']

    print(f"\n1.2 执行前置条件检查")
    check_result = run_pre_check(release_id=release_id, operator="system")
    print_result(check_result, "前置检查结果")

    if not check_result['success']:
        print("前置检查未通过，流程终止")
        return None

    print(f"\n1.3 启动证监会合规审批流程")
    approval_result = init_approval_flow(release_id=release_id, operator="system")
    print_result(approval_result, "审批流程启动")

    print(f"\n1.4 自动完成全部审批（演示用）")
    approve_result = auto_approve_all(release_id=release_id, operator="admin")
    print_result(approve_result, "审批结果")

    print(f"\n1.5 执行投资者分级灰度推送（机构客户→个人客户）")
    push_result = execute_full_grayscale_push(release_id=release_id, operator="system")
    print_result(push_result, "推送结果")

    print(f"\n1.6 查看发布详情")
    detail = get_release_detail(release_id=release_id)
    print_result(detail, "发布详情")

    print(f"\n1.7 执行一次监控检查")
    monitor_result = execute_monitor_check(release_id=release_id, operator="system")
    print_result(monitor_result, "监控检查")

    return release_id


def demo_rollback_flow():
    print_separator("演示2: 异常触发合规回退流程")

    fund_code = "000002"
    net_value_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    print(f"2.1 创建一个新的发布并完成全部流程")
    result = create_net_value_release(
        fund_code=fund_code,
        net_value_date=net_value_date,
        net_value=2.3456,
        accumulated_net_value=3.4567,
        daily_growth_rate=1.23,
        version="1.1.0",
        risk_level="NORMAL",
        applicant="运营-王经理",
        operator="user_wang"
    )
    release_id = result['release_id']

    run_pre_check(release_id=release_id, operator="system")
    init_approval_flow(release_id=release_id, operator="system")
    auto_approve_all(release_id=release_id, operator="admin")
    execute_full_grayscale_push(release_id=release_id, operator="system")

    print(f"发布已完成，release_id={release_id}")

    print(f"\n2.2 模拟手动触发合规回退（发现净值异常）")
    rollback_result = trigger_compliance_rollback(
        release_id=release_id,
        trigger_reason="人工复核发现净值核算错误，托管行对账差异超过阈值",
        trigger_source="MANUAL",
        operator="compliance_officer"
    )
    print_result(rollback_result, "回退结果")

    print(f"\n2.3 恢复上一监管备案稳定版本")
    restore_result = restore_previous_stable_version(
        release_id=release_id,
        operator="system"
    )
    print_result(restore_result, "版本恢复")

    return release_id


def demo_rollback_exercise():
    print_separator("演示3: 净值披露回滚演练")

    fund_code = "000003"
    print(f"3.1 创建回滚演练任务")
    exercise_result = create_rollback_exercise(
        fund_code=fund_code,
        target_version="1.0.0",
        exercise_name="二季度净值回退应急演练",
        executor="应急演练小组",
        operator="exercise_admin"
    )
    print_result(exercise_result, "演练创建")
    exercise_id = exercise_result['exercise_id']

    print(f"\n3.2 执行回滚演练（含估值校验）")
    exec_result = execute_rollback_exercise(
        exercise_id=exercise_id,
        operator="exercise_admin"
    )
    print_result(exec_result, "演练执行")

    print(f"\n3.3 查看演练详情")
    detail = get_exercise_detail(exercise_id=exercise_id)
    print_result(detail, "演练详情")

    return exercise_id


def demo_reporting():
    print_separator("演示4: 报表生成与统计")

    print(f"4.1 生成每周统计报告（含PDF趋势图 + Excel报表）")
    report_result = generate_weekly_report(operator="system")
    print_result(report_result, "报告生成")

    print(f"\n4.2 系统统计概览")
    stats = get_statistics_summary()
    print_result(stats, "系统统计")

    return report_result


def demo_history_query():
    print_separator("演示5: 历史记录查询与批量导出")

    print(f"5.1 组合条件查询历史发布记录")
    query_result = query_release_history(
        fund_code=None,
        start_date=(datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'),
        end_date=datetime.now().strftime('%Y-%m-%d'),
        page=1,
        page_size=10,
        date_filter_type='publish'
    )

    print(f"\n共找到 {query_result['total']} 条记录，当前第 {query_result['page']}/{query_result['total_pages']} 页（按发布时间筛选）")

    if query_result['data']:
        table_data = []
        for item in query_result['data']:
            table_data.append([
                item['release_no'],
                item['fund_code'],
                item['fund_name'],
                item['net_value_date'],
                item['net_value'],
                item['version'],
                item['risk_level'],
                item['status'],
                item['apply_time'],
                item.get('publish_time') or '未发布'
            ])

        headers = ['发布编号', '基金代码', '基金名称', '净值日期', '单位净值', '版本号', '风险级别', '状态', '申请时间', '发布时间']
        print(tabulate(table_data, headers=headers, tablefmt='simple', showindex=True))

    print(f"\n5.2 批量导出查询结果为Excel（包含申请时间+发布时间两列）")
    export_result = export_release_history(
        query_params={
            'start_date': (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'),
            'end_date': datetime.now().strftime('%Y-%m-%d'),
            'date_filter_type': 'publish'
        },
        export_format='xlsx',
        operator="user_export"
    )
    print_result(export_result, "导出结果")

    print(f"\n5.3 查询监管审计日志")
    logs = query_audit_logs(
        start_time=datetime.now() - timedelta(hours=1),
        page=1,
        page_size=5
    )
    print(f"共找到 {logs['total']} 条审计日志")

    if logs['data']:
        log_table = []
        for log in logs['data']:
            log_table.append([
                log['log_time'],
                log['operator'],
                log['operation_type'],
                log['target_type'] or '-',
                log['target_id'] or '-'
            ])
        headers = ['时间', '操作人', '操作类型', '目标类型', '目标ID']
        print(tabulate(log_table, headers=headers, tablefmt='simple', showindex=True))

    return query_result


def demo_urgent_release():
    print_separator("演示6: 紧急估值修正流程")

    fund_code = "000004"
    print(f"6.1 提交紧急估值修正申请（URGENT风险级别）")
    result = create_net_value_release(
        fund_code=fund_code,
        net_value_date=datetime.now().strftime('%Y-%m-%d'),
        net_value=1.8900,
        accumulated_net_value=2.1000,
        daily_growth_rate=-2.34,
        version="2.0.0",
        risk_level="URGENT",
        applicant="估值核算部-紧急",
        operator="valuator_zhang"
    )
    release_id = result['release_id']
    print_result(result, "紧急申请创建")

    print(f"\n6.2 执行前置检查")
    check_result = run_pre_check(release_id=release_id, operator="system")
    print_result(check_result, "前置检查")

    if check_result['success']:
        print(f"\n6.3 启动紧急审批流程")
        init_approval_flow(release_id=release_id, operator="system")
        detail = get_approval_flow_detail(release_id=release_id)
        print_result(detail, "审批流程详情")

    return release_id


def interactive_menu():
    menu = """
╔══════════════════════════════════════════════════════════════╗
║          公募基金净值发布与合规回退管理系统                    ║
╠══════════════════════════════════════════════════════════════╣
║  1. 演示: 标准净值发布流程                                   ║
║  2. 演示: 异常触发合规回退流程                               ║
║  3. 演示: 净值披露回滚演练                                   ║
║  4. 演示: 报表生成与统计                                     ║
║  5. 演示: 历史记录查询与导出                                 ║
║  6. 演示: 紧急估值修正流程                                   ║
║  7. 运行全部演示                                             ║
║  8. 启动定时调度器（监控 + 每周报表）                         ║
║  9. 查看当前监控中的发布                                     ║
║  10. 退出                                                    ║
╚══════════════════════════════════════════════════════════════╝
    """

    while True:
        print(menu)
        choice = input("请选择操作 (1-10): ").strip()

        try:
            if choice == '1':
                demo_normal_release_flow()
            elif choice == '2':
                demo_rollback_flow()
            elif choice == '3':
                demo_rollback_exercise()
            elif choice == '4':
                demo_reporting()
            elif choice == '5':
                demo_history_query()
            elif choice == '6':
                demo_urgent_release()
            elif choice == '7':
                print("\n>>> 开始运行全部演示流程...\n")
                demo_normal_release_flow()
                demo_rollback_flow()
                demo_rollback_exercise()
                demo_reporting()
                demo_history_query()
                demo_urgent_release()
                print_separator("全部演示流程完成!")
            elif choice == '8':
                from scheduler import start_scheduler
                start_scheduler()
            elif choice == '9':
                active = get_active_monitoring_releases()
                print(f"\n当前监控中的发布: {len(active)} 个")
                if active:
                    table_data = [[a['release_no'], a['fund_code'], a['net_value_date'],
                                  a['net_value'], a['version'], a['push_status']] for a in active]
                    headers = ['发布编号', '基金代码', '净值日期', '单位净值', '版本', '推送状态']
                    print(tabulate(table_data, headers=headers, tablefmt='simple', showindex=True))
            elif choice == '10':
                print("感谢使用，再见！")
                sys.exit(0)
            else:
                print("无效的选择，请重新输入")

            if choice != '8':
                input("\n按 Enter 继续...")

        except Exception as e:
            print(f"\n操作出错: {str(e)}")
            import traceback
            traceback.print_exc()
            input("\n按 Enter 继续...")


def main():
    print_separator("公募基金净值发布与合规回退自动化管理系统")
    print("系统初始化中...")

    init_db()
    init_sample_funds()

    write_audit_log(
        operator='system',
        operation_type='SYSTEM_START',
        operation_details={'start_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    )

    print("系统初始化完成！")

    if len(sys.argv) > 1:
        if sys.argv[1] == '--demo':
            print("\n>>> 运行全部演示流程...\n")
            demo_normal_release_flow()
            demo_rollback_flow()
            demo_rollback_exercise()
            demo_reporting()
            demo_history_query()
            demo_urgent_release()
            print_separator("全部演示流程完成!")
        elif sys.argv[1] == '--scheduler':
            from scheduler import start_scheduler
            start_scheduler()
        elif sys.argv[1] == '--help':
            print("""
用法: python main.py [选项]

选项:
  --demo        运行全部演示流程
  --scheduler   启动定时调度器
  --help        显示帮助信息

无参数时进入交互式菜单
            """)
        else:
            interactive_menu()
    else:
        interactive_menu()


if __name__ == '__main__':
    main()
