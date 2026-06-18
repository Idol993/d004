import os
import json
from datetime import datetime
import pandas as pd
from models import SessionLocal, NetValueRelease, FundProduct, ApprovalRecord, PushRecord
from config import REPORT_PATH, RISK_LEVELS
from audit_logger import audit_operation


STATUS_MAP = {
    'PENDING': '待前置检查',
    'PRE_CHECK_PASSED': '前置检查通过',
    'PRE_CHECK_FAILED': '前置检查未通过',
    'APPROVING': '审批中',
    'APPROVAL_PASSED': '审批通过',
    'APPROVAL_REJECTED': '审批驳回',
    'PUSHING': '推送中',
    'PUBLISHED': '已发布',
    'ROLLBACKED': '已回退',
    'CANCELLED': '已取消'
}


def query_release_history(fund_code=None, start_date=None, end_date=None,
                          publish_start_date=None, publish_end_date=None,
                          net_value_date=None, version=None, status=None,
                          page=1, page_size=50, date_filter_type='publish'):
    db = SessionLocal()
    try:
        query = db.query(NetValueRelease).order_by(
            NetValueRelease.publish_time.desc().nullslast() if date_filter_type == 'publish' else NetValueRelease.apply_time.desc()
        )

        if fund_code:
            query = query.filter(NetValueRelease.fund_code == fund_code)
        if date_filter_type == 'apply':
            if start_date:
                if isinstance(start_date, str):
                    start_date = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(NetValueRelease.apply_time >= start_date)
            if end_date:
                if isinstance(end_date, str):
                    end_date = datetime.strptime(end_date, '%Y-%m-%d')
                end_date = end_date.replace(hour=23, minute=59, second=59)
                query = query.filter(NetValueRelease.apply_time <= end_date)
        else:
            if publish_start_date or start_date:
                actual_start = publish_start_date if publish_start_date else start_date
                if isinstance(actual_start, str):
                    actual_start = datetime.strptime(actual_start, '%Y-%m-%d')
                query = query.filter(
                    (NetValueRelease.publish_time >= actual_start) |
                    (NetValueRelease.publish_time == None)
                )
            if publish_end_date or end_date:
                actual_end = publish_end_date if publish_end_date else end_date
                if isinstance(actual_end, str):
                    actual_end = datetime.strptime(actual_end, '%Y-%m-%d')
                actual_end = actual_end.replace(hour=23, minute=59, second=59)
                query = query.filter(
                    (NetValueRelease.publish_time <= actual_end) |
                    (NetValueRelease.publish_time == None)
                )
        if net_value_date:
            if isinstance(net_value_date, str):
                net_value_date = datetime.strptime(net_value_date, '%Y-%m-%d')
            query = query.filter(NetValueRelease.net_value_date == net_value_date)
        if version:
            query = query.filter(NetValueRelease.version == version)
        if status:
            query = query.filter(NetValueRelease.status == status)

        total = query.count()
        releases = query.offset((page - 1) * page_size).limit(page_size).all()

        fund_map = {}
        for fund in db.query(FundProduct).all():
            fund_map[fund.fund_code] = fund.fund_name

        results = []
        for release in releases:
            approval_count = db.query(ApprovalRecord).filter(
                ApprovalRecord.release_id == release.id,
                ApprovalRecord.approval_result == 'PASSED'
            ).count()
            total_approvals = db.query(ApprovalRecord).filter(
                ApprovalRecord.release_id == release.id
            ).count()

            push_success = db.query(PushRecord).filter(
                PushRecord.release_id == release.id,
                PushRecord.push_status == 'COMPLETED'
            ).count()

            results.append({
                'release_id': release.id,
                'release_no': release.release_no,
                'fund_code': release.fund_code,
                'fund_name': fund_map.get(release.fund_code, release.fund_code),
                'net_value_date': release.net_value_date.strftime('%Y-%m-%d'),
                'net_value': release.net_value,
                'accumulated_net_value': release.accumulated_net_value,
                'daily_growth_rate': release.daily_growth_rate,
                'version': release.version,
                'risk_level': RISK_LEVELS.get(release.risk_level, release.risk_level),
                'status': STATUS_MAP.get(release.status, release.status),
                'status_code': release.status,
                'applicant': release.applicant,
                'apply_time': release.apply_time.strftime('%Y-%m-%d %H:%M:%S'),
                'publish_time': release.publish_time.strftime('%Y-%m-%d %H:%M:%S') if release.publish_time else None,
                'pre_check_passed': release.pre_check_passed,
                'approval_progress': f'{approval_count}/{total_approvals}' if total_approvals > 0 else '未开始',
                'approval_passed': release.approval_passed,
                'push_status': release.push_status,
                'push_success': push_success,
                'monitor_active': release.monitor_active,
                'rollback_triggered': release.rollback_triggered,
                'rollback_reason': release.rollback_reason,
                'rollback_time': release.rollback_time.strftime('%Y-%m-%d %H:%M:%S') if release.rollback_time else None,
                'previous_stable_version': release.previous_stable_version
            })

        return {
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size,
            'date_filter_type': date_filter_type,
            'data': results
        }
    finally:
        db.close()


