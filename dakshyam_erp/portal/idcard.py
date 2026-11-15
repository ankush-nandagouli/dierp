import base64
import io

import qrcode
from django.urls import reverse

from .emails import make_id_token


def qr_data_uri(text, box_size=4):
    qr = qrcode.QRCode(version=None, box_size=box_size, border=1)
    qr.add_data(text)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="#0f172a", back_color="white").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def id_card_context(request, student):
    verify_url = request.build_absolute_uri(reverse("portal:verify_id", args=[make_id_token(student)]))
    return {"student": student, "qr": qr_data_uri(verify_url), "verify_url": verify_url}
