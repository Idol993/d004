#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
系统功能验证脚本 - 简洁版，直接验证5个修复点
"""
import os
import sys
import json
import random
from datetime import datetime, timedelta

from models import init_db, SessionLocal, NetValueRelease, PreCheckRecord
from release_manager import init_sample_funds, create_net_value_release, run_pre_check
from approval_engine import init_approval_flow, auto_approve_all, get_approval_flow_detail
from push_manager import execute_full_grayscale_push
from monitor_rollback import (
    execute_monitor_check, trigger_compliance_rollback,
    restore_previous_stable_version, get_active_monitoring_releases
)
from rollback_exercise import create_rollback_exercise, execute_rollback_exercise
from report_generator import generate_weekly_report
from history_manager import query_release_history, export_release_history
from audit_logger import write_audit_log, query_audit_logs


def force_pass_all_prechecks(release_id):
    db = SessionLocal()
    try:
        db.query(PreCheckRecord).filter(PreCheckRecord.release_id == release_id).delete()
        check_items = [
            ('net_value_accuracy', '净值核算准确率', 0.9995, 0.999),
            ('valuation_reconciliation', '估值对账一致性', 0.00005, 0.0001),
            ('regulatory_reporting', '监管数据上报状态', 1.0, 1.0),
            ('risk_adaptation', '客户风险适配校验', 0.995, 0.98),
        ]
        for item in check_items:
            record = PreCheckRecord(
                release_id=release_id, check_item=item[0],
                check_result=True, check_value=item[2],
                check_details=f'{item[1]}: 通过'
            )
            db.add(record)
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        release.pre_check_passed = True
        release.status = 'PRE_CHECK_PASSED'
        release.pre_check_details = '[]'
        db.commit()
    finally:
        db.close()


def create_complete_release(fund_code, version, net_value, risk_level='NORMAL',
                            net_value_date=None):
    if net_value_date is None:
        net_value_date = datetime.now().strftime('%Y-%m-%d')
    result = create_net_value_release(
        fund_code=fund_code, net_value_date=net_value_date,
        net_value=net_value, accumulated_net_value=round(net_value + 1.0, 4),
        daily_growth_rate=round(random.uniform(-2, 3), 2),
        version=version, risk_level=risk_level,
        applicant="运营测试员", operator="tester"
    )
    release_id = result['release_id']
    force_pass_all_prechecks(release_id)
    init_approval_flow(release_id=release_id, operator="system")
    auto_approve_all(release_id=release_id, operator="admin")
    execute_full_grayscale_push(release_id=release_id, operator="system")
    return release_id


def print_check(name, passed, details=""):
    status = "[PASS]" if passed else "[FAIL]"
    print(f"  {status} {name}")
    if details:
        print(f"         {details}")
    return passed


def main():
    print("=" * 70)
    print("  公募基金净值发布系统 - 5项修复点验证")
    print("=" * 70)

    all_passed = True

    # 初始化
    print("\n[初始化]")
    init_db()
    init_sample_funds()
    print("  数据库初始化完成")

    # ========== 修复点3: REGULATORY审批流程 ==========
    print("\n[修复点3] 监管要求下架(REGULATORY)审批流程验证")
    reg_result = create_net_value_release(
        fund_code="000001",
        net_value_date=(datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'),
        net_value=1.0,
        accumulated_net_value=1.0,
        daily_growth_rate=0,
        version="0.0.1-REG",
        risk_level="REGULATORY",
        applicant="合规部",
        operator="test"
    )
    reg_id = reg_result['release_id']
    force_pass_all_prechecks(reg_id)
    init_approval_flow(release_id=reg_id, operator="system")
    detail = get_approval_flow_detail(release_id=reg_id)
    roles = [s['role_name'] for s in detail['approval_flow']]
    expected = ['张会计', '李合规', '王经理']
    ok = print_check(
        "REGULATORY审批人顺序正确",
        roles == expected,
        f"实际顺序: {' → '.join(roles)}"
    )
    all_passed = all_passed and ok

    # ========== 创建稳定版本和新版本（用于其他测试） ==========
    print("\n[数据准备]")
    stable_id = create_complete_release(
        fund_code="000002",
        version="1.0.0",
        net_value=1.5000,
        net_value_date=(datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    )
    db = SessionLocal()
    try:
        stable_rel = db.query(NetValueRelease).filter(NetValueRelease.id == stable_id).first()
        stable_rel.monitor_active = False  # 先关闭，稍后测试恢复后激活
        db.commit()
        print(f"  创建稳定版本: ID={stable_id}, 版本=1.0.0, 净值=1.5000")
    finally:
        db.close()

    new_id = create_complete_release(
        fund_code="000002",
        version="2.0.0",
        net_value=1.6000,
        net_value_date=(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    )
    print(f"  创建新版本: ID={new_id}, 版本=2.0.0, 净值=1.6000")

    # ========== 修复点5: 手动回退不会崩溃 ==========
    print("\n[修复点5] 已回退的发布再次回退不会崩溃")
    rb_result = trigger_compliance_rollback(
        release_id=new_id,
        trigger_reason="测试手动回退",
        trigger_source="TEST",
        operator="test_admin"
    )
    rollbacked = rb_result['success'] if 'success' in rb_result else True
    ok = print_check("第一次手动回退成功", rollbacked)
    all_passed = all_passed and ok

    # 第二次尝试回退，应该优雅处理
    try:
        rb2 = trigger_compliance_rollback(
            release_id=new_id,
            trigger_reason="再次回退测试",
            trigger_source="TEST",
            operator="test_admin"
        )
        ok = print_check("重复回退优雅处理（不崩溃）", True, f"返回: {rb2.get('message', '无消息')[:50]}")
    except Exception as e:
        ok = print_check("重复回退优雅处理", False, f"崩溃: {str(e)[:80]}")
    all_passed = all_passed and ok

    # ========== 修复点1: 恢复稳定版本 ==========
    print("\n[修复点1] 恢复上一稳定版本验证")
    restore_result = restore_previous_stable_version(release_id=new_id, operator="system")
    ok = print_check(
        "版本恢复成功",
        restore_result['success'] is True,
        f"消息: {str(restore_result.get('message', ''))[:60].replace(chr(10), ' ')}"
    )
    all_passed = all_passed and ok

    # 验证返回字段
    has_version = 'restored_version' in restore_result
    has_netvalue = 'restored_net_value' in restore_result
    has_time = 'recovery_time' in restore_result
    ok = print_check(
        "返回字段完整（版本号/净值/恢复时间）",
        has_version and has_netvalue and has_time,
        f"版本={restore_result.get('restored_version')}, "
        f"净值={restore_result.get('restored_net_value')}, "
        f"恢复时间={restore_result.get('recovery_time')}"
    )
    all_passed = all_passed and ok

    ok = print_check(
        "恢复的是正确的稳定版本",
        restore_result.get('restored_version') == '1.0.0' and
        restore_result.get('restored_net_value') == 1.5000
    )
    all_passed = all_passed and ok

    # 无稳定版本场景
    tmp_id = create_complete_release(
        fund_code="000005", version="0.9.0", net_value=1.0100,
        net_value_date=(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    )
    trigger_compliance_rollback(release_id=tmp_id, trigger_reason="测试", trigger_source="T", operator="t")
    fail_restore = restore_previous_stable_version(release_id=tmp_id, operator="system")
    ok = print_check(
        "无稳定版本时明确返回失败",
        fail_restore['success'] is False,
        f"错误码={fail_restore.get('error_code')}, 消息: {str(fail_restore.get('message', ''))[:60]}"
    )
    all_passed = all_passed and ok

    # ========== 修复点2: 恢复后监控正常 ==========
    print("\n[修复点2] 恢复后监控正常工作")
    active = get_active_monitoring_releases()
    active_ids = [a['release_id'] for a in active]
    ok = print_check(
        "稳定版本在监控列表中",
        stable_id in active_ids,
        f"当前监控中: {active_ids}"
    )
    all_passed = all_passed and ok

    # 对稳定版本执行监控检查
    monitor_ok = False
    try:
        monitor_result = execute_monitor_check(release_id=stable_id, operator="system")
        monitor_ok = monitor_result.get('success', False)
        msg = monitor_result.get('message', '')
        ok = print_check(
            "稳定版本监控检查成功（不因旧回退停止）",
            monitor_ok,
            f"返回: success={monitor_result.get('success')}, msg={msg[:50]}"
        )
    except Exception as e:
        ok = print_check("稳定版本监控检查成功", False, f"异常: {str(e)[:80]}")
    all_passed = all_passed and ok

    # ========== 修复点4: 历史记录发布时间 ==========
    print("\n[修复点4] 历史记录查询发布时间验证")
    query_result = query_release_history(
        page=1, page_size=50, date_filter_type='publish'
    )
    has_publish = all('publish_time' in item for item in query_result['data'])
    has_apply = all('apply_time' in item for item in query_result['data'])
    ok = print_check(
        "查询结果同时包含申请时间和发布时间",
        has_publish and has_apply,
        f"记录数={query_result['total']}, publish_time字段存在={has_publish}"
    )
    all_passed = all_passed and ok

    # 验证按发布时间跨天查询
    q2 = query_release_history(
        start_date=(datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d'),
        end_date=datetime.now().strftime('%Y-%m-%d'),
        date_filter_type='publish',
        page=1, page_size=10
    )
    ok = print_check(
        "按发布时间范围筛选成功",
        q2['total'] > 0,
        f"找到 {q2['total']} 条（按发布时间筛选）"
    )
    all_passed = all_passed and ok

    # 验证Excel导出
    export_result = export_release_history(
        export_format='xlsx',
        operator="tester",
        query_params={'date_filter_type': 'publish'}
    )
    ok = print_check(
        "Excel导出成功",
        export_result.get('success'),
        f"文件: {export_result.get('filename')}, 数量={export_result.get('export_count')}"
    )
    all_passed = all_passed and ok

    # ========== 最终结果 ==========
    print("\n" + "=" * 70)
    if all_passed:
        print("  [全部通过] 5项修复点验证成功！")
    else:
        print("  [存在失败] 部分修复点未通过，请检查上方输出")
    print("=" * 70)

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
