"""Generate a small demo PDF (technical Romanian) into data/raw/ for a quick
end-to-end smoke test.

    python scripts/make_sample_pdf.py
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

# A Unicode TTF is required so Romanian diacritics (ă â î ș ț) are embedded in the
# text layer. The Base-14 "helv" font only covers Latin-1 and would drop them.
# Ordered by coverage of Romanian comma-below glyphs (ș U+0219, ț U+021B), which
# many common fonts (incl. Arial) lack. DejaVu (Linux/Docker) and Helvetica.ttc
# (macOS) round-trip them correctly.
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",   # Linux / Docker image
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",               # macOS
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Geneva.ttf",
]

PAGES = [
    (
        "Stație de transformare 110/20 kV — Instrucțiuni de exploatare\n\n"
        "1. Echipament individual de protecție (EIP)\n"
        "Înainte de orice manevră, personalul de exploatare trebuie să poarte casca "
        "de protecție, mănuși electroizolante verificate, încălțăminte electroizolantă "
        "și vizieră pentru arc electric. Mănușile electroizolante se verifică vizual "
        "înainte de fiecare utilizare și se testează la fiecare 6 luni."
    ),
    (
        "2. Manevre de comutație\n\n"
        "La întocmirea foii de manevră se trec, în ordine, operațiile de deconectare a "
        "întreruptorului, separarea vizibilă prin separatoare și verificarea lipsei "
        "tensiunii. Separatoarele nu se manevrează niciodată sub sarcină. După fiecare "
        "operație se confirmă poziția reală a aparatajului în schema stației."
    ),
    (
        "3. Punerea la pământ și verificări înainte de reanclanșare\n\n"
        "Înainte de reanclanșarea (re-energizarea) unei celule se verifică: lipsa "
        "tensiunii cu detectorul omologat, integritatea legăturilor de punere la pământ, "
        "retragerea scurtcircuitoarelor mobile și starea izolației. Reanclanșarea se face "
        "numai după confirmarea că nu există echipe la lucru pe circuitul respectiv."
    ),
    (
        "4. Admiterea echipei de mentenanță la locul de muncă\n\n"
        "Admiterea la lucru presupune: emiterea autorizației de lucru, separarea "
        "electrică a zonei, montarea scurtcircuitoarelor de protecție, delimitarea zonei "
        "cu îngrădiri și panouri de avertizare, și instruirea echipei privind riscurile "
        "specifice. Zonele cu risc de arc electric se semnalizează corespunzător."
    ),
]


def _pick_font() -> str | None:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def main() -> None:
    out_dir = Path("data/raw")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "statie_110kV_instructiuni.pdf"

    fontfile = _pick_font()
    box_kwargs = {"fontsize": 12, "lineheight": 1.4}
    if fontfile:
        box_kwargs.update(fontfile=fontfile, fontname="body")
    else:
        box_kwargs["fontname"] = "helv"
        print("WARNING: no Unicode TTF found — Romanian diacritics may not render.")

    doc = fitz.open()
    for text in PAGES:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(56, 56, 540, 780), text, **box_kwargs)
    doc.save(out)
    doc.close()
    print(f"Wrote {out} ({len(PAGES)} pages, font={'embedded' if fontfile else 'helv'}).")


if __name__ == "__main__":
    main()
