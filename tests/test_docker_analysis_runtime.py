import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_official_image_bundles_pinned_local_analysis_runtime():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.rsplit("FROM ", 1)[1]

    assert "WHISPER_CPP_VERSION=1.8.5" in dockerfile
    assert "WHISPER_CPP_SHA256=" in dockerfile
    assert "WHISPER_MODEL_REVISION=" in dockerfile
    assert "WHISPER_MODEL_SHA256=" in dockerfile
    assert "build/bin/whisper-cli" in dockerfile
    assert "/opt/whisper/models/ggml-base.bin" in dockerfile
    assert "tesseract-ocr" in runtime
    assert "tesseract-ocr-eng" in runtime
    assert "build-essential" not in runtime
    assert "WHISPER_CPP_BIN=/usr/local/bin/whisper-cli" in runtime
    assert "TESSERACT_BIN=/usr/bin/tesseract" in runtime


def test_compose_keeps_analysis_local_and_configurable():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'WHISPER_CPP_BIN: "/usr/local/bin/whisper-cli"' in compose
    assert 'WHISPER_MODEL: "/opt/whisper/models/ggml-base.bin"' in compose
    assert 'TESSERACT_BIN: "/usr/bin/tesseract"' in compose


if __name__ == "__main__":
    test_official_image_bundles_pinned_local_analysis_runtime()
    test_compose_keeps_analysis_local_and_configurable()
    print("PASS Docker local-analysis runtime contract")
