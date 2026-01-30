# KajovoPasport (Windows / Python)

Aplikace pro tvorbu a tisk pasportních karet (A4 na výšku). Data (karty + obrázky) se ukládají do lokální SQLite databáze.

Poznámka k zadání: V textu je uvedeno „13 miniatur“, ale seznam obsahuje 16 položek. V programu je proto 16 polí (4×4 mřížka) v pořadí přesně podle uvedeného seznamu. Pokud chcete jiný počet/pořadí, upravte konstantu `FIELDS` v souboru `KajovoPasport/app.py`.

## Instalace (Windows)

1) Nainstalujte Python 3.11+ (doporučeno).  
2) V rozbalené složce projektu otevřete PowerShell a spusťte:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Spuštění

V aktivovaném venv:

```powershell
python -m KajovoPasport
```

Alternativně lze spustit `run_KajovoPasport.bat`.

## Ovládání

- **Levý sloupec**: seznam pasportních karet. Tlačítka:
  - **Přidat** – vytvoří novou kartu.
  - **Upravit** – přejmenuje kartu.
  - **Smazat** – odstraní kartu a její obrázky.
  - Přejetí myší / kliknutí na řádek zobrazí kartu vpravo.

- **Pravý sloupec**: náhled karty jako A4 (na výšku).
  - Klikněte na libovolné políčko (např. „skříň“, „sprcha“…) a vyberte obrázek.
  - Otevře se editor: obrázek můžete **posouvat myší**, **zoomovat kolečkem**, **otáčet** tlačítky.  
    Ořez je fixní do „portrétního“ poměru (nastavitelné v **Nastavení**). Nepokryté místo se vyplní bílou.

- Tlačítka vpravo:
  - **Uložit** – uloží změny do databáze (většinou není nutné, ukládá se průběžně).
  - **PDF** – vygeneruje PDF A4 pro vybranou kartu a otevře ho.
  - **Tisknout** – vygeneruje PDF a pokusí se spustit tisk přes Windows (výchozí PDF prohlížeč musí podporovat příkaz „print“).
  - **Upravit** – přejmenuje vybranou kartu (stejné jako vlevo).

## Databáze a soubory

- Výchozí databáze: `%APPDATA%\KajovoPasport\kajovopasport.db`
- **Load**: otevře jiný databázový soubor (SQLite).  
- **Save**: uloží kopii databáze („Save As…“) – vhodné jako záloha/ export.

## Tipy

- Pokud tisk nefunguje, použijte **PDF** a vytiskněte ručně z prohlížeče.
- Pro vyšší kvalitu exportu lze v Nastavení zvýšit rozlišení exportu.

## Struktura projektu

- `KajovoPasport/__main__.py` – start aplikace
- `KajovoPasport/app.py` – UI + logika
- `KajovoPasport/db.py` – SQLite vrstva
- `KajovoPasport/image_editor.py` – editor ořezu/zoom/rotace
- `KajovoPasport/pdf_utils.py` – generování PDF a tisk
- `KajovoPasport/settings.py` – uživatelské nastavení

