import os
import json
import logging
from datetime import datetime
from functools import wraps
from config import AUDIT_LOG_PATH
from models import AuditLog, SessionLocal

file_handler = logging.FileHandler(
    os.path.join(AUDIT_LOG_PATH, f'audit_{datetime.now().strftime("%Y%m")}.log')
)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

audit_logger = logging.getLogger('audit')
audit_logger.setLevel(logging.INFO)
audit_logger.addHandler(file_handler)
audit_logger.propagate = False


def write_audit_log(operator, operation_type, target_type=None, target_id=None,
                    operation_details=None, ip_address=None, user_agent=None):
    db = SessionLocal()
    try:
        details_json = json.dumps(operation_details, ensure_ascii=False) if isinstance(operation_details, dict) else str(operation_details)

        log_entry = AuditLog(
            log_time=datetime.now(),
            operator=operator,
            operation_type=operation_type,
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
            operation_details=details_json,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.add(log_entry)
        db.commit()

        log_message = f"[{operator}] {operation_type} - {target_type or ''}:{target_id or ''} - {details_json[:200]}"
        audit_logger.info(log_message)

        return log_entry.id
    except Exception as e:
        db.rollback()
        audit_logger.error(f"审计日志写入失败: {str(e)}")
        raise
    finally:
        db.close()


def audit_operation(operation_type, target_type=None, operator_arg='operator'):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            operator = kwargs.get(operator_arg, 'system')
            target_id = kwargs.get('release_id') or kwargs.get('exercise_id') or kwargs.get('fund_code')

            details = {k: v for k, v in kwargs.items() if k not in [operator_arg, 'db']}

            try:
                result = func(*args, **kwargs)
                write_audit_log(
                    operator=operator,
                    operation_type=operation_type,
                    target_type=target_type,
                    target_id=target_id,
                    operation_details=details
                )
                return result
            except Exception as e:
                details['error'] = str(e)
                write_audit_log(
                    operator=operator,
                    operation_type=f"{operation_type}_FAILED",
                    target_type=target_type,
                    target_id=target_id,
                    operation_details=details
                )
                raise
        return wrapper
    return decorator


def query_audit_logs(start_time=None, end_time=None, operation_type=None,
                     operator=None, target_type=None, target_id=None, page=1, page_size=100):
    db = SessionLocal()
    try:
        query = db.query(AuditLog).order_by(AuditLog.log_time.desc())

        if start_time:
            query = query.filter(AuditLog.log_time >= start_time)
        if end_time:
            query = query.filter(AuditLog.log_time <= end_time)
        if operation_type:
            query = query.filter(AuditLog.operation_type == operation_type)
        if operator:
            query = query.filter(AuditLog.operator == operator)
        if target_type:
            query = query.filter(AuditLog.target_type == target_type)
        if target_id:
            query = query.filter(AuditLog.target_id == str(target_id))

        total = query.count()
        logs = query.offset((page - 1) * page_size).limit(page_size).all()

        return {
            'total': total,
            'page': page,
            'page_size': page_size,
            'data': [
                {
                    'id': log.id,
                    'log_time': log.log_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'operator': log.operator,
                    'operation_type': log.operation_type,
                    'target_type': log.target_type,
                    'target_id': log.target_id,
                    'operation_details': log.operation_details,
                    'ip_address': log.ip_address
                }
                for log in logs
            ]
        }
    finally:
        db.close()
