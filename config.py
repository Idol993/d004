import os
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'fund_system.db')
AUDIT_LOG_PATH = os.path.join(BASE_DIR, 'audit_logs')
REPORT_PATH = os.path.join(BASE_DIR, 'reports')
ROLLBACK_ARCHIVE_PATH = os.path.join(BASE_DIR, 'rollback_archives')

for path in [AUDIT_LOG_PATH, REPORT_PATH, ROLLBACK_ARCHIVE_PATH]:
    os.makedirs(path, exist_ok=True)

DATABASE_URL = f'sqlite:///{DB_PATH}'

MONITOR_INTERVAL = 120
MONITOR_THRESHOLDS = {
    'accuracy_rate': 0.99,
    'access_error_rate': 0.02,
    'trade_failure_rate': 0.01
}

RISK_LEVELS = {
    'NORMAL': '常规净值披露',
    'URGENT': '紧急估值修正',
    'REGULATORY': '监管要求下架'
}

APPROVAL_FLOW = {
    'NORMAL': ['fund_accountant', 'compliance', 'investment_manager'],
    'URGENT': ['fund_accountant', 'compliance', 'investment_manager'],
    'REGULATORY': ['compliance', 'investment_manager', 'chief_risk_officer']
}

INVESTOR_GRAYSCALE = {
    'INSTITUTION': {'delay': 0, 'name': '机构客户'},
    'PERSONAL': {'delay': 30, 'name': '个人客户'}
}

PRE_CHECK_ITEMS = [
    'net_value_accuracy',
    'valuation_reconciliation',
    'regulatory_reporting',
    'risk_adaptation'
]

STAKEHOLDERS = {
    'fund_operation': ['fund_op@fund.com', '13800138001'],
    'compliance': ['compliance@fund.com', '13800138002'],
    'investment_advisor': ['advisor@fund.com', '13800138003'],
    'customer_service': ['cs@fund.com', '13800138004']
}

APPROVERS = {
    'fund_accountant': {'name': '张会计', 'email': 'zhang_accountant@fund.com'},
    'compliance': {'name': '李合规', 'email': 'li_compliance@fund.com'},
    'investment_manager': {'name': '王经理', 'email': 'wang_manager@fund.com'},
    'chief_risk_officer': {'name': '赵总监', 'email': 'zhao_cro@fund.com'}
}
