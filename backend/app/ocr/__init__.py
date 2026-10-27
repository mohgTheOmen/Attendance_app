"""OCR import of photographed paper attendance lists.

Pipeline: preprocess (find the sheet, flatten, binarize) -> extract text lines (Tesseract,
or optionally an Azure OpenAI vision model) -> normalize -> fuzzy-match against users ->
deduplicate -> admin review -> attendances.
"""
