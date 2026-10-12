"""Tiny, valid PDFs built byte by byte, so extraction tests need no binary fixtures."""


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[str | None]) -> bytes:
    """A PDF with one page per entry: its text (lines split on newlines), or None for a blank page
    with no text layer (what a scan looks like to a text extractor)."""
    objects: dict[int, bytes] = {}
    page_numbers = [4 + 2 * i for i in range(len(pages))]
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{n} 0 R" for n in page_numbers)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for number, text in zip(page_numbers, pages, strict=True):
        if text is None:
            stream = b""
        else:
            lines = [f"({_escape(line)}) Tj T*" for line in text.split("\n")]
            stream = ("BT /F1 12 Tf 14 TL 72 720 Td " + " ".join(lines) + " ET").encode("latin-1")
        objects[number + 1] = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        objects[number] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {number + 1} 0 R "
            "/Resources << /Font << /F1 3 0 R >> >> >>"
        ).encode()
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for number in range(1, size):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
