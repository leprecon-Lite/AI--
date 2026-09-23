"""
Генерация PDF-заключения по протоколу.
Использует fpdf2 + шрифты DejaVuSans из пакета matplotlib (поддержка кириллицы).
"""
from pathlib import Path
from typing import Any, Dict

import matplotlib
from fpdf import FPDF

from logger import logger


# Путь к шрифтам внутри пакета matplotlib
MPL_FONTS_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"

FONT_REGULAR = MPL_FONTS_DIR / "DejaVuSans.ttf"
FONT_BOLD = MPL_FONTS_DIR / "DejaVuSans-Bold.ttf"
FONT_ITALIC = MPL_FONTS_DIR / "DejaVuSans-Oblique.ttf"
FONT_BOLD_ITALIC = MPL_FONTS_DIR / "DejaVuSans-BoldOblique.ttf"


STATUS_LABELS_RU = {
    "good": "ПРОДУКЦИЯ ГОДНА",
    "warning": "ТРЕБУЕТ ВНИМАНИЯ ОПЕРАТОРА",
    "defect": "ПРОДУКЦИЯ БРАКУЕТСЯ",
}

STATUS_COLORS = {
    "good": (63, 163, 77),
    "warning": (241, 162, 8),
    "defect": (192, 57, 43),
}


