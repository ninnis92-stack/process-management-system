from flask import Blueprint, request, jsonify
from PIL import Image
import pytesseract

verify_bp = Blueprint("verify", __name__)

@verify_bp.route("/verify/camera", methods=["POST"])
def verify_camera():
    """Simple camera-upload verification endpoint.

    Expects a multipart upload with an ``image`` file.  Runs OCR on the
    picture and returns a JSON object indicating which form field should be
    populated along with the recognized text.  For now the field is hard-\
    coded to ``serial_number``; the front end can override this if needed.

    The intent is to support both printed digits and crude handwriting by
    leveraging whatever OCR engine is available (``pytesseract`` by default).
    The route is deliberately lightweight so that back ends can be swapped out
    for a third-party API or ML model without touching the client code.
    """
    file = request.files.get("image")
    if not file:
        return jsonify(ok=False, error="missing_file"), 400

    try:
        img = Image.open(file.stream)
    except Exception:
        return jsonify(ok=False, error="bad_image"), 400

    # perform OCR; ``--psm 6`` treats the image as a single uniform block of
    # text which works reasonably for both handwriting and printed numbers.
    text = pytesseract.image_to_string(img, config="--psm 6")
    # normalize to alphanumeric, drop stray whitespace
    cleaned = "".join(ch for ch in text if ch.isalnum()).strip()

    # allow caller to specify which field they were trying to populate; if
    # nothing is given we default to ``serial_number`` for backwards
    # compatibility with the earlier proof‑of‑concept.
    field_name = request.form.get("field") or "serial_number"

    return jsonify(ok=True, field=field_name, value=cleaned)
