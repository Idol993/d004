from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from config import DATABASE_URL

Base = declarative_base()
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class FundProduct(Base):
    __tablename__ = 'fund_products'
    id = Column(Integer, primary_key=True, autoincrement=True)
    fund_code = Column(String(20), unique=True, nullable=False, index=True)
    fund_name = Column(String(100), nullable=False)
    fund_type = Column(String(50))
    risk_level = Column(String(20))
    manager = Column(String(50))
    created_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)


class NetValueRelease(Base):
    __tablename__ = 'net_value_releases'
    id = Column(Integer, primary_key=True, autoincrement=True)
    release_no = Column(String(50), unique=True, nullable=False, index=True)
    fund_code = Column(String(20), ForeignKey('fund_products.fund_code'), nullable=False, index=True)
    net_value_date = Column(DateTime, nullable=False, index=True)
    net_value = Column(Float, nullable=False)
    accumulated_net_value = Column(Float)
    daily_growth_rate = Column(Float)
    version = Column(String(20), nullable=False)
    risk_level = Column(String(20), nullable=False)
    status = Column(String(30), default='PENDING', index=True)
    applicant = Column(String(50), nullable=False)
    apply_time = Column(DateTime, default=datetime.now)
    publish_time = Column(DateTime, index=True)
    pre_check_passed = Column(Boolean, default=False)
    pre_check_details = Column(Text)
    current_approval_step = Column(Integer, default=0)
    approval_passed = Column(Boolean, default=False)
    push_status = Column(String(30), default='NOT_STARTED')
    push_progress = Column(String(100))
    monitor_active = Column(Boolean, default=False)
    rollback_triggered = Column(Boolean, default=False)
    rollback_reason = Column(Text)
    rollback_time = Column(DateTime)
    previous_stable_version = Column(String(20))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    approvals = relationship('ApprovalRecord', back_populates='release', cascade='all, delete-orphan')
    monitor_records = relationship('MonitorRecord', back_populates='release', cascade='all, delete-orphan')
    push_records = relationship('PushRecord', back_populates='release', cascade='all, delete-orphan')
    __table_args__ = (
        Index('idx_fund_date_version', 'fund_code', 'net_value_date', 'version', unique=True),
    )


class ApprovalRecord(Base):
    __tablename__ = 'approval_records'
    id = Column(Integer, primary_key=True, autoincrement=True)
    release_id = Column(Integer, ForeignKey('net_value_releases.id'), nullable=False, index=True)
    step = Column(Integer, nullable=False)
    role = Column(String(50), nullable=False)
    approver_name = Column(String(50), nullable=False)
    approval_result = Column(String(20))
    approval_opinion = Column(Text)
    approval_time = Column(DateTime)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    release = relationship('NetValueRelease', back_populates='approvals')


class PreCheckRecord(Base):
    __tablename__ = 'pre_check_records'
    id = Column(Integer, primary_key=True, autoincrement=True)
    release_id = Column(Integer, nullable=False, index=True)
    check_item = Column(String(50), nullable=False)
    check_result = Column(Boolean, default=False)
    check_value = Column(Float)
    check_details = Column(Text)
    checked_at = Column(DateTime, default=datetime.now)


class PushRecord(Base):
    __tablename__ = 'push_records'
    id = Column(Integer, primary_key=True, autoincrement=True)
    release_id = Column(Integer, ForeignKey('net_value_releases.id'), nullable=False, index=True)
    investor_type = Column(String(20), nullable=False)
    push_status = Column(String(30), default='PENDING')
    push_time = Column(DateTime)
    affected_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    release = relationship('NetValueRelease', back_populates='push_records')


class MonitorRecord(Base):
    __tablename__ = 'monitor_records'
    id = Column(Integer, primary_key=True, autoincrement=True)
    release_id = Column(Integer, ForeignKey('net_value_releases.id'), nullable=False, index=True)
    monitor_time = Column(DateTime, default=datetime.now, index=True)
    accuracy_rate = Column(Float)
    access_error_rate = Column(Float)
    trade_failure_rate = Column(Float)
    accuracy_alert = Column(Boolean, default=False)
    access_alert = Column(Boolean, default=False)
    trade_alert = Column(Boolean, default=False)
    triggered_rollback = Column(Boolean, default=False)
    details = Column(Text)
    release = relationship('NetValueRelease', back_populates='monitor_records')


