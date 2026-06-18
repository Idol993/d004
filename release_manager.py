import json
import random
from datetime import datetime
from models import (
    SessionLocal, NetValueRelease, PreCheckRecord,
    FundProduct, ApprovalRecord
)
from config import PRE_CHECK_ITEMS, RISK_LEVELS
from audit_logger import audit_operation, write_audit_log


def generate_release_no(fund_code, net_value_date):
    date_str = net_value_date.strftime('%Y%m%d')
    random_suffix = random.randint(1000, 9999)
    return f"NV-{fund_code}-{date_str}-{random_suffix}"


@audit_operation('CREATE_RELEASE', 'NetValueRelease')
def create_net_value_release(fund_code, net_value_date, net_value,
                             accumulated_net_value=None, daily_growth_rate=None,
                             version='1.0', risk_level='NORMAL',
                             applicant='system', operator='system'):
    db = SessionLocal()
    try:
        fund = db.query(FundProduct).filter(FundProduct.fund_code == fund_code).first()
        if not fund:
            raise ValueError(f"基金产品不存在: {fund_code}")

        if isinstance(net_value_date, str):
            net_value_date = datetime.strptime(net_value_date, '%Y-%m-%d')

        release_no = generate_release_no(fund_code, net_value_date)

        release = NetValueRelease(
            release_no=release_no,
            fund_code=fund_code,
            net_value_date=net_value_date,
            net_value=net_value,
            accumulated_net_value=accumulated_net_value,
            daily_growth_rate=daily_growth_rate,
            version=version,
            risk_level=risk_level,
            applicant=applicant,
            status='PENDING'
        )
        db.add(release)
        db.commit()
        db.refresh(release)

        return {
            'success': True,
            'release_id': release.id,
            'release_no': release_no,
            'status': release.status,
            'message': '净值发布申请创建成功'
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def check_net_value_accuracy(db, release_id):
    accuracy = round(random.uniform(0.98, 1.0), 4)
    passed = accuracy >= 0.999
    return {
        'check_item': 'net_value_accuracy',
        'check_name': '净值核算准确率',
        'check_result': passed,
        'check_value': accuracy,
        'check_details': f"净值核算准确率: {accuracy*100:.2f}%, 阈值: 99.9%"
    }


def check_valuation_reconciliation(db, release_id):
    diff = round(random.uniform(-0.0005, 0.0005), 6)
    passed = abs(diff) <= 0.0001
    return {
        'check_item': 'valuation_reconciliation',
        'check_name': '估值对账一致性',
        'check_result': passed,
        'check_value': diff,
        'check_details': f"估值差异: {diff}, 阈值: ±0.0001"
    }


def check_regulatory_reporting(db, release_id):
    reported = random.choice([True, True, True, False])
    return {
        'check_item': 'regulatory_reporting',
        'check_name': '监管数据上报状态',
        'check_result': reported,
        'check_value': 1.0 if reported else 0.0,
        'check_details': f"监管数据上报状态: {'已完成' if reported else '未完成'}"
    }


def check_risk_adaptation(db, release_id):
    adaptation_rate = round(random.uniform(0.95, 1.0), 4)
    passed = adaptation_rate >= 0.98
    return {
        'check_item': 'risk_adaptation',
        'check_name': '客户风险适配校验',
        'check_result': passed,
        'check_value': adaptation_rate,
        'check_details': f"客户风险适配率: {adaptation_rate*100:.2f}%, 阈值: 98%"
    }


CHECK_FUNCTIONS = {
    'net_value_accuracy': check_net_value_accuracy,
    'valuation_reconciliation': check_valuation_reconciliation,
    'regulatory_reporting': check_regulatory_reporting,
    'risk_adaptation': check_risk_adaptation
}


@audit_operation('PRE_CHECK', 'NetValueRelease')
def run_pre_check(release_id, operator='system'):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            raise ValueError(f"净值发布记录不存在: {release_id}")

        if release.status != 'PENDING':
            raise ValueError(f"当前状态不允许执行前置检查: {release.status}")

        check_results = []
        all_passed = True

        for check_item in PRE_CHECK_ITEMS:
            check_func = CHECK_FUNCTIONS.get(check_item)
            if check_func:
                result = check_func(db, release_id)
                check_results.append(result)

                pre_check_record = PreCheckRecord(
                    release_id=release_id,
                    check_item=result['check_item'],
                    check_result=result['check_result'],
                    check_value=result['check_value'],
                    check_details=result['check_details']
                )
                db.add(pre_check_record)

                if not result['check_result']:
                    all_passed = False

        release.pre_check_passed = all_passed
        release.pre_check_details = json.dumps(check_results, ensure_ascii=False)

        if all_passed:
            release.status = 'PRE_CHECK_PASSED'
            message = '前置检查全部通过，进入审批流程'
        else:
            release.status = 'PRE_CHECK_FAILED'
            message = '前置检查未通过'

        db.commit()

        return {
            'success': all_passed,
            'release_id': release_id,
            'status': release.status,
            'check_results': check_results,
            'message': message
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def get_release_detail(release_id):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            return None

        approvals = db.query(ApprovalRecord).filter(
            ApprovalRecord.release_id == release_id
        ).order_by(ApprovalRecord.step).all()

        return {
            'release_id': release.id,
            'release_no': release.release_no,
            'fund_code': release.fund_code,
            'net_value_date': release.net_value_date.strftime('%Y-%m-%d'),
            'net_value': release.net_value,
            'version': release.version,
            'risk_level': RISK_LEVELS.get(release.risk_level, release.risk_level),
            'status': release.status,
            'applicant': release.applicant,
            'apply_time': release.apply_time.strftime('%Y-%m-%d %H:%M:%S'),
            'pre_check_passed': release.pre_check_passed,
            'approval_passed': release.approval_passed,
            'push_status': release.push_status,
            'rollback_triggered': release.rollback_triggered,
            'approvals': [
                {
                    'step': a.step,
                    'role': a.role,
                    'approver_name': a.approver_name,
                    'approval_result': a.approval_result,
                    'approval_opinion': a.approval_opinion,
                    'approval_time': a.approval_time.strftime('%Y-%m-%d %H:%M:%S') if a.approval_time else None
                }
                for a in approvals
            ]
        }
    finally:
        db.close()


def init_sample_funds():
    db = SessionLocal()
    try:
        sample_funds = [
            {'fund_code': '000001', 'fund_name': '华夏成长混合', 'fund_type': '混合型', 'risk_level': 'R3', 'manager': '王经理'},
            {'fund_code': '000002', 'fund_name': '易方达蓝筹精选', 'fund_type': '股票型', 'risk_level': 'R4', 'manager': '张经理'},
            {'fund_code': '000003', 'fund_name': '招商中证白酒', 'fund_type': '指数型', 'risk_level': 'R4', 'manager': '侯经理'},
            {'fund_code': '000004', 'fund_name': '中欧医疗健康', 'fund_type': '混合型', 'risk_level': 'R3', 'manager': '葛经理'},
            {'fund_code': '000005', 'fund_name': '天弘余额宝', 'fund_type': '货币型', 'risk_level': 'R1', 'manager': '陈经理'},
        ]

        for fund_data in sample_funds:
            existing = db.query(FundProduct).filter(FundProduct.fund_code == fund_data['fund_code']).first()
            if not existing:
                fund = FundProduct(**fund_data)
                db.add(fund)

        db.commit()
        print("示例基金数据初始化完成")
    except Exception as e:
        db.rollback()
        print(f"示例基金数据初始化失败: {str(e)}")
    finally:
        db.close()
