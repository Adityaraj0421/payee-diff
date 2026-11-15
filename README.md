# payee-diff

payee-diff reports when payment details a person can see on an invoice or supplier email differ from payment details that exist only in hidden or raw text.

Hidden-character scanners such as GlyphGuard, GhostChar, and NoMark look for invisible Unicode. They do not say whether an IBAN, account number, payee, or amount in that hidden text disagrees with the one on the page. That comparison is what this tool does.

It does not move money, and a report is not a payment instruction.

## Install

Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Development install, including pytest:

```bash
pip install -e ".[dev]"
pytest
```

Runtime dependencies are [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) and [pdfminer.six](https://github.com/pdfminer/pdfminer.six). pdfminer.six is MIT-licensed and exposes glyph colour, size, and position. Render mode is read from the PDF text state. The tool does not call a model and does not make network requests.

## Usage

```bash
payee-diff path/to/invoice.pdf
payee-diff path/to/message.eml --format text
payee-diff path/to/invoice.html --format json
```

Input is one local file: `.pdf`, `.html`, `.htm`, or `.eml`. An `.eml` may contain a plain part, an HTML part, and PDF attachments. Those parts are scanned. Other attachments are skipped and named in `notes`.

`--format` is `text`, `json`, or `both` (the default). Text is the human report. JSON is the stable machine report (`schema_version` `1.0`).

### Exit codes

| Code | Status | Meaning |
| --- | --- | --- |
| 0 | `no_conflict` | Every payment value found in hidden or raw text also appears in the visible text. |
| 1 | `conflict` | A hidden or raw-only payment value differs from the visible one, or a payment value appears only in hidden or raw text. |
| 2 | `error` | The file is missing, unreadable, encrypted, or not a supported type. |
| 3 | `not_checked` | No selectable text, so nothing was compared. This is not a pass. |

Exit 0 is not a recommendation to pay. If a PDF has some text pages and some pages with no selectable text, and there is no conflict in the text that could be read, the exit code is 3 and the message is `no selectable text, not checked`. If there is also a conflict, the exit code is 1 and the unchecked page is listed in `notes`.

## Example output

Clean HTML invoice (`fixtures/clean.html`). Exit code 0.

```text
payee-diff 1.0.0
file: fixtures/clean.html
kind: html
status: no_conflict
exit_code: 0
message: no payment-detail conflict

iban
  visible:
    GB29FAKE00112210293847
      rendered text
  hidden:
    (none)

payee
  visible:
    Northwind Paper Ltd
      rendered text
  hidden:
    (none)

conflicts: 0
This report does not authorise a payment.
```

The full text report also lists account number, sort code, IFSC, UPI, and amount. The JSON report carries the same facts under `candidates`, `fields`, and `conflicts`.

HTML invoice with a second IBAN inside `display:none` (`fixtures/html_display_none.html`). Exit code 1.

```text
iban
  visible:
    GB29FAKE00112210293847
      rendered text
  hidden:
    DE58000000009988776655  [hidden-css]
      display:none
  CONFLICT: hidden or raw-only value differs from the visible value

payee
  visible:
    Northwind Paper Ltd
  hidden:
    Grey Harbor Supplies GmbH  [hidden-css]
      display:none
  CONFLICT: hidden or raw-only value differs from the visible value

amount
  visible:
    GBP 1,250.00
  hidden:
    GBP 9,875.00  [hidden-css]
      display:none
  CONFLICT: hidden or raw-only value differs from the visible value

conflicts: 3
```

The matching JSON `conflicts` array:

```json
[
  {
    "field": "iban",
    "visible": ["GB29FAKE00112210293847"],
    "hidden": [
      {
        "value": "DE58000000009988776655",
        "normalized": "DE58000000009988776655",
        "origin": "hidden-css"
      }
    ],
    "conflict": true,
    "reason": "hidden or raw-only value differs from the visible value"
  }
]
```

Image-only PDF (`fixtures/image_only.pdf`). Exit code 3.

```text
payee-diff 1.0.0
file: fixtures/image_only.pdf
kind: pdf
status: not_checked
exit_code: 3
message: no selectable text, not checked

no selectable text, not checked
Nothing in this file was compared.
This report does not authorise a payment.
```

```json
{
  "status": "not_checked",
  "exit_code": 3,
  "not_checked": true,
  "message": "no selectable text, not checked",
  "stats": {
    "pdf_pages": 1,
    "selectable_characters": 0,
    "images": 1
  },
  "candidates": [],
  "conflicts": []
}
```

## What it detects

Payment fields, extracted with regular expressions and nearby labels. No model.

| Field | How it is recognised |
| --- | --- |
| IBAN | Country length from the IBAN registry, then the ISO 13616 mod-97 check. Spaces and dashes between characters are allowed. |
| Account number | 6–18 digits next to a label such as "account number", "acct", or "a/c". |
| Sort code | `NN-NN-NN` next to "sort code". |
| IFSC | `AAAA0XXXXXX` next to "IFSC". |
| UPI | `local@handle` next to "UPI" or "VPA". The handle must not contain a dot, so an ordinary email is not treated as a UPI id. |
| Amount | A decimal amount with GBP, EUR, USD, INR, or £ € $ ₹, or the same amount next to "amount" or "total". |
| Payee | The words after "payee", "beneficiary", "account name", "payable to", or "paid to". |

Each candidate has one origin:

| Origin | Where the value came from |
| --- | --- |
| `visible` | Shown as normal text. |
| `hidden-css` | HTML that is not painted: `display:none`, `visibility:hidden`, `opacity:0`, font size at or below 0.5px, transparent colour, font colour within 12/255 per channel of the effective background (including white on a default white page), or common off-screen placement (`left`/`top` at or beyond -50px, a large negative `text-indent`, `translate` off-screen, a clipped box, or zero size with `overflow:hidden`). |
| `raw-only` | Present in the source or the PDF text layer and not visibly rendered. Includes HTML comments, `<script>`, `<style>`, `<title>`, `<meta>`, hidden inputs, `data-*` attributes, PDF render mode 3 or 7, text outside the crop box, PDF font size at or below 0.5pt, and PDF fill colour matching the painted background. |
| `unicode-tag` | Decoded from Unicode Tags U+E0020–U+E007E (the ASCII mirror inside U+E0000–U+E007F). |

A conflict is per field. The hidden value is compared after normalisation (IBAN compacted and uppercased, amounts parsed as currency plus two decimals, payee case-folded). The same value in both places is not a conflict. A hidden value with no visible counterpart is a conflict, because a reader that ingests the raw file can still pick it up.

## What it does not detect

These are limits of the heuristics, not a claim that the file has been cleared.

- No OCR and no raster comparison. A scan, a photo, or text drawn only as curves is reported as `no selectable text, not checked` when the page has no text layer. Exit code 3. It is not a pass.
- Text covered by a later opaque image or path is still treated as visible. The check uses paint order only to decide the background fill behind a glyph.
- The PDF page background is white unless a filled rectangle sits behind the glyph. A full-page shaded background that is not a rectangle can be missed, and near-white text on it can be mislabelled.
- Account numbers, sort codes, IFSC codes, UPI ids, amounts, and payee names need a label (amounts may instead carry a currency). A bare digit string is ignored. IBAN is the exception, because the checksum is the filter.
- Only GBP, EUR, USD, and INR amounts are recognised.
- Values split across elements or across separately positioned PDF runs can be missed. Lines are joined with newlines; a payee name does not cross a newline.
- HTML is not a browser. Stylesheets linked with `<link>` are not fetched. Selectors are limited to type, class, id, descendant, and child. Pseudo-classes, attribute selectors, and sibling combinators are ignored. The `font` shorthand is only partly read. JavaScript is not run. `<noscript>` content is treated as visible for that reason.
- Unicode Tags are decoded. Other invisible characters (zero-width spaces, bidi controls) are removed before matching so they do not break a regex, and they are not reported on their own. Homoglyphs are not folded to Latin lookalikes.
- Two different *visible* values for one field are listed and are not called a conflict. The conflict rule is hidden or raw text versus visible text.
- Encrypted PDFs are an error. Email headers are not scanned.
- A passing mod-97 check does not mean the account exists. The fixture IBANs are valid-format and fictional.

## How this differs from a Unicode-only scanner

GlyphGuard, GhostChar, and NoMark report hidden characters. payee-diff ignores tag characters that do not decode into a payment field, and it does report a payment field hidden with ordinary CSS or with PDF render mode 3 even when the file contains no special Unicode at all. The output is a field-by-field difference, not a count of invisible code points.

## Fixtures

`python scripts/generate_fixtures.py` rewrites `fixtures/`. The companies, amounts, and IBANs are fictional. The IBANs pass mod-97 so the validator accepts them. They are not real accounts.

| File | What it is | Exit |
| --- | --- | --- |
| `fixtures/clean.pdf` | Visible text layer only | 0 |
| `fixtures/clean.html` | Visible HTML only | 0 |
| `fixtures/clean.eml` | Plain + HTML + the clean PDF | 0 |
| `fixtures/html_white_on_white.html` | White text on a white background | 1 |
| `fixtures/html_display_none.html` | A `display:none` span with a second payee | 1 |
| `fixtures/html_unicode_tags.html` | A second payee encoded as Unicode Tags | 1 |
| `fixtures/pdf_white_text.pdf` | White text in the PDF content stream | 1 |
| `fixtures/pdf_render_mode_3.pdf` | Text with render mode 3 (not painted) | 1 |
| `fixtures/eml_hidden_span.eml` | Plain part plus HTML with a hidden span | 1 |
| `fixtures/image_only.pdf` | A raster image and no text operators | 3 |

## JSON report

Top-level keys, in this order: `schema_version`, `tool`, `tool_version`, `input` (`path`, `kind`, `sha256`), `status`, `exit_code`, `not_checked`, `message`, `notes`, `stats` (`pdf_pages`, `selectable_characters`, `images`), `candidates`, `fields`, `conflicts`.

`stats` is null for HTML. For a PDF, or for an email that contains one, it counts pages, selectable characters, and embedded images.

Each candidate has `field`, `value`, `normalized`, `origin`, `detail`, `context`, `page`, and `part`.

Each field summary has `field`, `visible`, `hidden` (value, normalized, origin), `conflict`, and `reason`. `conflicts` is the subset of field summaries with `conflict: true`. `reason` is either `hidden or raw-only value differs from the visible value` or `payment value appears only in hidden or raw text`.

## License

MIT. Copyright (c) 2026 Aditya Raj. See [LICENSE](LICENSE).
