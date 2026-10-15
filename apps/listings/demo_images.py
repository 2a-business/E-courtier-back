"""Illustrations générées pour les annonces fictives (aucune photo réelle n'est utilisée)."""

import random
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw, ImageFont

PALETTES = [
    ((120, 170, 230), (235, 225, 205), (95, 85, 75)),
    ((150, 195, 240), (245, 240, 230), (60, 70, 90)),
    ((240, 180, 130), (230, 210, 185), (110, 80, 60)),
    ((110, 160, 210), (210, 215, 220), (50, 60, 70)),
    ((170, 210, 235), (250, 235, 215), (160, 90, 60)),
]


def building(seed: int, variant: int = 0, size=(1200, 800)) -> SimpleUploadedFile:
    rnd = random.Random(seed * 31 + variant)
    sky, wall, accent = PALETTES[(seed + variant) % len(PALETTES)]
    w, h = size
    img = Image.new("RGB", size, sky)
    draw = ImageDraw.Draw(img)
    for y in range(h // 2):  # dégradé du ciel
        t = y / (h / 2)
        draw.line([(0, y), (w, y)], fill=tuple(int(c + (255 - c) * t * 0.6) for c in sky))
    draw.rectangle([0, int(h * 0.78), w, h], fill=(205, 190, 160))  # sol sableux
    floors = rnd.randint(1, 6) if variant == 0 else rnd.randint(1, 3)
    bw = rnd.randint(int(w * 0.35), int(w * 0.6))
    bx = rnd.randint(int(w * 0.1), w - bw - int(w * 0.1))
    floor_h = int(h * 0.62 / max(floors, 3))
    top = int(h * 0.78) - floors * floor_h
    draw.rectangle([bx, top, bx + bw, int(h * 0.78)], fill=wall, outline=accent, width=3)
    for f in range(floors):
        y = top + f * floor_h + floor_h // 4
        for x in range(bx + 20, bx + bw - 50, 70):
            draw.rectangle([x, y, x + 40, y + floor_h // 2], fill=(90, 130, 170))
        draw.line([(bx, top + (f + 1) * floor_h), (bx + bw, top + (f + 1) * floor_h)], fill=accent, width=2)
    for px in (rnd.randint(20, bx - 10 if bx > 40 else 30), rnd.randint(bx + bw + 10, w - 30)):
        draw.rectangle([px, int(h * 0.5), px + 10, int(h * 0.8)], fill=(110, 80, 50))
        for dx, dy in ((-60, -10), (60, -10), (-40, -40), (40, -40), (0, -55)):
            draw.ellipse([px + dx - 35, int(h * 0.5) + dy - 12, px + dx + 35, int(h * 0.5) + dy + 12], fill=(60, 130, 70))
    font = ImageFont.load_default(size=30)
    label = "Illustration - annonce fictive"
    box = draw.textbbox((0, 0), label, font=font)
    draw.rounded_rectangle([20, h - 76, 52 + box[2], h - 20], radius=14, fill=(0, 0, 0, 200))
    draw.text((36, h - 66), label, fill=(255, 255, 255), font=font)
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    return SimpleUploadedFile(f"demo-{seed}-{variant}.jpg", buf.getvalue(), content_type="image/jpeg")


def fake_pdf(title: str) -> SimpleUploadedFile:
    body = f"DOCUMENT FICTIF DE DEMONSTRATION - {title} - SANS VALEUR"
    content = (
        "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        f"4 0 obj<</Length {len(body) + 30}>>stream\nBT /F1 12 Tf 30 100 Td ({body}) Tj ET\nendstream endobj\n"
        "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    )
    return SimpleUploadedFile("document-fictif.pdf", content.encode("latin-1"), content_type="application/pdf")
