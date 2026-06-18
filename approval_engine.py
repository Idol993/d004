import json
from datetime import datetime
from models import SessionLocal, NetValueRelease, ApprovalRecord
from config import APPROVAL_FLOW, APPROVERS, RISK_LEVELS
from audit_logger import audit_operation


@audit_operation('INIT_APPROVAL_FLOW', 'NetValueRelease')
def init_approval_flow(release_id, operator='system'):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            raise ValueError(f"净值发布记录不存在: {release_id}")

        if release.status != 'PRE_CHECK_PASSED':
            raise ValueError(f"当前状态不允许启动审批流程: {release.status}")

        risk_level = release.risk_level
        approval_steps = APPROVAL_FLOW.get(risk_level, APPROVAL_FLOW['NORMAL'])

        for step, role in enumerate(approval_steps, 1):
            approver_info = APPROVERS.get(role, {})
            approval_record = ApprovalRecord(
                release_id=release_id,
                step=step,
                role=role,
                approver_name=approver_info.get('name', '待分配'),
                is_active=True
            )
            db.add(approval_record)

        release.status = 'APPROVING'
        release.current_approval_step = 1
        db.commit()

        return {
            'success': True,
            'release_id': release_id,
            'status': release.status,
            'current_step': 1,
            'total_steps': len(approval_steps),
            'approval_flow': [
                {
                    'step': step,
                    'role': role,
                    'approver': APPROVERS.get(role, {}).get('name', '待分配'),
                    'status': 'PENDING'
                }
                for step, role in enumerate(approval_steps, 1)
            ],
            'message': f"审批流程已启动，风险级别: {RISK_LEVELS.get(risk_level, risk_level)}"
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def get_current_approval(release_id):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            return None

        approval = db.query(ApprovalRecord).filter(
            ApprovalRecord.release_id == release_id,
            ApprovalRecord.step == release.current_approval_step,
            ApprovalRecord.is_active == True
        ).first()

        return approval
    finally:
        db.close()


@audit_operation('APPROVE', 'NetValueRelease')
def process_approval(release_id, approval_result, approval_opinion='', operator='system'):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            raise ValueError(f"净值发布记录不存在: {release_id}")

        if release.status != 'APPROVING':
            raise ValueError(f"当前状态不允许审批: {release.status}")

        current_approval = db.query(ApprovalRecord).filter(
            ApprovalRecord.release_id == release_id,
            ApprovalRecord.step == release.current_approval_step,
            ApprovalRecord.is_active == True
        ).first()

        if not current_approval:
            raise ValueError("当前审批节点不存在")

        current_approval.approval_result = 'PASSED' if approval_result else 'REJECTED'
        current_approval.approval_opinion = approval_opinion
        current_approval.approval_time = datetime.now()
        current_approval.is_active = False

        if not approval_result:
            release.status = 'APPROVAL_REJECTED'
            release.approval_passed = False
            db.commit()
            return {
                'success': False,
                'release_id': release_id,
                'status': release.status,
                'current_step': release.current_approval_step,
                'message': '审批被驳回，流程终止'
            }

        risk_level = release.risk_level
        approval_steps = APPROVAL_FLOW.get(risk_level, APPROVAL_FLOW['NORMAL'])
        total_steps = len(approval_steps)

        if release.current_approval_step >= total_steps:
            release.status = 'APPROVAL_PASSED'
            release.approval_passed = True
            db.commit()
            return {
                'success': True,
                'release_id': release_id,
                'status': release.status,
                'current_step': release.current_approval_step,
                'total_steps': total_steps,
                'message': '全部审批通过，可以进入推送阶段'
            }
        else:
            release.current_approval_step += 1
            next_approval = db.query(ApprovalRecord).filter(
                ApprovalRecord.release_id == release_id,
                ApprovalRecord.step == release.current_approval_step
            ).first()
            if next_approval:
                next_approval.is_active = True

            db.commit()
            return {
                'success': True,
                'release_id': release_id,
                'status': release.status,
                'current_step': release.current_approval_step,
                'total_steps': total_steps,
                'next_approver': APPROVERS.get(approval_steps[release.current_approval_step - 1], {}).get('name'),
                'message': f'审批通过，进入下一级审批（第{release.current_approval_step}/{total_steps}步）'
            }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


@audit_operation('APPROVE_ALL', 'NetValueRelease')
def auto_approve_all(release_id, operator='system'):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            raise ValueError(f"净值发布记录不存在: {release_id}")

        if release.status != 'APPROVING':
            raise ValueError(f"当前状态不允许自动审批: {release.status}")

        risk_level = release.risk_level
        approval_steps = APPROVAL_FLOW.get(risk_level, APPROVAL_FLOW['NORMAL'])
        total_steps = len(approval_steps)

        for step, role in enumerate(approval_steps, 1):
            approval = db.query(ApprovalRecord).filter(
                ApprovalRecord.release_id == release_id,
                ApprovalRecord.step == step
            ).first()

            if approval:
                approval.approval_result = 'PASSED'
                approval.approval_opinion = f'系统自动审批通过（{role}）'
                approval.approval_time = datetime.now()
                approval.is_active = False

        release.current_approval_step = total_steps
        release.status = 'APPROVAL_PASSED'
        release.approval_passed = True
        db.commit()

        return {
            'success': True,
            'release_id': release_id,
            'status': release.status,
            'total_steps': total_steps,
            'message': '全部审批已自动通过'
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def get_approval_flow_detail(release_id):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            return None

        approvals = db.query(ApprovalRecord).filter(
            ApprovalRecord.release_id == release_id
        ).order_by(ApprovalRecord.step).all()

        risk_level = release.risk_level
        approval_steps = APPROVAL_FLOW.get(risk_level, APPROVAL_FLOW['NORMAL'])

        flow_detail = []
        for step, role in enumerate(approval_steps, 1):
            approval = next((a for a in approvals if a.step == step), None)
            approver_info = APPROVERS.get(role, {})

            status = 'PENDING'
            if approval and approval.approval_result:
                status = approval.approval_result
            elif release.current_approval_step == step and release.status == 'APPROVING':
                status = 'CURRENT'

            flow_detail.append({
                'step': step,
                'role': role,
                'role_name': approver_info.get('name', role),
                'email': approver_info.get('email'),
                'status': status,
                'approval_result': approval.approval_result if approval else None,
                'approval_opinion': approval.approval_opinion if approval else None,
                'approval_time': approval.approval_time.strftime('%Y-%m-%d %H:%M:%S') if approval and approval.approval_time else None
            })

        return {
            'release_id': release_id,
            'release_no': release.release_no,
            'fund_code': release.fund_code,
            'risk_level': RISK_LEVELS.get(risk_level, risk_level),
            'status': release.status,
            'current_step': release.current_approval_step,
            'total_steps': len(approval_steps),
            'approval_flow': flow_detail
        }
    finally:
        db.close()
