# sE-pretix-customfonts

pretix-Plugin: Schriften **global** im Admin-Bereich hochladen (`/control/global/customfonts/`, Menüpunkt „Schriften“, nur Administratoren im Admin-Modus).
Die Schriften stehen danach in allen Events für Shop-Design, Tickets, Badges und Rechnungen zur Verfügung. Das Plugin ist unsichtbar (kein Schalter pro Event).

- Upload: TTF, OTF, WOFF, WOFF2 oder ZIP mit mehreren Schnitten; Duplikate („…Upright“) werden erkannt und übersprungen.
- OTF/CFF wird automatisch nach TrueType konvertiert (reportlab braucht TrueType für PDFs); fürs Web entsteht WOFF2.
- pretix kennt je Familie nur Regular/Bold/Italic/Bold Italic. Andere Gewichte (Light, Semibold, …) werden eigene Familien, z. B. „Titillium Light“.
- Schriften mit Einbettungsverbot (`OS/2 fsType` restricted) werden abgelehnt; „Open Sans“ ist reserviert. **Beachten Sie die Lizenz jeder Schrift selbst.**
- Ablage: `MEDIA_ROOT/customfonts/<familie>/…` plus `registry.json` (liegt im Daten-Volume, übersteht Updates).

## Installation

```bash
pip install se-pretix-customfonts      # zieht fonttools und brotli mit; danach pretix neu starten
```

Docker: `RUN pip3 install …` im eigenen Dockerfile auf Basis von `pretix/standalone`. `/media/` muss vom Webserver ausgeliefert werden (bei der Standard-Docker-Konfiguration der Fall).

## Wie es in pretix eingreift (und was bei Updates brechen kann)

pretix kennt für Plugin-Schriften keinen Weg, der PDF und Web gleichzeitig mit nachträglich hochgeladenen Dateien abdeckt. Das Plugin nutzt deshalb:

1. das offizielle Signal `register_fonts` und einen **Static-Finder** (Djangos Erweiterungspunkt) – stabil;
2. einen **Hook auf `staticfiles_storage.url`**, damit Web-Schriften eine URL unter `/media/` bekommen (pretix' Manifest-Storage kennt hochgeladene Dateien nicht);
3. einen **Wrapper um `Renderer._register_fonts`** und Zugriff auf `reportlab.pdfmetrics._fonts`, damit neue/ersetzte Schriften in PDFs ohne Neustart erscheinen.

Punkte 2 und 3 sind interne Schnittstellen. Die Seite „Schriften“ führt deshalb eine **Selbstprüfung** durch und warnt, wenn ein Hook nicht mehr greift. `compatibility` ist auf `pretix>=2026.8.0,<2027.0.0` begrenzt.

## Tests

```bash
python -m venv .venv && .venv/bin/pip install pytest fonttools brotli reportlab && .venv/bin/python -m pytest -q
# optional mit echter Schrift: TITILLIUM_ZIP=/pfad/zur/Schrift.zip
```

## Lizenz

Apache License 2.0 (siehe `LICENSE`). Das Plugin darf frei genutzt, geändert und weitergegeben werden, auch kommerziell.
pretix selbst steht unter der AGPL mit Zusatzbedingungen; wer pretix betreibt, muss deren Bedingungen einhalten
(siehe [Lizenz-FAQ von pretix](https://docs.pretix.eu/trust/licensing/faq/)). Apache-2.0 ist dazu ausdrücklich verträglich.

**Inoffiziell:** Dieses Projekt wird nicht vom pretix-Team entwickelt oder unterstützt. „pretix“ ist eine Marke von rami.io GmbH.
