import time
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from config import MONITOR_INTERVAL
from monitor_rollback import execute_monitor_check, get_active_monitoring_releases
from report_generator import generate_weekly_report
from audit_logger import write_audit_log

logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.WARNING)


def monitor_job():
    try:
        active_releases = get_active_monitoring_releases()
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 定时监控启动，当前监控中发布数: {len(active_releases)}")

        for release in active_releases:
            try:
                result = execute_monitor_check(release_id=release['release_id'], operator='scheduler')
                if result.get('rollback_triggered'):
                    print(f"  [!] {release['release_no']} 触发回退: {result.get('message', '')}")
                else:
                    metrics = result.get('metrics', {})
                    print(f"  [OK] {release['release_no']} 准确率: {metrics.get('accuracy_rate', 0)*100:.2f}%, "
                          f"访问异常: {metrics.get('access_error_rate', 0)*100:.2f}%, "
                          f"交易失败: {metrics.get('trade_failure_rate', 0)*100:.2f}%")
            except Exception as e:
                print(f"  [ERROR] {release['release_no']} 监控失败: {str(e)}")
    except Exception as e:
        print(f"监控任务执行异常: {str(e)}")


def weekly_report_job():
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始生成每周统计报告...")
        result = generate_weekly_report(operator='scheduler')
        if result['success']:
            print(f"  报告生成成功: {result['report_week']}")
            print(f"  PDF: {result['pdf_path']}")
            print(f"  Excel: {result['excel_path']}")
            write_audit_log(
                operator='scheduler',
                operation_type='WEEKLY_REPORT_AUTO',
                operation_details=result
            )
        else:
            print(f"  报告已存在: {result.get('message', '')}")
    except Exception as e:
        print(f"每周报告任务执行异常: {str(e)}")


def start_scheduler():
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        monitor_job,
        trigger=IntervalTrigger(seconds=MONITOR_INTERVAL),
        id='net_value_monitor',
        name='净值监控任务',
        replace_existing=True
    )

    scheduler.add_job(
        weekly_report_job,
        trigger=CronTrigger(day_of_week='mon', hour=9, minute=0),
        id='weekly_report',
        name='每周报告任务',
        replace_existing=True
    )

    scheduler.start()
    print(f"调度器已启动")
    print(f"  - 净值监控: 每 {MONITOR_INTERVAL} 秒执行一次")
    print(f"  - 每周报告: 每周一 09:00 执行")
    print("按 Ctrl+C 停止调度器...\n")

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        print("\n正在停止调度器...")
        scheduler.shutdown()
        print("调度器已停止")


if __name__ == '__main__':
    start_scheduler()