class ProtocolPDF(FPDF):
    def __init__(self, protocol_id: int):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.protocol_id = protocol_id
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(15, 15, 15)

        # Загружаем шрифты прямо из matplotlib
        if FONT_REGULAR.exists() and FONT_BOLD.exists():
            self.add_font("DejaVu", "", str(FONT_REGULAR))
            self.add_font("DejaVu", "B", str(FONT_BOLD))

            if FONT_ITALIC.exists():
                self.add_font("DejaVu", "I", str(FONT_ITALIC))
            if FONT_BOLD_ITALIC.exists():
                self.add_font("DejaVu", "BI", str(FONT_BOLD_ITALIC))

            self.font_family = "DejaVu"
            logger.info("PDF: шрифты DejaVu загружены из matplotlib")
        else:
            logger.warning("PDF: шрифты DejaVu не найдены в matplotlib — кириллица не отобразится")
            self.font_family = "Helvetica"

    def header(self):
        self.set_font(self.font_family, "B", 16)
        self.set_text_color(241, 90, 36)
        self.cell(0, 10, "СОЛЯРИС", ln=True)

        self.set_font(self.font_family, "", 10)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, "Система контроля качества кофейного сырья", ln=True)
        self.ln(2)

        self.set_draw_color(234, 223, 206)
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font(self.font_family, "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f"Документ сформирован автоматически · Страница {self.page_no()}", align="C")


def generate_pdf(protocol_data: Dict[str, Any]) -> bytes:
    protocol = protocol_data.get("protocol", {})
    rows = protocol_data.get("rows", [])
    report_text = protocol_data.get("report_text", "")

    protocol_id = protocol.get("id", 0)
    filename = protocol.get("filename", "—")
    uploaded_at = protocol.get("uploaded_at", "")[:19].replace("T", " ")
    overall_status = protocol.get("overall_status", "warning")
    total_rows = protocol.get("total_rows", 0)
    failed_rows = protocol.get("failed_rows", 0)
    warning_rows = protocol.get("warning_rows", 0)
    good_rows = total_rows - failed_rows - warning_rows

    pdf = ProtocolPDF(protocol_id)
    pdf.add_page()

    # Заголовок
    pdf.set_font(pdf.font_family, "B", 14)
    pdf.set_text_color(43, 43, 43)
    pdf.cell(0, 8, "ЗАКЛЮЧЕНИЕ ПО ПРОВЕРКЕ КАЧЕСТВА", ln=True)

    pdf.set_font(pdf.font_family, "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, f"Протокол №{protocol_id} от {uploaded_at}", ln=True)
    pdf.ln(4)

    # Плашка статуса
    color = STATUS_COLORS.get(overall_status, (150, 150, 150))
    pdf.set_fill_color(*color)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(pdf.font_family, "B", 13)
    pdf.cell(0, 12, "   " + STATUS_LABELS_RU.get(overall_status, overall_status), ln=True, fill=True)
    pdf.ln(4)

    # Сводка
    pdf.set_text_color(43, 43, 43)
    pdf.set_font(pdf.font_family, "", 10)
    pdf.cell(0, 6, f"Файл: {filename}", ln=True)
    pdf.cell(0, 6, f"Всего партий: {total_rows}", ln=True)
    pdf.cell(0, 6, f"Годных: {good_rows}  ·  Требует внимания: {warning_rows}  ·  Брак: {failed_rows}", ln=True)
    pdf.ln(4)

    # Заключение GigaChat
    if report_text:
        pdf.set_font(pdf.font_family, "B", 12)
        pdf.cell(0, 8, "ЗАКЛЮЧЕНИЕ", ln=True)
        pdf.set_font(pdf.font_family, "", 10)
        pdf.multi_cell(0, 5.5, report_text)
        pdf.ln(4)

    # Таблица отклонений
    problems = []
    for row in rows:
        for p in row.get("parameters", []):
            if p.get("status") in ("fail", "warning"):
                problems.append({
                    "row": row.get("row_index"),
                    "param": p.get("parameter") or p.get("source_column"),
                    "actual": p.get("actual"),
                    "unit": p.get("unit") or "",
                    "norm": p.get("norm"),
                    "status_ru": p.get("status_ru", p.get("status")),
                    "status": p.get("status"),
                })

    if problems:
        pdf.set_font(pdf.font_family, "B", 12)
        pdf.cell(0, 8, "ОТКЛОНЕНИЯ ПО ПАРТИЯМ", ln=True)
        pdf.set_font(pdf.font_family, "B", 9)
        pdf.set_fill_color(250, 247, 242)
        pdf.set_text_color(110, 110, 110)

        widths = [12, 55, 22, 22, 32, 42]
        headers = ["№", "Параметр", "Факт", "Ед.", "Норма", "Статус"]
        for w, h in zip(widths, headers):
            pdf.cell(w, 7, h, border="B", fill=True)
        pdf.ln()

        pdf.set_font(pdf.font_family, "", 9)
        pdf.set_text_color(43, 43, 43)

        for pr in problems[:200]:
            if pdf.get_y() > 260:
                pdf.add_page()
                pdf.set_font(pdf.font_family, "B", 9)
                pdf.set_fill_color(250, 247, 242)
                for w, h in zip(widths, headers):
                    pdf.cell(w, 7, h, border="B", fill=True)
                pdf.ln()
                pdf.set_font(pdf.font_family, "", 9)

            if pr["status"] == "fail":
                pdf.set_fill_color(253, 243, 242)
            else:
                pdf.set_fill_color(254, 248, 230)

            pdf.cell(widths[0], 6, str(pr["row"]), border="B", fill=True)
            pdf.cell(widths[1], 6, str(pr["param"])[:40], border="B", fill=True)
            pdf.cell(widths[2], 6, str(pr["actual"]), border="B", fill=True)
            pdf.cell(widths[3], 6, str(pr["unit"]), border="B", fill=True)
            pdf.cell(widths[4], 6, str(pr["norm"]), border="B", fill=True)
            pdf.cell(widths[5], 6, str(pr["status_ru"])[:30], border="B", fill=True)
            pdf.ln()

        if len(problems) > 200:
            pdf.set_font(pdf.font_family, "", 9)
            pdf.cell(0, 6, f"… и ещё {len(problems) - 200} отклонений", ln=True)

        pdf.ln(4)

    # Не проверено
    unchecked = protocol_data.get("unchecked", [])
    if unchecked:
        pdf.set_font(pdf.font_family, "B", 11)
        pdf.set_text_color(138, 100, 0)
        pdf.cell(0, 8, "НЕ ПРОВЕРЕНО (НЕТ В ПРОТОКОЛЕ)", ln=True)
        pdf.set_font(pdf.font_family, "", 9)
        pdf.set_text_color(43, 43, 43)
        for u in unchecked[:20]:
            pdf.cell(0, 5, f"• {u.get('parameter', '—')} — норма {u.get('norm', '—')}", ln=True)
        pdf.ln(4)

    # Подпись
    pdf.ln(8)
    pdf.set_draw_color(180, 180, 180)
    y = pdf.get_y()
    pdf.line(15, y, 90, y)
    pdf.line(120, y, 195, y)
    pdf.set_font(pdf.font_family, "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(75, 5, "Оператор / подпись", align="L")
    pdf.cell(0, 5, "Дата", align="L", ln=True)

    pdf.ln(6)
    pdf.set_font(pdf.font_family, "I", 8)
    pdf.set_text_color(140, 140, 140)
    pdf.multi_cell(0, 4, "Решение о переработке или списании продукции принимает комиссия. "
                          "AI-агент выполняет только первичную проверку соответствия ГОСТ.")

    return bytes(pdf.output())