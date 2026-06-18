import os
import json
import random
from datetime import datetime, timedelta
from models import (
    SessionLocal, NetValueRelease, MonitorRecord,
    RollbackRecord, PushRecord
)
from config import MONITOR_THRESHOLDS, REPORT_PATH
from audit_logger import audit_operation, write_audit_log
from notifier import notify_rollback_triggered


def generate_monitor_metrics():
    accuracy_rate = round(random.uniform(0.95, 1.0), 4)
    access_error_rate = round(random.uniform(0.0, 0.05), 4)
    trade_failure_rate = round(random.uniform(0.0, 0.03), 4)

    if random.random() < 0.1:
        accuracy_rate = round(random.uniform(0.90, 0.98), 4)
    if random.random() < 0.05:
        access_error_rate = round(random.uniform(0.03, 0.10), 4)
    if random.random() < 0.05:
        trade_failure_rate = round(random.uniform(0.02, 0.08), 4)

    return {
        'accuracy_rate': accuracy_rate,
        'access_error_rate': access_error_rate,
        'trade_failure_rate': trade_failure_rate
    }


def check_thresholds(metrics):
    alerts = []
    if metrics['accuracy_rate'] < MONITOR_THRESHOLDS['accuracy_rate']:
        alerts.append({
            'type': 'accuracy',
            'value': metrics['accuracy_rate'],
            'threshold': MONITOR_THRESHOLDS['accuracy_rate'],
            'message': f"净值展示准确率 {metrics['accuracy_rate']*100:.2f}% 低于阈值 {MONITOR_THRESHOLDS['accuracy_rate']*100}%"
        })
    if metrics['access_error_rate'] > MONITOR_THRESHOLDS['access_error_rate']:
        alerts.append({
            'type': 'access',
            'value': metrics['access_error_rate'],
            'threshold': MONITOR_THRESHOLDS['access_error_rate'],
            'message': f"客户访问异常率 {metrics['access_error_rate']*100:.2f}% 超过阈值 {MONITOR_THRESHOLDS['access_error_rate']*100}%"
        })
    if metrics['trade_failure_rate'] > MONITOR_THRESHOLDS['trade_failure_rate']:
        alerts.append({
            'type': 'trade',
            'value': metrics['trade_failure_rate'],
            'threshold': MONITOR_THRESHOLDS['trade_failure_rate'],
            'message': f"交易下单失败率 {metrics['trade_failure_rate']*100:.2f}% 超过阈值 {MONITOR_THRESHOLDS['trade_failure_rate']*100}%"
        })
    return alerts


