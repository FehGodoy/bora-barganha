"""Gera rascunho de arte a partir de uma oferta coletada, sem entrada manual."""

from __future__ import annotations

import io
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "offers.sqlite3"
OUT_DIR = ROOT / "drafts"
SIZE = (1080, 1350)
INK = "#261a29"
CREAM = "#fff8ec"
CORAL = "#f65c45"
PINK = "#ec87a1"
MINT = "#bcebd3"
FONT_CANDIDATES = [
    ROOT / "assets" / "font-bold.ttf",                             # fonte do projeto, se adicionada
    Path(r"C:\Windows\Fonts\trebucbd.ttf"),                        # Windows (local)
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),  # Ubuntu (GitHub Actions)
]
FONT = next((p for p in FONT_CANDIDATES if p.exists()), FONT_CANDIDATES[-1])


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size)


def select_offer(db: sqlite3.Connection) -> sqlite3.Row:
    db.row_factory = sqlite3.Row
    rows = db.execute("""SELECT listing_key,title,image_url,price_min,price_max,rating,sales,offer_link
        FROM listings WHERE status LIKE 'candidata%' AND image_url IS NOT NULL AND offer_link IS NOT NULL
        ORDER BY CAST(sales AS INTEGER) DESC LIMIT 100""").fetchall()
    for row in rows:
        low, high = Decimal(row["price_min"]), Decimal(row["price_max"])
        if high / low <= Decimal("1.4") and Decimal(row["rating"] or "0") >= Decimal("4.5"):
            return row
    raise RuntimeError("Nenhuma oferta coletada atende aos filtros do rascunho.")


def download_image(url: str) -> Image.Image:
    request = Request(url, headers={"User-Agent": "BoraBarganha/0.1 (creative draft)"})
    with urlopen(request, timeout=25) as response:
        payload = response.read(8_000_001)
    if len(payload) > 8_000_000:
        raise RuntimeError("Imagem do produto ultrapassa 8 MB.")
    image = Image.open(io.BytesIO(payload))
    return ImageOps.exif_transpose(image).convert("RGBA")


def wrap(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont, width: int, limit: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=face)[2] > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > limit:
        lines = lines[:limit]
        while draw.textbbox((0, 0), lines[-1] + "…", font=face)[2] > width and lines[-1]:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def render(row: sqlite3.Row, product: Image.Image, display_title: str | None = None, final: bool = False) -> Path:
    canvas = Image.new("RGB", SIZE, CORAL)
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((560, 320, 1320, 1080), fill=PINK, outline=INK, width=5)
    draw.rounded_rectangle((56, 56, 304, 150), radius=20, fill=CREAM, outline=INK, width=4)
    draw.text((80, 63), "bora", font=font(42), fill=INK)
    draw.text((80, 102), "barganha", font=font(42), fill=INK)
    draw.rounded_rectangle((748, 68, 1020, 139), radius=35, fill=MINT, outline=INK, width=4)
    draw.text((884, 88), "SALDÃO" if final else "RASCUNHO", font=font(27), fill=INK, anchor="mt")

    title_face = font(65)
    title_lines = wrap(draw, display_title or row["title"], title_face, 950, 2)
    for index, line in enumerate(title_lines):
        draw.text((61, 199 + index * 77), line, font=title_face, fill=INK)

    draw.rounded_rectangle((170, 378, 920, 1012), radius=50, fill=CREAM, outline=INK, width=5)
    fitted = ImageOps.contain(product, (690, 575), Image.Resampling.LANCZOS)
    if fitted.mode == "RGBA":
        canvas.paste(fitted, (540 - fitted.width // 2, 695 - fitted.height // 2), fitted)
    else:
        canvas.paste(fitted, (540 - fitted.width // 2, 695 - fitted.height // 2))

    low, high = Decimal(row["price_min"]), Decimal(row["price_max"])
    label = "A PARTIR DE" if low != high else "PREÇO DA OFERTA"
    price = f"R$ {low:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    draw.rounded_rectangle((54, 1032, 700, 1247), radius=28, fill=CREAM, outline=INK, width=5)
    draw.text((85, 1058), label, font=font(31), fill=INK)
    draw.text((85, 1110), price, font=font(103 if len(price) < 11 else 84), fill=INK)
    draw.text((1020, 1212), "SHOPEE", font=font(30), fill=CREAM, anchor="rt")
    draw.rectangle((0, 1268, 1080, 1350), fill=INK)
    draw.text((540, 1285), "CONFIRA O PREÇO NO LINK DO GRUPO", font=font(32), fill=CREAM, anchor="mt")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    item = row["listing_key"].replace(":", "-")
    destination = OUT_DIR / f"{item}-{'oferta' if final else 'rascunho'}.png"
    canvas.save(destination, optimize=True)
    return destination


def main() -> None:
    from collect_shopee import open_db
    with open_db(DB_PATH) as db:
        row = select_offer(db)
        image = download_image(row["image_url"])
        output = render(row, image)
    print(f"Rascunho criado: {output}")
    print("Imagem gerada automaticamente a partir dos dados coletados. Nenhuma publicação foi feita.")


if __name__ == "__main__":
    main()
