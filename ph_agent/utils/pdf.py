import io
import logging
import os

import frappe

logger = logging.getLogger(__name__)


def extract_pdf_text(file_doc_name: str) -> str:
	"""
	Given a Frappe File document name, extract and return plain text from the PDF.
	Returns an empty string if the file is not a PDF or extraction fails.
	"""
	try:
		import PyPDF2
	except ImportError:
		logger.warning("PyPDF2 is not installed; PDF extraction skipped.")
		return ""

	try:
		file_doc = frappe.get_doc("File", file_doc_name)
	except Exception:
		return ""

	file_url = file_doc.file_url or ""
	file_name = file_doc.file_name or ""

	# Only attempt extraction if the original filename suggests a PDF
	if not file_name.lower().endswith(".pdf") and not file_url.lower().endswith(".pdf"):
		# Fall back to checking magic bytes below — skip the early return
		pass

	# Resolve absolute path on disk (Frappe may omit the .pdf extension from the stored filename)
	disk_name = os.path.basename(file_url) if file_url else file_name
	file_path = frappe.get_site_path("private" if file_doc.is_private else "public", "files", disk_name)

	try:
		with open(file_path, "rb") as f:
			header = f.read(4)
			if header != b"%PDF":
				return ""
			f.seek(0)
			reader = PyPDF2.PdfReader(f)
			pages_text = []
			for page in reader.pages:
				text = page.extract_text()
				if text:
					pages_text.append(text.strip())
			return "\n\n".join(pages_text)
	except Exception:
		logger.exception("PDF text extraction failed for file %s", file_doc_name)
		return ""
