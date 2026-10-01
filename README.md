<img src="app/assets/icon.png" width="96" alt="DocToolkit icon">

# DocToolkit

A free Windows app that protects your privacy in PDF and Word files. It shows the hidden information inside them (metadata) and lets you change or remove it before you share them. It also extracts images, reads text from images (English and Arabic) and counts words.

Everything runs on your own computer. No file is ever uploaded.

![The Metadata tab](docs/screenshots/metadata-tab.png)

## Why metadata matters

PDF and Word files carry hidden information called **metadata**. When you email a CV, submit an assignment or post a document online, the metadata goes with it. Anyone who gets the file can read it in seconds, in the file's Properties window or with free tools.

Depending on the file, metadata can show:

- **Who made it:** the author and the last person who edited it.
- **Where you work or study:** the company name and the manager's name.
- **When and how:** when the file was created, changed and printed, how many minutes were spent editing it, and how many times it was saved.
- **Your software:** the exact programs and versions used. This helps attackers, because it tells them which known security holes to try.
- **Links between files:** IDs that stay the same in every copy, so files that look unrelated can be traced back to the same original.
- **Forgotten notes:** comments, keywords and subjects you never meant to share.

Collecting this information from public files is a standard first step in OSINT (open-source intelligence) and in targeted attacks such as phishing.

## How DocToolkit protects your privacy

- **See everything:** every value is shown, including the hidden XMP data, plus an optional full report from ExifTool.
- **Change or remove it:** edit any value, or remove everything with **Clear all metadata**, then save once.
- **No stamp:** many PDF editors and online converters write their own name into every file they touch and add new dates. DocToolkit adds nothing: not its name, not a date, not any other mark. Your file changes only where you changed it. The one exception is the PDF file ID, because the PDF standard renews half of it on every save.
- **Old values are really gone:** many tools edit a PDF by adding the change at the end of the file, so the old values stay hidden inside it. DocToolkit rewrites the whole file, so they are removed.
- **File dates too:** optionally, the Windows "Date created" and "Date modified" are set to the document's own dates, so the file on your computer doesn't show when you edited it.
- **Fully offline:** online "metadata removers" make you upload your private file to someone else's server. DocToolkit never uploads anything.

**What it doesn't remove (yet):**

- **Pictures inside the document** can have their own metadata, such as the camera model or the GPS location where a photo was taken.
- **Word comments and tracked changes** keep the names of the people who wrote them. You can remove them in Word: **File > Info > Check for Issues > Inspect Document**.
- **The content itself:** names and details in the text, headers and footers.

Tip: after cleaning a file, open the new file in DocToolkit and look at the **ExifTool** section to see exactly what is left.

## Download

1. Open the [latest release](../../releases/latest).
2. Under **Assets**, download **DocToolkit-*version*-windows.zip**.
3. Right-click the ZIP and choose **Extract All**. Then open the **DocToolkit** folder and double-click **DocToolkit.exe**.

You don't need admin rights, and you don't need to install Python or anything else: the text-reading engine (Tesseract) is included.

Keep **DocToolkit.exe** inside its folder, because it needs the `_internal` folder next to it. For a desktop shortcut, right-click **DocToolkit.exe** and choose **Show more options**, then **Send to**, then **Desktop (create shortcut)**.

> **"Windows protected your PC"?** Windows shows this for new apps that aren't signed with a paid certificate. Click **More info**, then **Run anyway**.

## What it does

### Metadata
Open a PDF or Word (.docx) file to see its metadata in sections. Each section opens in its own window as a Tag / Value table.

- **PDF files:** *PDF* (facts about the file and its Info dictionary), *XMP* (the XML metadata inside the PDF) and *ExifTool* (a full report, read only).
- **Word files:** *Core properties* (title, author, comments, dates), *Application properties* (company, template, editing time), *Custom properties* and *ExifTool*.

Edit values in as many sections as you want. Edited sections are marked **Modified**, and one click on **Save changes** writes everything at once. **Clear all metadata** removes it all.

![A section window](docs/screenshots/section-window.png)

### Extract Images
Pull the images out of PDF and Word files and save the ones you choose.

### Image to Text
Pick images (or pages of a PDF), crop to the part you need, and extract the text in English or Arabic. Edit it, copy it, or save it as a .txt file.

### Word Count
See a picture of every page, pick pages (tick them or type a range like `1-5, 8`), and get the word and character count. For Word files, the pages are exact when Microsoft Word is installed and approximate otherwise.

## Safety

- Extract Images and Word Count only read your files. They never change them.
- Password-protected PDFs stay protected after you save.
- "Save a copy" never replaces an existing file.
- A save writes a temporary file first, so a failed save can't damage your original.
- ExifTool is only used to read, never to write.

## Run from source

For developers. You need Windows 10 or 11, [Python](https://www.python.org/downloads/) 3.10 or newer, [Git](https://git-scm.com/) and [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki). When installing Tesseract, tick **Arabic** under *Additional language data*.

In PowerShell:
```powershell
git clone https://github.com/SOoONB52/DocToolkit.git
cd DocToolkit
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
venv\Scripts\python main.py
```
Next time, only the last line is needed (from inside the DocToolkit folder).

**ExifTool (optional):** the ExifTool report only works if ExifTool is present. Download the Windows version from [exiftool.org](https://exiftool.org), rename `exiftool(-k).exe` to `exiftool.exe`, and put it with its `exiftool_files` folder in a folder named `exiftool` inside the project folder.

## Project structure

```
main.py              starts the app
app/core/            the actual work: metadata, images, OCR, word count (no window code)
app/ui/              the main window, tabs and dialogs
app/i18n.py          all text shown in the app
app/assets/          the app icon
DocToolkit.spec      recipe for building the app with PyInstaller
docs/                screenshots for this page, and the icon's source drawings
```

## Built with

[PySide6 (Qt)](https://doc.qt.io/qtforpython/), [pikepdf](https://github.com/pikepdf/pikepdf) ([qpdf](https://github.com/qpdf/qpdf)), [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) (PDFium), [lxml](https://lxml.de), [Pillow](https://python-pillow.org), [pytesseract](https://github.com/madmaze/pytesseract) with [Tesseract OCR](https://github.com/tesseract-ocr/tesseract), [pywin32](https://github.com/mhammond/pywin32), and optionally [ExifTool](https://exiftool.org). Their licenses are listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## License

DocToolkit is released under the [MIT License](LICENSE).

## Author

Developed by **Tariq Alanazi**, tariq.n.alanazi@gmail.com
