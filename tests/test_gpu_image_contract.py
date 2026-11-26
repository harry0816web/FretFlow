from pathlib import Path


def test_gpu_worker_image_pins_cuda_torch_and_preflight():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "nvidia/cuda:13.0.2-cudnn-runtime-ubuntu22.04@sha256:" in dockerfile
    assert "ARG TORCH_VERSION=2.11.0+cu130" in dockerfile
    assert "FROM gpu-worker-runtime AS gpu-worker" in dockerfile
    assert "python download_mvsep_mega.py" in dockerfile
    assert "python -m fretflow.gpu_preflight" in dockerfile
    assert "COPY THIRD_PARTY_NOTICES.md" in dockerfile
    assert 'org.opencontainers.image.revision="$VCS_REF"' in dockerfile
    assert 'ENTRYPOINT ["./docker/gpu-entrypoint.sh"]' in dockerfile


def test_gpu_entrypoint_requires_preflight_before_worker():
    entrypoint = Path("docker/gpu-entrypoint.sh").read_text(encoding="utf-8")

    preflight = entrypoint.index("python -m fretflow.gpu_preflight")
    worker = entrypoint.index("exec python -m fretflow.worker")
    assert preflight < worker
    assert "--require-gpu" in entrypoint
    assert "set -- serve" in entrypoint


def test_worker_images_share_one_verified_model_stage():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "AS model" in dockerfile
    assert "FROM python-base AS cpu-worker" in dockerfile
    assert dockerfile.count("COPY --from=model") == 2
    assert "--backend cpu" in dockerfile