@audit_operation('MONITOR_CHECK', 'NetValueRelease')
def execute_monitor_check(release_id, operator='system'):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            raise ValueError(f"净值发布记录不存在: {release_id}")

        if not release.monitor_active:
            return {'success': False, 'message': '监控未激活'}

        if release.rollback_triggered:
            return {'success': False, 'message': '已触发回退，监控停止'}

        metrics = generate_monitor_metrics()
        alerts = check_thresholds(metrics)

        monitor_record = MonitorRecord(
            release_id=release_id,
            accuracy_rate=metrics['accuracy_rate'],
            access_error_rate=metrics['access_error_rate'],
            trade_failure_rate=metrics['trade_failure_rate'],
            accuracy_alert=any(a['type'] == 'accuracy' for a in alerts),
            access_alert=any(a['type'] == 'access' for a in alerts),
            trade_alert=any(a['type'] == 'trade' for a in alerts),
            triggered_rollback=False,
            details=json.dumps(alerts, ensure_ascii=False) if alerts else None
        )
        db.add(monitor_record)
        db.commit()
        db.refresh(monitor_record)

        if alerts:
            monitor_record.triggered_rollback = True
            db.commit()

            rollback_reason = '; '.join([a['message'] for a in alerts])
            rollback_result = trigger_compliance_rollback(
                release_id=release_id,
                trigger_reason=rollback_reason,
                trigger_source='AUTO_MONITOR',
                operator=operator
            )

            return {
                'success': True,
                'release_id': release_id,
                'metrics': metrics,
                'alerts': alerts,
                'rollback_triggered': True,
                'rollback_result': rollback_result,
                'message': f"监控发现异常，已触发回退: {rollback_reason}"
            }

        return {
            'success': True,
            'release_id': release_id,
            'metrics': metrics,
            'alerts': [],
            'rollback_triggered': False,
            'message': '监控正常，未发现异常'
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def get_previous_stable_version(db, fund_code, current_version):
    previous_release = db.query(NetValueRelease).filter(
        NetValueRelease.fund_code == fund_code,
        NetValueRelease.status == 'PUBLISHED',
        NetValueRelease.rollback_triggered == False,
        NetValueRelease.version != current_version
    ).order_by(NetValueRelease.net_value_date.desc()).first()

    return previous_release.version if previous_release else '1.0.0'


def analyze_net_value_diff(db, release_id):
    release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
    if not release:
        return None

    previous_release = db.query(NetValueRelease).filter(
        NetValueRelease.fund_code == release.fund_code,
        NetValueRelease.id != release_id,
        NetValueRelease.status.in_(['PUBLISHED', 'ROLLBACKED'])
    ).order_by(NetValueRelease.net_value_date.desc()).first()

    if previous_release:
        diff = release.net_value - previous_release.net_value
        diff_reasons = [
            '估值模型参数调整导致计算偏差',
            '交易系统数据同步延迟',
            '持仓估值定价差异',
            '费用计提计算错误',
            '汇率波动影响（QDII基金）'
        ]
        return {
            'previous_net_value': previous_release.net_value,
            'current_net_value': release.net_value,
            'net_value_diff': round(diff, 4),
            'diff_reason': random.choice(diff_reasons),
            'previous_version': previous_release.version
        }
    return {
        'previous_net_value': None,
        'current_net_value': release.net_value,
        'net_value_diff': 0,
        'diff_reason': '首次发布，无历史对比数据',
        'previous_version': None
    }


def generate_rollback_report(rollback_record, release, push_records, diff_analysis):
    institution_count = sum(p.affected_count for p in push_records if p.investor_type == 'INSTITUTION')
    personal_count = sum(p.affected_count for p in push_records if p.investor_type == 'PERSONAL')
    total_count = institution_count + personal_count

    compliance_statement = f"""
合规回退说明：
1. 本次回退符合《公开募集证券投资基金信息披露管理办法》相关规定
2. 回退触发原因：{rollback_record.trigger_reason}
3. 已及时通知所有受影响投资者，并启动客户安抚预案
4. 估值核算团队已启动净值复核，预计3个工作日内完成修正
5. 本次回退不影响投资者实际资产安全，相关数据已备份待查
6. 已向证监会派出机构报告本次回退事件
    """

    report_content = {
        'rollback_no': rollback_record.rollback_no,
        'release_no': release.release_no,
        'fund_code': release.fund_code,
        'net_value_date': release.net_value_date.strftime('%Y-%m-%d'),
        'rollback_time': rollback_record.rollback_time.strftime('%Y-%m-%d %H:%M:%S'),
        'trigger_reason': rollback_record.trigger_reason,
        'trigger_source': rollback_record.trigger_source,
        'affected_investors': {
            'total': total_count,
            'institution': institution_count,
            'personal': personal_count
        },
        'net_value_analysis': diff_analysis,
        'compliance_statement': compliance_statement.strip(),
        'recovery_version': rollback_record.previous_version,
        'status': rollback_record.rollback_status
    }

    report_path = os.path.join(REPORT_PATH, f"rollback_report_{rollback_record.rollback_no}.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report_content, f, ensure_ascii=False, indent=2)

    return report_path, report_content


@audit_operation('TRIGGER_ROLLBACK', 'NetValueRelease')
def trigger_compliance_rollback(release_id, trigger_reason, trigger_source='MANUAL', operator='system'):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            raise ValueError(f"净值发布记录不存在: {release_id}")

        if release.rollback_triggered:
            return {'success': False, 'message': '该发布已触发回退'}

        push_records = db.query(PushRecord).filter(
            PushRecord.release_id == release_id
        ).all()

        institution_count = sum(p.affected_count for p in push_records if p.investor_type == 'INSTITUTION')
        personal_count = sum(p.affected_count for p in push_records if p.investor_type == 'PERSONAL')
        total_count = institution_count + personal_count

        diff_analysis = analyze_net_value_diff(db, release_id)
        previous_version = get_previous_stable_version(db, release.fund_code, release.version)

        rollback_no = f"RB-{release.fund_code}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        rollback_record = RollbackRecord(
            release_id=release_id,
            rollback_no=rollback_no,
            trigger_reason=trigger_reason,
            trigger_source=trigger_source,
            affected_investor_count=total_count,
            affected_institution_count=institution_count,
            affected_personal_count=personal_count,
            net_value_diff=diff_analysis.get('net_value_diff', 0),
            diff_reason=diff_analysis.get('diff_reason', ''),
            previous_version=previous_version,
            rollback_status='COMPLETED'
        )
        db.add(rollback_record)
        db.commit()
        db.refresh(rollback_record)

        report_path, report_content = generate_rollback_report(
            rollback_record, release, push_records, diff_analysis
        )
        rollback_record.report_path = report_path
        rollback_record.report_generated = True
        rollback_record.compliance_statement = report_content['compliance_statement']

        release.rollback_triggered = True
        release.rollback_reason = trigger_reason
        release.rollback_time = datetime.now()
        release.monitor_active = False
        release.status = 'ROLLBACKED'
        release.previous_stable_version = previous_version

        db.commit()

        rollback_info = {
            'rollback_id': rollback_record.id,
            'rollback_no': rollback_no,
            'release_id': release_id,
            'release_no': release.release_no,
            'fund_code': release.fund_code,
            'trigger_reason': trigger_reason,
            'trigger_source': trigger_source,
            'affected_investor_count': total_count,
            'affected_institution_count': institution_count,
            'affected_personal_count': personal_count,
            'previous_version': previous_version,
            'rollback_time': rollback_record.rollback_time.strftime('%Y-%m-%d %H:%M:%S'),
            'report_path': report_path
        }

        notify_rollback_triggered(rollback_info)

        return {
            'success': True,
            'rollback_info': rollback_info,
            'report_content': report_content,
            'message': '合规回退已完成，已通知所有干系人'
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


@audit_operation('RESTORE_PREVIOUS_VERSION', 'NetValueRelease')
def restore_previous_stable_version(release_id, operator='system'):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            raise ValueError(f"净值发布记录不存在: {release_id}")

        if not release.rollback_triggered:
            return {
                'success': False,
                'release_id': release_id,
                'error_code': 'NO_ROLLBACK',
                'message': f'[失败] 该发布(ID={release_id})未触发回退，无需执行版本恢复'
            }

        stable_release = db.query(NetValueRelease).filter(
            NetValueRelease.fund_code == release.fund_code,
            NetValueRelease.id != release_id,
            NetValueRelease.status == 'PUBLISHED',
            NetValueRelease.rollback_triggered == False
        ).order_by(NetValueRelease.publish_time.desc() if NetValueRelease.publish_time != None else NetValueRelease.apply_time.desc()).first()

        if not stable_release:
            return {
                'success': False,
                'release_id': release_id,
                'fund_code': release.fund_code,
                'error_code': 'NO_STABLE_VERSION',
                'message': f'[失败] 基金 {release.fund_code} 未找到已发布且未回退的上一稳定版本，无法执行恢复。请先完成一次成功的净值发布。'
            }

        recovery_time = datetime.now()
        release.previous_stable_version = stable_release.version
        stable_release.monitor_active = True

        write_audit_log(
            operator=operator,
            operation_type='VERSION_RESTORED',
            target_type='NetValueRelease',
            target_id=release_id,
            operation_details={
                'rollbacked_release_id': release_id,
                'rollbacked_version': release.version,
                'restored_release_id': stable_release.id,
                'restored_version': stable_release.version,
                'restored_net_value': stable_release.net_value,
                'recovery_time': recovery_time.strftime('%Y-%m-%d %H:%M:%S')
            }
        )

        db.commit()

        return {
            'success': True,
            'rollbacked_release': {
                'id': release_id,
                'release_no': release.release_no,
                'version': release.version,
                'net_value': release.net_value
            },
            'restored_stable_release': {
                'id': stable_release.id,
                'release_no': stable_release.release_no,
                'version': stable_release.version,
                'net_value': stable_release.net_value,
                'publish_time': stable_release.publish_time.strftime('%Y-%m-%d %H:%M:%S') if stable_release.publish_time else None
            },
            'restored_version': stable_release.version,
            'restored_net_value': stable_release.net_value,
            'recovery_time': recovery_time.strftime('%Y-%m-%d %H:%M:%S'),
            'monitor_restarted': True,
            'message': (
                f'[成功] 已恢复上一监管备案稳定版本\n'
                f'  稳定版本号: {stable_release.version}\n'
                f'  稳定净值:   {stable_release.net_value}\n'
                f'  发布时间:   {stable_release.publish_time.strftime("%Y-%m-%d %H:%M:%S") if stable_release.publish_time else "N/A"}\n'
                f'  恢复时间:   {recovery_time.strftime("%Y-%m-%d %H:%M:%S")}\n'
                f'  监控状态:   已激活（稳定版本ID={stable_release.id}）'
            )
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def get_monitor_history(release_id, limit=50):
    db = SessionLocal()
    try:
        records = db.query(MonitorRecord).filter(
            MonitorRecord.release_id == release_id
        ).order_by(MonitorRecord.monitor_time.desc()).limit(limit).all()

        return [
            {
                'monitor_time': r.monitor_time.strftime('%Y-%m-%d %H:%M:%S'),
                'accuracy_rate': r.accuracy_rate,
                'access_error_rate': r.access_error_rate,
                'trade_failure_rate': r.trade_failure_rate,
                'accuracy_alert': r.accuracy_alert,
                'access_alert': r.access_alert,
                'trade_alert': r.trade_alert,
                'triggered_rollback': r.triggered_rollback
            }
            for r in records
        ]
    finally:
        db.close()


def get_active_monitoring_releases():
    db = SessionLocal()
    try:
        releases = db.query(NetValueRelease).filter(
            NetValueRelease.monitor_active == True,
            NetValueRelease.rollback_triggered == False
        ).all()

        return [
            {
                'release_id': r.id,
                'release_no': r.release_no,
                'fund_code': r.fund_code,
                'net_value_date': r.net_value_date.strftime('%Y-%m-%d'),
                'net_value': r.net_value,
                'version': r.version,
                'push_status': r.push_status
            }
            for r in releases
        ]
    finally:
        db.close()