class RollbackRecord(Base):
    __tablename__ = 'rollback_records'
    id = Column(Integer, primary_key=True, autoincrement=True)
    release_id = Column(Integer, nullable=False, index=True)
    rollback_no = Column(String(50), unique=True, nullable=False)
    trigger_reason = Column(String(100), nullable=False)
    trigger_source = Column(String(50))
    affected_investor_count = Column(Integer)
    affected_institution_count = Column(Integer)
    affected_personal_count = Column(Integer)
    net_value_diff = Column(Float)
    diff_reason = Column(Text)
    compliance_statement = Column(Text)
    rollback_time = Column(DateTime, default=datetime.now)
    previous_version = Column(String(20))
    rollback_status = Column(String(30), default='COMPLETED')
    report_generated = Column(Boolean, default=False)
    report_path = Column(String(255))


class RollbackExercise(Base):
    __tablename__ = 'rollback_exercises'
    id = Column(Integer, primary_key=True, autoincrement=True)
    exercise_no = Column(String(50), unique=True, nullable=False)
    exercise_name = Column(String(100), nullable=False)
    fund_code = Column(String(20), nullable=False)
    target_version = Column(String(20))
    exercise_plan = Column(Text)
    valuation_check_result = Column(Text)
    exercise_status = Column(String(30), default='CREATED')
    executor = Column(String(50))
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    archive_path = Column(String(255))
    created_at = Column(DateTime, default=datetime.now)


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    log_time = Column(DateTime, default=datetime.now, index=True)
    operator = Column(String(50), nullable=False)
    operation_type = Column(String(50), nullable=False, index=True)
    target_type = Column(String(50))
    target_id = Column(String(50))
    operation_details = Column(Text)
    ip_address = Column(String(50))
    user_agent = Column(String(255))
    __table_args__ = (
        Index('idx_log_time_type', 'log_time', 'operation_type'),
    )


class WeeklyReport(Base):
    __tablename__ = 'weekly_reports'
    id = Column(Integer, primary_key=True, autoincrement=True)
    report_week = Column(String(20), unique=True, nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    total_releases = Column(Integer, default=0)
    success_releases = Column(Integer, default=0)
    success_rate = Column(Float, default=0.0)
    rollback_count = Column(Integer, default=0)
    avg_approval_time = Column(Float, default=0.0)
    max_approval_time = Column(Float, default=0.0)
    min_approval_time = Column(Float, default=0.0)
    pdf_path = Column(String(255))
    excel_path = Column(String(255))
    created_at = Column(DateTime, default=datetime.now)


class NotificationRecord(Base):
    __tablename__ = 'notification_records'
    id = Column(Integer, primary_key=True, autoincrement=True)
    release_id = Column(Integer, index=True)
    rollback_id = Column(Integer, index=True)
    stakeholder_type = Column(String(50), nullable=False)
    notification_type = Column(String(50), nullable=False)
    content = Column(Text)
    sent_at = Column(DateTime, default=datetime.now)
    status = Column(String(20), default='SENT')


def init_db():
    from sqlalchemy import inspect, text
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    with engine.connect() as conn:
        columns = [col['name'] for col in inspector.get_columns('net_value_releases')]
        if 'publish_time' not in columns:
            conn.execute(text("ALTER TABLE net_value_releases ADD COLUMN publish_time DATETIME"))
            conn.commit()
            print("数据库迁移: 新增 publish_time 列")

        idx_names = [idx['name'] for idx in inspector.get_indexes('net_value_releases')]
        if 'ix_net_value_releases_publish_time' not in idx_names:
            try:
                conn.execute(text("CREATE INDEX ix_net_value_releases_publish_time ON net_value_releases (publish_time)"))
                conn.commit()
            except Exception:
                pass

    print("数据库初始化完成")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
