"""Pretrained networks used by the transcriber: vocal separation, sung pitch, beats.

Optional (`uv sync --extra gpu`). Heavy imports happen inside the functions, so importing this
module is cheap and safe without them. Weights are downloaded once, to ~/.cache/tunelab.
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import urllib.request
from importlib.util import find_spec
from pathlib import Path

import librosa
import numpy as np

SEPARATOR = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
RMVPE_URL = ("https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/"
             "e6d0c1a17da07c33557852f9dfa2bd44cc75737d/rmvpe.onnx")
RMVPE_SHA256 = "5370e71ac80af8b4b7c793d27efd51fd8bf962de3a7ede0766dac0befa3660fd"
RMVPE_SR, RMVPE_HOP = 16000, 160
CENTS = np.pad(20 * np.arange(360) + 1997.3794084376191, (4, 4))  # pitch of each output bin


def installed() -> bool:
    return (not os.environ.get("TUNELAB_NO_GPU")
            and all(find_spec(m) for m in ("torch", "audio_separator", "onnxruntime", "beat_this")))


def folder() -> Path:
    p = Path(os.environ.get("TUNELAB_MODELS", Path.home() / ".cache" / "tunelab"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def check_gpu() -> None:
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("no CUDA graphics card available")


def separate(wav: Path, out: Path) -> tuple[Path, Path]:
    """Write the singing and everything else as two files; returns (vocals, rest)."""
    from audio_separator.separator import Separator
    s = Separator(output_dir=str(out), model_file_dir=str(folder()), output_format="WAV",
                  log_level=logging.ERROR, use_autocast=True,
                  # overlap 2 is 3 times faster than the default 8, with the same pitch accuracy
                  mdxc_params={"segment_size": 256, "override_model_segment_size": False,
                               "batch_size": 1, "overlap": 2, "pitch_shift": 0})
    s.load_model(SEPARATOR)
    s.separate(str(wav), {"Vocals": "vocals", "Instrumental": "rest"})
    return out / "vocals.wav", out / "rest.wav"


def _rmvpe_file() -> Path:
    path = folder() / "rmvpe.onnx"
    if path.exists():
        return path
    digest = hashlib.sha256()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f, urllib.request.urlopen(RMVPE_URL, timeout=60) as r:
            while block := r.read(1 << 20):
                digest.update(block)
                f.write(block)
        if digest.hexdigest() != RMVPE_SHA256:
            raise RuntimeError("the downloaded RMVPE model is damaged or was changed")
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return path


def rmvpe_session():
    import torch  # noqa: F401  (its CUDA libraries are the ones preload_dlls finds)
    import onnxruntime as ort
    ort.preload_dlls()
    opt = ort.SessionOptions()
    opt.log_severity_level = 3
    return ort.InferenceSession(str(_rmvpe_file()), opt,
                                providers=["CUDAExecutionProvider", "CPUExecutionProvider"])


def sung_pitch(session, y: np.ndarray, allowed=None) -> tuple[np.ndarray, np.ndarray]:
    """(frequency in Hz, confidence 0..1) every 10 ms, for mono audio at RMVPE_SR.
    allowed: optional function (times, MIDI pitches) -> where the pitch may be."""
    y = y / (np.abs(y).max() + 1e-9)
    mag = np.abs(librosa.stft(y, n_fft=1024, hop_length=RMVPE_HOP, window="hann", pad_mode="reflect"))
    mel = librosa.filters.mel(sr=RMVPE_SR, n_fft=1024, n_mels=128, fmin=30, fmax=8000, htk=True) @ mag
    mel = np.log(np.maximum(mel, 1e-5))
    n = mel.shape[1]
    mel = np.pad(mel, ((0, 0), (0, -n % 32)), mode="reflect")
    out = session.run(None, {"input": mel[None].astype(np.float32)})[0].reshape(-1, 360)[:n]
    if allowed is not None:
        out = out * allowed(np.arange(n) * RMVPE_HOP / RMVPE_SR, 69 + 12 * np.log2(10 / 440) + CENTS[4:-4] / 100)
    # weighted average of the bins around the strongest one
    near = out.argmax(axis=1)[:, None] + np.arange(9)[None]
    w = np.take_along_axis(np.pad(out, ((0, 0), (4, 4))), near, axis=1)
    cents = (w * CENTS[near]).sum(axis=1) / (w.sum(axis=1) + 1e-9)
    return 10 * 2 ** (cents / 1200), out.max(axis=1)


def beats(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Times in seconds of (beats, first beats of bars)."""
    from beat_this.inference import Audio2Beats
    b, d = Audio2Beats(checkpoint_path="final0", device="cuda", dbn=False)(y, sr)
    return np.asarray(b), np.asarray(d)
