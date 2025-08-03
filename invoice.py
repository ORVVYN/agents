import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from datetime import datetime
from db.session import get_session
from db import models

def generate_invoice(app_id: int, amount: float, currency: str = "RUB") -> str:
    """Generate PDF invoice, return file path."""
    session = get_session()
    app = session.query(models.Application).get(app_id)
    supplier = session.query(models.Supplier).get(app.supplier_id)
    filename = f"invoice_{app_id}.pdf"
    filepath = os.path.join(os.getcwd(), "invoices", filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "СЧЁТ-ФАКТУРА")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 80, f"Дата: {datetime.utcnow().strftime('%d.%m.%Y')}")
    c.drawString(50, height - 100, f"Поставщик: {supplier.name}")
    c.drawString(50, height - 120, f"Покупатель: {app.requester.full_name or app.requester.username}")
    c.drawString(50, height - 160, f"Сумма: {amount} {currency}")
    c.showPage()
    c.save()

    invoice_rec = models.Invoice(supplier_id=supplier.id, amount=amount, currency=currency, pdf_path=filepath)
    session.add(invoice_rec)
    session.commit()
    session.close()
    return filepath
