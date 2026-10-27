from prometheus_client import Counter, Histogram

attendance_submissions = Counter(
    "attendance_submissions_total", "Attendance submissions received", ["late"]
)
attendance_reviews = Counter(
    "attendance_reviews_total", "Attendance reviews performed by admins", ["status"]
)
login_attempts = Counter("login_attempts_total", "Login attempts", ["result"])
ocr_imports = Counter("ocr_imports_total", "Attendance list images processed by OCR", ["engine", "result"])
ocr_lines = Counter("ocr_lines_total", "OCR lines by match outcome", ["status"])
ocr_duration = Histogram("ocr_duration_seconds", "Time to OCR and match one import", ["engine"],
                         buckets=(0.5, 1, 2, 5, 10, 20, 40, 90))
attendance_deletions = Counter("attendance_deletions_total", "Attendance records deleted by admins")
