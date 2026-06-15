import base64

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def encode_upload(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_training_file_upload_creates_searchable_knowledge_source():
    response = client.post(
        "/api/knowledge/uploads",
        json={
            "tags": ["占星", "上传资料"],
            "files": [
                {
                    "filename": "aries-training.txt",
                    "content_base64": encode_upload("# 白羊座\n白羊座强调行动力和开端。"),
                    "content_type": "text/plain",
                }
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["uploaded"] == 1
    assert data["chunks_created"] >= 1
    assert data["sources"][0]["source_type"] == "uploaded_txt"
    assert "上传资料" in data["sources"][0]["tags"]

    search_response = client.post(
        "/api/knowledge/search",
        json={"query": "行动力", "tags": ["上传资料"], "limit": 5},
    )
    assert search_response.status_code == 200
    assert any("白羊座" in item["content"] or "白羊座" in item["title"] for item in search_response.json()["items"])


def test_training_file_upload_rejects_unsupported_extension():
    response = client.post(
        "/api/knowledge/uploads",
        json={
            "files": [
                {
                    "filename": "archive.zip",
                    "content_base64": encode_upload("not a document"),
                    "content_type": "application/zip",
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "不支持" in response.text or "unsupported" in response.text.lower()


def test_github_import_uses_training_pipeline(monkeypatch):
    def fake_fetch_github_training_files(url):
        assert url == "https://github.com/demo/astro-knowledge"
        return [
            {
                "filename": "rules/moon.md",
                "content": b"# \xe6\x9c\x88\xe4\xba\xae\n\xe6\x9c\x88\xe4\xba\xae\xe4\xbb\xa3\xe8\xa1\xa8\xe6\x83\x85\xe7\xbb\xaa\xe5\xae\x89\xe5\x85\xa8\xe6\x84\x9f\xe3\x80\x82",
                "source_url": "https://raw.githubusercontent.com/demo/astro-knowledge/main/rules/moon.md",
            }
        ]

    import app.services as services

    monkeypatch.setattr(services, "fetch_github_training_files", fake_fetch_github_training_files)
    response = client.post(
        "/api/knowledge/github-import",
        json={"url": "https://github.com/demo/astro-knowledge", "tags": ["GitHub", "占星"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["uploaded"] == 1
    assert data["sources"][0]["source_type"] == "github_md"
    assert "GitHub" in data["sources"][0]["tags"]
