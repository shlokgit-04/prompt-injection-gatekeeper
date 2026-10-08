from backend.audit import AuditLog, redact

def test_redacts_aws_keys_and_password_fields():
    v = redact({"to": "x@y.z", "body": "key AKIAIOSFODNN7EXAMPLE in text", "SMTP_PASSWORD": "hunter2"})
    assert "AKIAIOSFODNN7EXAMPLE" not in v["body"]
    assert "[REDACTED]" in v["SMTP_PASSWORD"]

def test_events_persist_and_list():
    a = AuditLog("/tmp/data_audit2")
    a.record("send_email", {"to": "x@y.z"}, None, execution="blocked", outcome="denied_by_gate")
    assert a.recent()[0]["tool"] == "send_email"