def get_release_full_detail(release_id):
    db = SessionLocal()
    try:
        release = db.query(NetValueRelease).filter(NetValueRelease.id == release_id).first()
        if not release:
            return None

        fund = db.query(FundProduct).filter(FundProduct.fund_code == release.fund_code).first()
        approvals = db.query(ApprovalRecord).filter(
            ApprovalRecord.release_id == release_id
        ).order_by(ApprovalRecord.step).all()
        push_records = db.query(PushRecord).filter(
            PushRecord.release_id == release_id
        ).all()

        pre_check_details = []
        if release.pre_check_details:
            try:
                pre_check_details = json.loads(release.pre_check_details)
            except:
                pre_check_details = []

        return {
            'basic_info': {
                'release_id': release.id,
                'release_no': release.release_no,
                'fund_code': release.fund_code,
                'fund_name': fund.fund_name if fund else release.fund_code,
                'fund_type': fund.fund_type if fund else None,
                'net_value_date': release.net_value_date.strftime('%Y-%m-%d'),
                'net_value': release.net_value,
                'accumulated_net_value': release.accumulated_net_value,
                'daily_growth_rate': release.daily_growth_rate,
                'version': release.version,
                'risk_level': RISK_LEVELS.get(release.risk_level, release.risk_level),
                'status': STATUS_MAP.get(release.status, release.status),
                'applicant': release.applicant,
                'apply_time': release.apply_time.strftime('%Y-%m-%d %H:%M:%S')
            },
            'pre_check': {
                'passed': release.pre_check_passed,
                'details': pre_check_details
            },
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
            ],
            'push_records': [
                {
                    'investor_type': p.investor_type,
                    'push_status': p.push_status,
                    'push_time': p.push_time.strftime('%Y-%m-%d %H:%M:%S') if p.push_time else None,
                    'affected_count': p.affected_count,
                    'success_count': p.success_count,
                    'fail_count': p.fail_count
                }
                for p in push_records
            ],
            'monitor': {
                'monitor_active': release.monitor_active,
                'rollback_triggered': release.rollback_triggered,
                'rollback_reason': release.rollback_reason,
                'rollback_time': release.rollback_time.strftime('%Y-%m-%d %H:%M:%S') if release.rollback_time else None
            }
        }
    finally:
        db.close()


@audit_operation('EXPORT_HISTORY', 'NetValueRelease')
def export_release_history(query_params=None, export_format='xlsx', operator='system'):
    if query_params is None:
        query_params = {}

    query_params['page'] = 1
    query_params['page_size'] = 10000
    result = query_release_history(**query_params)

    if result['total'] == 0:
        return {'success': False, 'message': '没有可导出的数据'}

    df = pd.DataFrame(result['data'])

    export_columns = [
        'release_no', 'fund_code', 'fund_name', 'net_value_date',
        'net_value', 'accumulated_net_value', 'daily_growth_rate',
        'version', 'risk_level', 'status', 'applicant', 'apply_time', 'publish_time',
        'pre_check_passed', 'approval_progress', 'approval_passed',
        'push_status', 'rollback_triggered', 'rollback_reason', 'rollback_time'
    ]
    df_export = df[export_columns].copy()

    df_export.columns = [
        '发布编号', '基金代码', '基金名称', '净值日期',
        '单位净值', '累计净值', '日增长率(%)',
        '版本号', '风险级别', '状态', '申请人', '申请时间', '发布时间',
        '前置检查通过', '审批进度', '审批通过',
        '推送状态', '是否回退', '回退原因', '回退时间'
    ]

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"release_history_{timestamp}"

    if export_format == 'xlsx':
        filepath = os.path.join(REPORT_PATH, f"{filename}.xlsx")
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            df_export.to_excel(writer, sheet_name='净值发布记录', index=False)

            workbook = writer.book
            worksheet = writer.sheets['净值发布记录']
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 40)
                worksheet.column_dimensions[column_letter].width = adjusted_width

    elif export_format == 'csv':
        filepath = os.path.join(REPORT_PATH, f"{filename}.csv")
        df_export.to_csv(filepath, index=False, encoding='utf-8-sig')

    elif export_format == 'json':
        filepath = os.path.join(REPORT_PATH, f"{filename}.json")
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(result['data'], f, ensure_ascii=False, indent=2)
    else:
        raise ValueError(f"不支持的导出格式: {export_format}")

    return {
        'success': True,
        'export_count': result['total'],
        'format': export_format,
        'filepath': filepath,
        'filename': os.path.basename(filepath),
        'message': f"成功导出 {result['total']} 条记录"
    }


def get_statistics_summary():
    db = SessionLocal()
    try:
        total_releases = db.query(NetValueRelease).count()
        published = db.query(NetValueRelease).filter(NetValueRelease.status == 'PUBLISHED').count()
        rollbacked = db.query(NetValueRelease).filter(NetValueRelease.rollback_triggered == True).count()
        pending = db.query(NetValueRelease).filter(NetValueRelease.status.in_(['PENDING', 'APPROVING', 'PUSHING'])).count()

        success_rate = (published / total_releases * 100) if total_releases > 0 else 0
        rollback_rate = (rollbacked / total_releases * 100) if total_releases > 0 else 0

        return {
            'total_releases': total_releases,
            'published': published,
            'rollbacked': rollbacked,
            'pending': pending,
            'success_rate': round(success_rate, 2),
            'rollback_rate': round(rollback_rate, 2),
            'status_distribution': {
                STATUS_MAP.get(s, s): c
                for s, c in db.query(
                    NetValueRelease.status,
                    db.func.count(NetValueRelease.id)
                ).group_by(NetValueRelease.status).all()
            }
        }
    finally:
        db.close()
