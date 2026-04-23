import logging
import os
from typing import Tuple

import frappe

logger = logging.getLogger(__name__)


def extract_file_text(file_doc_name: str, max_size_mb: int = 50) -> Tuple[str, str]:
	"""
	Given a Frappe File document name, extract and return plain text from the file.
	Supports PDF, DOCX, PPTX, XLSX, XLS, HTML, CSV, JSON, XML, EPUB, and TXT files.
	
	Args:
		file_doc_name: Name of the Frappe File document
		max_size_mb: Maximum file size in MB allowed for extraction (default: 50)
		
	Returns:
		Tuple of (markdown_content, file_type_label)
		Returns ("", file_type_label) if extraction fails or file is too large
	"""
	
	try:
		import markitdown
	except ImportError:
		error_msg = "markitdown is not installed; file extraction skipped."
		logger.warning(error_msg)
		frappe.log_error(f"DEBUG: {error_msg}", "ph_agent_file_extractor")
		return "", "Unknown"

	try:
		file_doc = frappe.get_doc("File", file_doc_name)
	except Exception as e:
		frappe.log_error(f"DEBUG: Failed to get file doc {file_doc_name}: {str(e)}", "ph_agent_file_extractor")
		return "", "Unknown"

	file_url = file_doc.file_url or ""
	file_name = file_doc.file_name or ""

	# Resolve absolute path on disk
	disk_name = os.path.basename(file_url) if file_url else file_name
	file_path = frappe.get_site_path("private" if file_doc.is_private else "public", "files", disk_name)
	
	# Determine file type from extension
	file_ext = os.path.splitext(file_name.lower())[1]
	file_type_map = {
		".pdf": "PDF",
		".docx": "DOCX",
		".pptx": "PPTX",
		".xlsx": "XLSX",
		".xls": "XLS",
		".html": "HTML",
		".htm": "HTML",
		".csv": "CSV",
		".json": "JSON",
		".xml": "XML",
		".epub": "EPUB",
		".txt": "Text",
	}
	file_type_label = file_type_map.get(file_ext, "Document")
	
	# Check file size
	try:
		file_size_bytes = os.path.getsize(file_path)
		max_size_bytes = max_size_mb * 1024 * 1024		
		if file_size_bytes > max_size_bytes:
			warning_msg = f"File {file_doc_name} ({file_name}) exceeds size limit: {file_size_bytes // (1024 * 1024)} MB > {max_size_mb} MB limit"
			logger.warning(warning_msg)
			return "", file_type_label
	except OSError as e:
		error_msg = f"Failed to get file size for {file_doc_name}: {str(e)}"
		logger.exception(error_msg)
		frappe.log_error(f"DEBUG: {error_msg}", "ph_agent_file_extractor")
		return "", file_type_label

	try:
		# Use markitdown with plugins disabled (no OCR/transcription needed)
		md = markitdown.MarkItDown(enable_plugins=False)
		result = md.convert_local(file_path)
		extracted_text = result.text_content or ""
		return extracted_text, file_type_label
	except Exception as e:
		error_msg = f"File text extraction failed for file {file_doc_name}: {str(e)}"
		logger.exception(error_msg)
		frappe.log_error(f"DEBUG: {error_msg}", "ph_agent_file_extractor")
		return "", file_type_label
