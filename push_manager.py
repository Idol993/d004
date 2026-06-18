import time
import random
from datetime import datetime, timedelta
from models import SessionLocal, NetValueRelease, PushRecord
from config import INVESTOR_GRAYSCALE
from audit_logger import audit_operation


def get_investor_counts(fund_code):
    return {
        'INSTITUTION': random.randint(50, 200),
        'PERSONAL': random.randint(10000, 50000)
    }


@audit_operation('START_PUSH', 'NetValueRelease')
def start_grayscale_push(release_id, operator='system'):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            raise ValueError(f"净值发布记录不存在: {release_id}")

        if release.status != 'APPROVAL_PASSED':
            raise ValueError(f"当前状态不允许推送: {release.status}")

        if release.push_status != 'NOT_STARTED':
            raise ValueError(f"推送已启动: {release.push_status}")

        investor_counts = get_investor_counts(release.fund_code)

        for investor_type in ['INSTITUTION', 'PERSONAL']:
            push_record = PushRecord(
                release_id=release_id,
                investor_type=investor_type,
                push_status='PENDING',
                affected_count=investor_counts[investor_type]
            )
            db.add(push_record)

        release.push_status = 'PUSHING'
        release.push_progress = '机构客户推送准备中'
        release.status = 'PUSHING'
        db.commit()

        return {
            'success': True,
            'release_id': release_id,
            'status': release.status,
            'push_status': release.push_status,
            'investor_counts': investor_counts,
            'message': '灰度推送已启动，首先推送给机构客户'
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def execute_push_for_investor_type(db, release_id, investor_type):
    push_record = db.query(PushRecord).filter(
        PushRecord.release_id == release_id,
        PushRecord.investor_type == investor_type
    ).first()

    if not push_record or push_record.push_status == 'COMPLETED':
        return None

    investor_config = INVESTOR_GRAYSCALE.get(investor_type, {})
    time.sleep(investor_config.get('delay', 0))

    affected_count = push_record.affected_count
    success_rate = random.uniform(0.98, 1.0)
    success_count = int(affected_count * success_rate)
    fail_count = affected_count - success_count

    push_record.push_status = 'COMPLETED'
    push_record.push_time = datetime.now()
    push_record.success_count = success_count
    push_record.fail_count = fail_count

    return {
        'investor_type': investor_type,
        'investor_name': investor_config.get('name', investor_type),
        'affected_count': affected_count,
        'success_count': success_count,
        'fail_count': fail_count,
        'success_rate': success_rate
    }


@audit_operation('EXECUTE_PUSH_INSTITUTION', 'NetValueRelease')
def push_to_institutions(release_id, operator='system'):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            raise ValueError(f"净值发布记录不存在: {release_id}")

        result = execute_push_for_investor_type(db, release_id, 'INSTITUTION')
        if not result:
            return {'success': False, 'message': '机构客户推送已完成或不存在'}

        release.push_progress = f"机构客户推送完成，成功率: {result['success_rate']*100:.2f}%"
        db.commit()

        return {
            'success': True,
            'release_id': release_id,
            'push_result': result,
            'message': f"机构客户推送完成，成功 {result['success_count']}/{result['affected_count']}"
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


@audit_operation('EXECUTE_PUSH_PERSONAL', 'NetValueRelease')
def push_to_personal(release_id, operator='system'):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            raise ValueError(f"净值发布记录不存在: {release_id}")

        inst_push = db.query(PushRecord).filter(
            PushRecord.release_id == release_id,
            PushRecord.investor_type == 'INSTITUTION'
        ).first()

        if not inst_push or inst_push.push_status != 'COMPLETED':
            raise ValueError("请先完成机构客户推送")

        result = execute_push_for_investor_type(db, release_id, 'PERSONAL')
        if not result:
            return {'success': False, 'message': '个人客户推送已完成或不存在'}

        release.push_progress = f"全部推送完成，机构: {inst_push.success_count}/{inst_push.affected_count}, 个人: {result['success_count']}/{result['affected_count']}"
        release.push_status = 'COMPLETED'
        release.status = 'PUBLISHED'
        release.monitor_active = True
        db.commit()

        return {
            'success': True,
            'release_id': release_id,
            'push_result': result,
            'status': release.status,
            'monitor_active': release.monitor_active,
            'message': f"个人客户推送完成，成功 {result['success_count']}/{result['affected_count']}，监控已启动"
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


@audit_operation('FULL_PUSH', 'NetValueRelease')
def execute_full_grayscale_push(release_id, operator='system'):
    db = SessionLocal()
    try:
        result1 = start_grayscale_push(release_id=release_id, operator=operator)
        time.sleep(1)
        result2 = push_to_institutions(release_id=release_id, operator=operator)
        time.sleep(1)
        result3 = push_to_personal(release_id=release_id, operator=operator)

        return {
            'success': True,
            'release_id': release_id,
            'institution_push': result2,
            'personal_push': result3,
            'message': '灰度推送全部完成，监控已启动'
        }
    except Exception as e:
        raise e


def get_push_status(release_id):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            return None

        push_records = db.query(PushRecord).filter(
            PushRecord.release_id == release_id
        ).all()

        return {
            'release_id': release_id,
            'release_no': release.release_no,
            'fund_code': release.fund_code,
            'status': release.status,
            'push_status': release.push_status,
            'push_progress': release.push_progress,
            'monitor_active': release.monitor_active,
            'push_records': [
                {
                    'investor_type': INVESTOR_GRAYSCALE.get(p.investor_type, {}).get('name', p.investor_type),
                    'push_status': p.push_status,
                    'push_time': p.push_time.strftime('%Y-%m-%d %H:%M:%S') if p.push_time else None,
                    'affected_count': p.affected_count,
                    'success_count': p.success_count,
                    'fail_count': p.fail_count
                }
                for p in push_records
            ]
        }
    finally:
        db.close()
