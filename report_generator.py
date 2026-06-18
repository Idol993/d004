import os
import json
from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import rcParams
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from models import SessionLocal, NetValueRelease, ApprovalRecord, RollbackRecord, WeeklyReport
from config import REPORT_PATH, RISK_LEVELS
from audit_logger import audit_operation
from notifier import notify_report_generated

rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
rcParams['axes.unicode_minus'] = False


def get_weekly_statistics(start_date, end_date):
    db = SessionLocal()
    try:
        releases = db.query(NetValueRelease).filter(
            NetValueRelease.apply_time >= start_date,
            NetValueRelease.apply_time <= end_date
        ).all()

        total_releases = len(releases)
        success_releases = sum(1 for r in releases if r.status in ['PUBLISHED', 'ROLLBACKED'] and r.approval_passed)
        success_rate = (success_releases / total_releases * 100) if total_releases > 0 else 0

        rollback_count = db.query(RollbackRecord).filter(
            RollbackRecord.rollback_time >= start_date,
            RollbackRecord.rollback_time <= end_date
        ).count()

        approval_times = []
        for release in releases:
            if release.approval_passed:
                first_approval = db.query(ApprovalRecord).filter(
                    ApprovalRecord.release_id == release.id,
                    ApprovalRecord.step == 1
                ).first()
                last_approval = db.query(ApprovalRecord).filter(
                    ApprovalRecord.release_id == release.id
                ).order_by(ApprovalRecord.step.desc()).first()

                if first_approval and first_approval.approval_time and last_approval and last_approval.approval_time:
                    duration = (last_approval.approval_time - first_approval.approval_time).total_seconds() / 60
                    approval_times.append(duration)

        avg_approval_time = sum(approval_times) / len(approval_times) if approval_times else 0
        max_approval_time = max(approval_times) if approval_times else 0
        min_approval_time = min(approval_times) if approval_times else 0

        daily_data = []
        current = start_date
        while current <= end_date:
            day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = current.replace(hour=23, minute=59, second=59, microsecond=999999)

            day_releases = sum(1 for r in releases if day_start <= r.apply_time <= day_end)
            day_success = sum(1 for r in releases if day_start <= r.apply_time <= day_end and r.status in ['PUBLISHED', 'ROLLBACKED'] and r.approval_passed)
            day_rollback = db.query(RollbackRecord).filter(
                RollbackRecord.rollback_time >= day_start,
                RollbackRecord.rollback_time <= day_end
            ).count()

            daily_data.append({
                'date': current.strftime('%Y-%m-%d'),
                'total_releases': day_releases,
                'success_releases': day_success,
                'rollback_count': day_rollback,
                'success_rate': (day_success / day_releases * 100) if day_releases > 0 else 0
            })
            current += timedelta(days=1)

        risk_distribution = {}
        for risk_level in RISK_LEVELS.keys():
            count = sum(1 for r in releases if r.risk_level == risk_level)
            risk_distribution[RISK_LEVELS[risk_level]] = count

        return {
            'start_date': start_date,
            'end_date': end_date,
            'total_releases': total_releases,
            'success_releases': success_releases,
            'success_rate': success_rate,
            'rollback_count': rollback_count,
            'avg_approval_time': avg_approval_time,
            'max_approval_time': max_approval_time,
            'min_approval_time': min_approval_time,
            'daily_data': daily_data,
            'risk_distribution': risk_distribution
        }
    finally:
        db.close()


