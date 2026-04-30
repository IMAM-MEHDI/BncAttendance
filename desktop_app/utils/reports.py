from fpdf import FPDF
import datetime
import os

class AttendanceReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'BNC Attendance System - Report', 0, 1, 'C')
        self.set_font('Arial', '', 10)
        self.cell(0, 10, f'Generated on: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}', 0, 1, 'R')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def generate_pdf_report(title, records, filename="report.pdf", metadata=None):
    pdf = AttendanceReport()
    pdf.add_page()
    
    # Title
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, title, 0, 1, 'L')
    pdf.ln(2)

    # Metadata Section
    if metadata:
        pdf.set_font('Arial', '', 10)
        col_width = pdf.w / 2.2
        # Row 1
        pdf.cell(col_width, 7, f"Department: {metadata.get('dept', 'N/A')}", 0, 0)
        pdf.cell(col_width, 7, f"Teacher: {metadata.get('teacher', 'N/A')}", 0, 1)
        # Row 2
        paper_str = f"Paper: {metadata.get('paper', 'N/A')}"
        if metadata.get('code'):
            paper_str += f" ({metadata.get('code')})"
        pdf.cell(col_width, 7, paper_str, 0, 0)
        pdf.cell(col_width, 7, f"Semester: {metadata.get('sem', 'N/A')}", 0, 1)
        pdf.ln(5)

    # Table Header
    pdf.set_font('Arial', 'B', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(35, 10, 'Enrollment', 1, 0, 'C', True)
    pdf.cell(50, 10, 'Name', 1, 0, 'C', True)
    pdf.cell(45, 10, 'Paper', 1, 0, 'C', True)
    pdf.cell(35, 10, 'Date/Time', 1, 0, 'C', True)
    pdf.cell(25, 10, 'Status', 1, 1, 'C', True)

    # Data
    pdf.set_font('Arial', '', 9)
    for rec in records:
        paper = getattr(rec, 'paper', "General")
        pdf.cell(35, 10, str(rec.user.enrollment), 1)
        pdf.cell(50, 10, str(rec.user.name), 1)
        pdf.cell(45, 10, str(paper), 1)
        pdf.cell(35, 10, rec.timestamp.strftime("%Y-%m-%d %H:%M"), 1)
        pdf.cell(25, 10, "Present", 1, 1)

    # Save
    save_path = os.path.join(os.path.expanduser("~"), "Downloads", filename)
    pdf.output(save_path)
    return save_path
