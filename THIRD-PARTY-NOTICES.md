# Third-party software

DocToolkit is built on these open-source projects. The Windows app includes
copies of them. Each keeps its own license; the full license texts are on the
linked project pages.

| Software | Used for | License |
|---|---|---|
| [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/) | The window and all controls | LGPL-3.0 |
| [pikepdf](https://github.com/pikepdf/pikepdf) and [qpdf](https://github.com/qpdf/qpdf) | Reading and saving PDF metadata | MPL-2.0 (pikepdf), Apache-2.0 (qpdf) |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) and [PDFium](https://pdfium.googlesource.com/pdfium/) | PDF pages, text and images | Apache-2.0 or BSD-3-Clause (pypdfium2), BSD-3-Clause (PDFium) |
| [lxml](https://lxml.de) | Reading and saving Word metadata | BSD-3-Clause |
| [Pillow](https://python-pillow.org) | Image handling | MIT-CMU |
| [pytesseract](https://github.com/madmaze/pytesseract) | Talking to Tesseract | Apache-2.0 |
| [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) | Reading text from images | Apache-2.0 |
| [pywin32](https://github.com/mhammond/pywin32) | Exact Word page counts through Microsoft Word | PSF-2.0 |
| [ExifTool](https://exiftool.org) (optional) | The read-only ExifTool report | Same terms as Perl (Artistic License or GPL) |

The Qt libraries are included as separate files in the app folder, so they
can be replaced with other compatible versions, as the LGPL allows.
