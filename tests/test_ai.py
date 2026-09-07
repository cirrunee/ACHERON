"""Protocol, evidence isolation and resumable download regression checks."""
import hashlib
import io
import json
from pathlib import Path
import pytest

from acheron import analyze
from acheron.ai.catalog import MODELS, installed, model_path
from acheron.ai.evidence import SYSTEM, build_context, parse_result
from acheron.ai.transport import json_request, NoRedirect
from acheron.ai import worker
from acheron.project import Project

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/known_O0.exe"


def answer(ids=None):
    return json.dumps({"summary": "Sample hypothesis", "findings": [{"title": "Branch", "explanation": "A conditional branch may select a path.",
                       "evidence_ids": ids or ["E001"], "confidence": "medium"}], "limitations": ["Purpose is unknown"]})


def test_ai_hypotheses_preserve_engine_and_roundtrip(tmp_path):
    project = analyze(FIXTURE)
    before = project.snapshot()
    context = build_context(project, project.functions[0], simple=True)
    assert "path" not in context and str(FIXTURE) not in json.dumps(context)
    assert "beginner" in context["style"]
    result = parse_result(answer(), context, "local", "test-model")
    project.hypotheses.extend(result["findings"])
    assert project.hypotheses[0]["status"] == "HYPOTHESIZED"
    assert project.hypotheses[0]["validation_status"] == "references_checked_only"
    assert project.hypotheses[0]["addresses"] == [int(context["evidence"][0]["address"], 16)]
    project.hypotheses[0]["review"] = "useful"
    project.save(tmp_path / "ai.acheron")
    saved = Project.load(tmp_path / "ai.acheron")
    assert saved.snapshot() == before == project.snapshot()
    assert saved.hypotheses == project.hypotheses


def test_hallucinated_evidence_cannot_create_addresses():
    project = analyze(FIXTURE)
    context = build_context(project, project.functions[0])
    finding = parse_result(answer(["E999", "http://evil.invalid", "E001"]), context, "local", "test")["findings"][0]
    assert finding["validation_status"] == "missing_or_invalid_references"
    assert finding["unresolved_evidence"] == ["E999", "http://evil.invalid"]
    assert len(finding["addresses"]) == 1
    assert finding["status"] == "HYPOTHESIZED"


def test_large_function_context_is_bounded_and_declares_omissions():
    from acheron.ai.evidence import prompt
    project = analyze(FIXTURE)
    function = project.functions[0]
    function.blocks = function.blocks * 40
    context = build_context(project, function, "Explain " * 300)
    assert len(prompt(context)) <= 14000
    assert context["included_instructions"] <= 100
    assert context["truncated"] or context["pseudocode_truncated"]
    assert context["instruction_count"] > context["included_instructions"]


@pytest.mark.parametrize("raw", ['{"summary":', '{"summary":"test","findings":[{}]}', '{"summary":"test","findings":[],"limitations":"bad"}'])
def test_invalid_model_output_is_an_explicit_error(raw):
    project = analyze(FIXTURE)
    with pytest.raises(ValueError):
        parse_result(raw, build_context(project, project.functions[0]), "local", "test")


def test_provider_payloads_use_structured_output_and_no_cloud_storage(monkeypatch):
    project = analyze(FIXTURE)
    context = build_context(project, project.functions[0])
    seen = []

    def respond(url, payload, key, timeout):
        seen.append((url, payload, key))
        if url.endswith("/responses"):
            return {"status": "completed", "output": [{"content": [{"type": "output_text", "text": answer()}]}]}
        return {"choices": [{"finish_reason": "stop", "message": {"content": answer()}}]}

    monkeypatch.setattr(worker, "json_request", respond)
    for provider in ("openai", "local"):
        result = worker.investigate({"provider": provider, "model": "test-model", "context": context, "key": "test-secret", "endpoint": "http://127.0.0.1:1234"})
        assert result["findings"]
    assert seen[0][1]["store"] is False
    assert seen[0][1]["text"]["format"]["strict"] is True
    assert seen[0][1]["instructions"] == SYSTEM
    assert "tools" not in seen[0][1] and "tools" not in seen[1][1]
    assert "test-secret" not in json.dumps(seen[0][1])
    assert seen[1][1]["response_format"]["type"] == "json_schema"


@pytest.mark.parametrize("url", ["http://example.com/v1", "https://api.openai.com.evil.invalid/v1", "https://user:pw@api.openai.com/v1", "file:///secret"])
def test_credentials_and_evidence_cannot_go_to_unconfigured_hosts(url):
    with pytest.raises(ValueError):
        json_request(url, {}, key="test-secret")


def test_redirects_do_not_forward_credentials():
    with pytest.raises(ValueError):
        NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://elsewhere.invalid")


def download_fixture(monkeypatch, tmp_path, content=b"gguf-test-contents", corrupt=False):
    model_id = "test-download"
    monkeypatch.setitem(MODELS, model_id, {"filename": "test.gguf", "size": len(content), "sha256": hashlib.sha256(content).hexdigest(), "url": "https://huggingface.co/test"})
    requests = []

    class Response(io.BytesIO):
        status = 206

    def open_request(request, timeout):
        offset = int(request.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
        requests.append(offset)
        body = bytes([content[0] ^ 1]) + content[1:] if corrupt else content
        response = Response(body[offset:])
        response.headers = {"Content-Range": f"bytes {offset}-{len(content)-1}/{len(content)}"}
        return response

    monkeypatch.setattr(worker, "urlopen", open_request)
    return model_id, requests


def test_partial_model_download_resumes_and_verifies(monkeypatch, tmp_path):
    content = b"gguf-test-contents"
    model_id, requests = download_fixture(monkeypatch, tmp_path, content)
    partial = model_path(tmp_path, model_id).with_suffix(".part")
    partial.parent.mkdir(parents=True)
    partial.write_bytes(content[:4])
    path = Path(worker.download_model(model_id, tmp_path))
    assert requests == [4]
    assert path.read_bytes() == content
    assert installed(tmp_path, model_id)
    assert not partial.exists()
    # An extracted bundle can be reverified fully offline after timestamp changes.
    path.with_suffix(".verified.json").unlink()
    assert not installed(tmp_path, model_id)
    worker.download_model(model_id, tmp_path)
    assert requests == [4] and installed(tmp_path, model_id)


def test_bad_download_hash_is_not_installed(monkeypatch, tmp_path):
    model_id, requests = download_fixture(monkeypatch, tmp_path, corrupt=True)
    with pytest.raises(ValueError, match="checksum"):
        worker.download_model(model_id, tmp_path)
    assert not installed(tmp_path, model_id)
    assert not model_path(tmp_path, model_id).with_suffix(".part").exists()
