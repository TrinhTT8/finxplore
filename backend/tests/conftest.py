import os

# Keep tests offline and quiet.
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")
os.environ.setdefault("POWERTOOLS_SERVICE_NAME", "finxplore-test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("SEC_USER_AGENT", "FinXplore-test test@example.com")
