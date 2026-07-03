from pathlib import Path

import fitz
import numpy as np
from PIL import Image


def render_pdf_page(pdf_path, page_index, dpi=300, debug_dir=None, output_name=None):
    with fitz.open(pdf_path) as doc:
        page = doc[page_index - 1]
        if page.rotation:
            page.set_rotation(page.rotation)
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    if debug_dir:
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        name = output_name or f"{Path(pdf_path).stem}_p{page_index}_{dpi}dpi.png"
        image.save(Path(debug_dir) / name)
    return np.array(image)
