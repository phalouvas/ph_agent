import re


def substitute_placeholders(template, replacement_text):
	"""Replace all {{placeholder}} tokens in template with replacement_text.

	Uses a lambda with re.sub so backslash sequences in replacement_text
	are treated as literals, not regex escape sequences. Falls back to
	simple concatenation if the regex fails for any reason.
	"""
	try:
		return re.sub(r"\{\{\w+\}\}", lambda m: replacement_text, template)
	except re.error:
		return template + "\n\n" + replacement_text
