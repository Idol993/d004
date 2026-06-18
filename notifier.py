import json
from datetime import datetime
from models import SessionLocal, NotificationRecord
from config import STAKEHOLDERS


def send_notification(stakeholder_type, notification_type, content, release_id=None, rollback_id=None):
    db = SessionLocal()
    try:
        stakeholder_info = STAKEHOLDERS.get(stakeholder_type, [])
        if not stakeholder_info:
            return {'success': False, 'message': f'未找到干系人: {stakeholder_type}'}

        email = stakeholder_info[0] if len(stakeholder_info) > 0 else None
        phone = stakeholder_info[1] if len(stakeholder_info) > 1 else None

        notification = NotificationRecord(
            release_id=release_id,
            rollback_id=rollback_id,
            stakeholder_type=stakeholder_type,
            notification_type=notification_type,
            content=json.dumps(content, ensure_ascii=False)
        )
        db.add(notification)
        db.commit()

        print(f"[通知] {stakeholder_type} ({email}/{phone}): {content.get('subject', notification_type)}")

        return {
            'success': True,
            'stakeholder_type': stakeholder_type,
            'email': email,
            'phone': phone,
            'notification_type': notification_type,
            'notification_id': notification.id
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def notify_all_stakeholders(notification_type, content, release_id=None, rollback_id=None):
    results = []
    for stakeholder_type in STAKEHOLDERS.keys():
        try:
            result = send_notification(
                stakeholder_type=stakeholder_type,
                notification_type=notification_type,
                content=content,
                release_id=release_id,
                rollback_id=rollback_id
            )
            results.append(result)
        except Exception as e:
            results.append({
                'success': False,
                'stakeholder_type': stakeholder_type,
                'error': str(e)
            })
    return results


def notify_rollback_triggered(rollback_info):
    content = {
        'subject': '【紧急】净值发布合规回退通知',
        'rollback_no': rollback_info.get('rollback_no'),
        'release_no': rollback_info.get('release_no'),
        'fund_code': rollback_info.get('fund_code'),
        'trigger_reason': rollback_info.get('trigger_reason'),
        'affected_count': rollback_info.get('affected_investor_count'),
        'rollback_time': rollback_info.get('rollback_time'),
        'action_required': '请立即关注并配合处理后续事宜',
        'details': rollback_info
    }
    return notify_all_stakeholders(
        notification_type='ROLLBACK_TRIGGERED',
        content=content,
        release_id=rollback_info.get('release_id'),
        rollback_id=rollback_info.get('rollback_id')
    )


def notify_approval_pending(approval_info):
    content = {
        'subject': '净值发布审批待处理',
        'release_no': approval_info.get('release_no'),
        'fund_code': approval_info.get('fund_code'),
        'current_step': approval_info.get('current_step'),
        'total_steps': approval_info.get('total_steps'),
        'approver': approval_info.get('approver'),
        'apply_time': approval_info.get('apply_time')
    }
    return send_notification(
        stakeholder_type=approval_info.get('stakeholder_type', 'compliance'),
        notification_type='APPROVAL_PENDING',
        content=content,
        release_id=approval_info.get('release_id')
    )


def notify_push_completed(push_info):
    content = {
        'subject': '净值发布推送完成通知',
        'release_no': push_info.get('release_no'),
        'fund_code': push_info.get('fund_code'),
        'institution_success': push_info.get('institution_success'),
        'personal_success': push_info.get('personal_success'),
        'monitor_active': push_info.get('monitor_active'),
        'push_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    return send_notification(
        stakeholder_type='fund_operation',
        notification_type='PUSH_COMPLETED',
        content=content,
        release_id=push_info.get('release_id')
    )


def notify_report_generated(report_info):
    content = {
        'subject': '每周净值发布统计报告已生成',
        'report_week': report_info.get('report_week'),
        'success_rate': report_info.get('success_rate'),
        'rollback_count': report_info.get('rollback_count'),
        'avg_approval_time': report_info.get('avg_approval_time'),
        'pdf_path': report_info.get('pdf_path'),
        'excel_path': report_info.get('excel_path')
    }
    return notify_all_stakeholders(
        notification_type='REPORT_GENERATED',
        content=content
    )
