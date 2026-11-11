import io
import base64
import qrcode
from django.urls import reverse

def generate_receipt_qr(request, receipt):
    verify_url = request.build_absolute_uri(
        reverse("verify_receipt", args=[str(receipt.verification_uuid)])
    )
    qr = qrcode.QRCode(version=1, box_size=5, border=2)
    qr.add_data(verify_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#0f172a", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")