def generate_trend_charts(stats, output_dir):
    chart_paths = {}

    dates = [d['date'] for d in stats['daily_data']]
    x = range(len(dates))

    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle(f"净值发布监管趋势 ({stats['start_date'].strftime('%Y-%m-%d')} ~ {stats['end_date'].strftime('%Y-%m-%d')})", fontsize=16)

    ax1 = axes[0, 0]
    ax1.plot(x, [d['total_releases'] for d in stats['daily_data']], 'b-o', label='发布总数')
    ax1.plot(x, [d['success_releases'] for d in stats['daily_data']], 'g-s', label='成功发布')
    ax1.set_title('日发布数量趋势')
    ax1.set_xlabel('日期')
    ax1.set_ylabel('数量')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.set_xticks(x[::max(1, len(x)//7)])
    ax1.set_xticklabels([dates[i] for i in range(0, len(dates), max(1, len(dates)//7))], rotation=45)

    ax2 = axes[0, 1]
    ax2.bar(x, [d['success_rate'] for d in stats['daily_data']], color='lightgreen', alpha=0.7)
    ax2.axhline(y=stats['success_rate'], color='r', linestyle='--', label=f'周平均: {stats["success_rate"]:.1f}%')
    ax2.set_title('日发布成功率趋势 (%)')
    ax2.set_xlabel('日期')
    ax2.set_ylabel('成功率 (%)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.set_xticks(x[::max(1, len(x)//7)])
    ax2.set_xticklabels([dates[i] for i in range(0, len(dates), max(1, len(dates)//7))], rotation=45)
    ax2.set_ylim([0, 105])

    ax3 = axes[1, 0]
    if stats['daily_data'] and any(d['rollback_count'] > 0 for d in stats['daily_data']):
        ax3.bar(x, [d['rollback_count'] for d in stats['daily_data']], color='salmon', alpha=0.7)
    ax3.set_title('日回退次数趋势')
    ax3.set_xlabel('日期')
    ax3.set_ylabel('回退次数')
    ax3.grid(True, alpha=0.3)
    ax3.set_xticks(x[::max(1, len(x)//7)])
    ax3.set_xticklabels([dates[i] for i in range(0, len(dates), max(1, len(dates)//7))], rotation=45)

    ax4 = axes[1, 1]
    risk_labels = list(stats['risk_distribution'].keys())
    risk_values = list(stats['risk_distribution'].values())
    colors_pie = ['#66b3ff', '#ff9999', '#99ff99']
    if any(v > 0 for v in risk_values):
        wedges, texts, autotexts = ax4.pie(risk_values, labels=risk_labels, autopct='%1.1f%%',
                                           colors=colors_pie[:len(risk_values)], startangle=90)
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
    ax4.set_title('风险级别分布')

    plt.tight_layout()
    trends_path = os.path.join(output_dir, f"trends_{stats['start_date'].strftime('%Y%m%d')}_{stats['end_date'].strftime('%Y%m%d')}.png")
    plt.savefig(trends_path, dpi=150, bbox_inches='tight')
    plt.close()
    chart_paths['trends'] = trends_path

    return chart_paths


def generate_pdf_report(stats, chart_paths, output_path):
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                          rightMargin=2*cm, leftMargin=2*cm,
                          topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#1a365d'), spaceAfter=12, alignment=1)
    heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'], fontSize=14, textColor=colors.HexColor('#2d3748'), spaceBefore=8, spaceAfter=8)
    normal_style = ParagraphStyle('CustomNormal', parent=styles['BodyText'], fontSize=11, textColor=colors.HexColor('#4a5568'), spaceAfter=6)

    story = []

    story.append(Paragraph('公募基金净值发布周报', title_style))
    story.append(Paragraph(f"统计周期: {stats['start_date'].strftime('%Y年%m月%d日')} - {stats['end_date'].strftime('%Y年%m月%d日')}", normal_style))
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph('一、核心指标概览', heading_style))
    summary_data = [
        ['指标', '数值', '说明'],
        ['发布总数', str(stats['total_releases']), '本周提交的净值发布申请总数'],
        ['成功发布', str(stats['success_releases']), '完成全部审批并成功发布的数量'],
        ['发布成功率', f"{stats['success_rate']:.2f}%", '成功发布/发布总数'],
        ['回退次数', str(stats['rollback_count']), '触发合规回退的次数'],
        ['平均审批时长', f"{stats['avg_approval_time']:.2f} 分钟", '从首签到末签的平均时长'],
        ['最长审批时长', f"{stats['max_approval_time']:.2f} 分钟", '本周最长审批耗时'],
        ['最短审批时长', f"{stats['min_approval_time']:.2f} 分钟", '本周最短审批耗时'],
    ]

    summary_table = Table(summary_data, colWidths=[5*cm, 4*cm, 7*cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4299e1')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f7fafc')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f7fafc'), colors.HexColor('#edf2f7')]),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.8*cm))

    story.append(Paragraph('二、监管趋势图表', heading_style))
    if 'trends' in chart_paths:
        img = Image(chart_paths['trends'], width=17*cm, height=11*cm)
        story.append(img)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph('三、风险级别分布', heading_style))
    risk_data = [['风险级别', '数量', '占比']]
    total = sum(stats['risk_distribution'].values()) or 1
    for label, count in stats['risk_distribution'].items():
        risk_data.append([label, str(count), f"{count/total*100:.1f}%"])

    risk_table = Table(risk_data, colWidths=[6*cm, 4*cm, 4*cm])
    risk_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#48bb78')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    story.append(risk_table)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph('四、合规说明', heading_style))
    compliance_text = """
    1. 本报告数据来源于净值发布自动化管理系统，所有操作均已记录监管审计日志；<br/>
    2. 净值发布严格遵循《公开募集证券投资基金信息披露管理办法》相关规定；<br/>
    3. 回退机制符合监管要求，触发阈值设置审慎，回退流程完整可追溯；<br/>
    4. 审批流程遵循内部控制制度，三级审批机制确保合规风险可控。
    """
    story.append(Paragraph(compliance_text, normal_style))

    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", normal_style))

    doc.build(story)
    return output_path


def generate_excel_report(stats, output_path):
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        summary_df = pd.DataFrame([{
            '统计周期': f"{stats['start_date'].strftime('%Y-%m-%d')} ~ {stats['end_date'].strftime('%Y-%m-%d')}",
            '发布总数': stats['total_releases'],
            '成功发布': stats['success_releases'],
            '发布成功率(%)': round(stats['success_rate'], 2),
            '回退次数': stats['rollback_count'],
            '平均审批时长(分钟)': round(stats['avg_approval_time'], 2),
            '最长审批时长(分钟)': round(stats['max_approval_time'], 2),
            '最短审批时长(分钟)': round(stats['min_approval_time'], 2)
        }])
        summary_df.to_excel(writer, sheet_name='核心指标概览', index=False)

        daily_df = pd.DataFrame(stats['daily_data'])
        daily_df.columns = ['日期', '发布总数', '成功发布', '回退次数', '成功率(%)']
        daily_df['成功率(%)'] = daily_df['成功率(%)'].round(2)
        daily_df.to_excel(writer, sheet_name='每日明细', index=False)

        risk_df = pd.DataFrame(list(stats['risk_distribution'].items()), columns=['风险级别', '数量'])
        total = risk_df['数量'].sum() or 1
        risk_df['占比(%)'] = (risk_df['数量'] / total * 100).round(2)
        risk_df.to_excel(writer, sheet_name='风险分布', index=False)

        workbook = writer.book
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 30)
                worksheet.column_dimensions[column_letter].width = adjusted_width

    return output_path


@audit_operation('GENERATE_WEEKLY_REPORT', 'WeeklyReport')
def generate_weekly_report(report_date=None, operator='system'):
    if report_date is None:
        report_date = datetime.now()

    end_date = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_date = (end_date - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)

    report_week = start_date.strftime('%Y-W%W')

    db = SessionLocal()
    try:
        existing = db.query(WeeklyReport).filter(WeeklyReport.report_week == report_week).first()
        if existing:
            return {
                'success': True,
                'report_week': report_week,
                'pdf_path': existing.pdf_path,
                'excel_path': existing.excel_path,
                'message': '本周报告已存在'
            }

        stats = get_weekly_statistics(start_date, end_date)
        chart_paths = generate_trend_charts(stats, REPORT_PATH)

        pdf_path = os.path.join(REPORT_PATH, f"weekly_report_{report_week}.pdf")
        excel_path = os.path.join(REPORT_PATH, f"weekly_report_{report_week}.xlsx")

        generate_pdf_report(stats, chart_paths, pdf_path)
        generate_excel_report(stats, excel_path)

        weekly_report = WeeklyReport(
            report_week=report_week,
            start_date=start_date,
            end_date=end_date,
            total_releases=stats['total_releases'],
            success_releases=stats['success_releases'],
            success_rate=stats['success_rate'],
            rollback_count=stats['rollback_count'],
            avg_approval_time=stats['avg_approval_time'],
            max_approval_time=stats['max_approval_time'],
            min_approval_time=stats['min_approval_time'],
            pdf_path=pdf_path,
            excel_path=excel_path
        )
        db.add(weekly_report)
        db.commit()

        report_info = {
            'report_week': report_week,
            'success_rate': f"{stats['success_rate']:.2f}%",
            'rollback_count': stats['rollback_count'],
            'avg_approval_time': f"{stats['avg_approval_time']:.2f}分钟",
            'pdf_path': pdf_path,
            'excel_path': excel_path
        }
        notify_report_generated(report_info)

        return {
            'success': True,
            'report_week': report_week,
            'statistics': stats,
            'pdf_path': pdf_path,
            'excel_path': excel_path,
            'chart_paths': chart_paths,
            'message': '每周报告生成完成，已通知相关人员'
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()
