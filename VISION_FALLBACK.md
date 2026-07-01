# Vision fallback — conectare cu un token OpenAI (GPT-4o-mini)

Ghid pentru a face **căutabile** schemele monofilare, exporturile `.rvt.png`,
fotografiile de echipamente și scanările pe care **OCR nu le poate citi** — folosind
un token OpenAI ieftin (`gpt-4o-mini`).

---

## Ce este vision fallback-ul

La ingestie, imaginile și PDF-urile scanate trec prin OCR (Tesseract). Dar OCR-ul
nu descifrează bine desenele tehnice și nu „vede" o poză fără text — de aceea unele
imagini ajung cu puțin text sau deloc (rândurile `ERROR: No non-empty text extracted`).

Când **vision fallback** e activ, pentru aceste pagini se trimite imaginea la un
model cu viziune (Claude sau OpenAI), care:
1. **transcrie** tot textul vizibil (etichete, nume de celule/bay, valori, unități), și
2. **descrie** pe scurt ce arată schema/poza (echipamente, conexiuni, identificatori),

iar rezultatul devine chunk căutabil. Implementare: `src/llm.py` (`vision`) apelat din
`src/ingest/pdf_loader.py` (`vision_transcribe_page`).

## De ce era „INERT"

Fallback-ul era pornit (`OCR_VISION_FALLBACK=true`), dar **fără cheie API** funcția
`vision()` returnează gol și doar loghează un warning — deci nu se întâmpla nimic.
Trebuie o cheie a providerului ales.

---

## Conectare cu GPT-4o-mini (pas cu pas)

### 1. Obține o cheie OpenAI
Din <https://platform.openai.com/api-keys> → *Create new secret key*. Arată ca
`sk-proj-...`. (Necesită credit în contul OpenAI.)

### 2. Configurează `.env`
```dotenv
OCR_VISION_FALLBACK=true       # fallback-ul activ
VISION_PROVIDER=openai         # foloseste OpenAI DOAR pentru viziune
OPENAI_API_KEY=sk-proj-...     # cheia ta
OPENAI_MODEL=gpt-4o-mini       # modelul (ieftin, cu viziune)
```
`VISION_PROVIDER=openai` schimbă **doar** pasul de viziune; extracția răspunsurilor
(`LLM_PROVIDER`) rămâne separată — vezi secțiunea „Extracție pe OpenAI" mai jos.

### 3. Testează pe o singură imagine (înainte de un run mare)
```bash
export PATH="/opt/homebrew/bin:$PATH"
IMG=$(find data/raw -iname 'Schema Monofilara*.png' | head -1)
.venv/bin/python -c "
from src.config import get_settings
from src.ingest.document_loader import load_document
print(load_document('$IMG', get_settings()).pages[0][:600])
"
```
Dacă vezi text + o descriere a schemei (nu doar câteva etichete), cheia funcționează.

### 4. Re-procesează imaginile deja ingerate
Imaginile existente sunt sărite de deduplicare, deci nu primesc descriere vision la un
`make ingest` obișnuit. Forțează re-procesarea:
```bash
# în .env:
INGEST_ON_DUPLICATE=replace
# apoi:
make ingest
```
(Alternativ, start curat: `make db-reset && make ingest`.)

---

## Ce imagini declanșează vision-ul

Vision rulează pentru paginile OCR-uite (imagini / PDF scanate) al căror text extras
e sub pragul `SCANNED_CHAR_THRESHOLD` (implicit 100 caractere) — adică exact schemele
și pozele sărace în text. Paginile care au deja text bogat din OCR nu consumă token.
Astfel:
- pozele fără text (fostele rânduri `ERROR`) devin căutabile;
- schemele (`Schema Monofilara`, `*.rvt.png`, `Celule…`) primesc descriere completă.

## Cost

`gpt-4o-mini` cu viziune e printre cele mai ieftine opțiuni. Se plătește per imagine
(tokeni de intrare pentru imagine + tokenii de ieșire ai transcrierii). Pentru un corpus
de câteva zeci–sute de scheme/poze, costul e mic, dar **nu zero** — controlează volumul
prin `SCANNED_CHAR_THRESHOLD` (prag mai mic ⇒ mai puține imagini trimise la vision).

---

## Extracție pe OpenAI (opțional)

Dacă **nu** ai cheie Anthropic și vrei ca și răspunsul la `POST /ask` (extracția
verbatim) să meargă pe OpenAI:
```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o-mini        # sau gpt-4o pentru extracție mai bună
```
Atunci și extracția, și viziunea folosesc OpenAI (viziunea moștenește `LLM_PROVIDER`
dacă lași `VISION_PROVIDER` gol).

| Vreau… | Setează |
|---|---|
| Vision pe OpenAI, extracție pe Claude | `VISION_PROVIDER=openai` + `OPENAI_API_KEY`, `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` |
| Tot pe OpenAI | `LLM_PROVIDER=openai` + `OPENAI_API_KEY` (lasă `VISION_PROVIDER` gol) |
| Tot pe Claude | `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` (lasă `VISION_PROVIDER` gol) |

---

## Troubleshooting

- **Tot gol / warning „OPENAI_API_KEY is unset"** → cheia nu e citită: verifică `.env`
  (fără ghilimele), și că rulezi din rădăcina proiectului.
- **`401 / invalid_api_key`** → cheie greșită sau expirată.
- **`429 / insufficient_quota`** → nu ai credit în contul OpenAI.
- **Imaginile tot nu se actualizează** → sunt sărite de dedupe; pune
  `INGEST_ON_DUPLICATE=replace` (sau `make db-reset`) și re-ingerează.
- **Prea scump / prea lent** → scade `SCANNED_CHAR_THRESHOLD` ca să trimiți mai puține
  imagini la vision, sau lasă `OCR_VISION_FALLBACK=false` și bazează-te doar pe OCR.
