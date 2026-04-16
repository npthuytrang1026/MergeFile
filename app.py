import os
import uuid
import io
from flask import Flask, render_template, request, jsonify, send_file
from PIL import Image
import pypdf

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB

UPLOAD_FOLDER = "/tmp/merge_uploads"
THUMB_FOLDER = "/tmp/merge_thumbs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMB_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "bmp", "tiff", "webp"}

# In-memory metadata: {file_id: {'ext': str, 'type': 'pdf'|'image', 'page_count': int}}
file_meta = {}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_ext(filename):
    return filename.rsplit(".", 1)[1].lower()


def make_pdf_thumb(file_id, path, page_num):
    thumb = os.path.join(THUMB_FOLDER, f"{file_id}_p{page_num}.jpg")
    if os.path.exists(thumb):
        return True
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(path)
        mat = fitz.Matrix(0.5, 0.5)
        pix = doc[page_num].get_pixmap(matrix=mat)
        pix.save(thumb)
        doc.close()
        return True
    except Exception:
        return False


def make_image_thumb(file_id, path):
    thumb = os.path.join(THUMB_FOLDER, f"{file_id}_p0.jpg")
    if os.path.exists(thumb):
        return True
    try:
        with Image.open(path) as img:
            img.thumbnail((200, 280), Image.LANCZOS)
            img.convert("RGB").save(thumb, "JPEG", quality=85)
        return True
    except Exception:
        return False


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    results = []
    for f in request.files.getlist("files"):
        if not f.filename or not allowed_file(f.filename):
            continue

        file_id = str(uuid.uuid4())
        ext = get_ext(f.filename)
        path = os.path.join(UPLOAD_FOLDER, f"{file_id}.{ext}")
        f.save(path)

        if ext == "pdf":
            try:
                reader = pypdf.PdfReader(path)
                count = len(reader.pages)
            except Exception:
                os.remove(path)
                continue

            file_meta[file_id] = {"ext": ext, "type": "pdf", "page_count": count}
            pages = []
            for i in range(count):
                ok = make_pdf_thumb(file_id, path, i)
                pages.append(
                    {
                        "page_num": i,
                        "thumbnail": f"/thumb/{file_id}/{i}" if ok else None,
                    }
                )
            results.append(
                {"file_id": file_id, "name": f.filename, "type": "pdf", "pages": pages}
            )
        else:
            ok = make_image_thumb(file_id, path)
            file_meta[file_id] = {"ext": ext, "type": "image", "page_count": 1}
            results.append(
                {
                    "file_id": file_id,
                    "name": f.filename,
                    "type": "image",
                    "pages": [
                        {
                            "page_num": 0,
                            "thumbnail": f"/thumb/{file_id}/0" if ok else None,
                        }
                    ],
                }
            )

    return jsonify(results)


@app.route("/thumb/<file_id>/<int:page>")
def thumb(file_id, page):
    try:
        uuid.UUID(file_id)
    except ValueError:
        return "", 404
    path = os.path.join(THUMB_FOLDER, f"{file_id}_p{page}.jpg")
    if os.path.exists(path):
        return send_file(path, mimetype="image/jpeg")
    return "", 404


@app.route("/merge", methods=["POST"])
def merge():
    data = request.json or {}
    pages = data.get("pages", [])
    if not pages:
        return jsonify({"error": "Không có trang nào để gộp"}), 400

    writer = pypdf.PdfWriter()

    for item in pages:
        fid = item.get("file_id", "")
        pnum = int(item.get("page_num", 0))

        try:
            uuid.UUID(fid)
        except ValueError:
            continue

        meta = file_meta.get(fid)
        if not meta:
            continue

        path = os.path.join(UPLOAD_FOLDER, f"{fid}.{meta['ext']}")
        if not os.path.exists(path):
            continue

        if meta["type"] == "pdf":
            try:
                reader = pypdf.PdfReader(path)
                if 0 <= pnum < len(reader.pages):
                    writer.add_page(reader.pages[pnum])
            except Exception:
                continue
        else:
            try:
                with Image.open(path) as img:
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format="PDF")
                    buf.seek(0)
                    writer.add_page(pypdf.PdfReader(buf).pages[0])
            except Exception:
                continue

    if not writer.pages:
        return jsonify({"error": "Không có trang hợp lệ để gộp"}), 400

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return send_file(
        out,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="merged.pdf",
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
