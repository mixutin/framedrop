"""Bounded media measurements for editing assistance; timestamps are relative.

Beat estimates use a bass-energy onset envelope and have octave ambiguity. They
are editing suggestions, not a claim of musical or semantic understanding.
"""
from __future__ import annotations

from array import array
import math
from pathlib import Path
import re
import statistics
import subprocess
import sys

from .engine import FFMPEG, THREADS, _number, probe


def _envelope(path, start, duration, bass=False):
    """Decode at most ten minutes of mono 8 kHz audio (under 10 MB PCM)."""
    command = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-threads", str(THREADS),
               "-filter_threads", "1", "-ss", f"{start:.9f}", "-t", f"{duration:.9f}", "-i", str(path),
               "-vn", "-map", "0:a:0"]
    if bass:
        command += ["-af", "lowpass=f=180"]
    command += ["-ar", "8000", "-ac", "1", "-f", "s16le", "pipe:1"]
    result = subprocess.run(command, capture_output=True, timeout=120, check=False)
    if result.returncode:
        raise ValueError("Audio analysis failed: "+result.stderr.decode("utf-8", "replace")[-2000:])
    samples = array("h")
    samples.frombytes(result.stdout[:len(result.stdout)//2*2])
    if sys.byteorder != "little":
        samples.byteswap()
    energies, peaks = [], []
    window = 160  # 20 ms: sufficient for montage beat-grid suggestions.
    for offset in range(0, len(samples), window):
        frame = samples[offset:offset+window]
        if not frame:
            continue
        energies.append(math.sqrt(sum(float(x)*x for x in frame)/len(frame))/32768.)
        peaks.append(max(abs(x) for x in frame)/32768.)
    return energies, peaks, len(samples)/8000.


def _beats(energies):
    if len(energies) < 10 or max(energies, default=0) < .0001:
        return {"beats": [], "bpm": None, "confidence": 0., "method": "Bass-energy onset peaks; insufficient rhythmic audio"}
    # Positive envelope derivative reduces sustained notes and constant noise.
    onsets = [0.]+[max(0., energies[i]-energies[i-1]) for i in range(1, len(energies))]
    threshold = max(.0005, statistics.mean(onsets)*2.5, max(onsets)*.12)
    candidates = []
    for i in range(1, len(onsets)-1):
        if onsets[i] >= threshold and onsets[i] >= onsets[i-1] and onsets[i] > onsets[i+1]:
            if candidates and i-candidates[-1] < 12:  # At least 240 ms apart.
                if onsets[i] > onsets[candidates[-1]]:
                    candidates[-1] = i
            else:
                candidates.append(i)
    if energies[0] > max(energies)*.3:
        candidates.insert(0, 0)
    times = [round(i*.02, 3) for i in candidates]
    if len(candidates) < 3:
        return {"beats": times, "bpm": None, "confidence": 0., "method": "Bass-energy onset peaks; too few peaks for tempo"}
    # Match intervals to a median and report regularity instead of false certainty.
    intervals = [times[i]-times[i-1] for i in range(1, len(times)) if .28 <= times[i]-times[i-1] <= 1.2]
    if not intervals:
        return {"beats": times, "bpm": None, "confidence": .1, "method": "Bass-energy onset peaks; irregular tempo"}
    median = statistics.median(intervals)
    bpm = 60/median
    while bpm < 60:
        bpm *= 2
    while bpm > 200:
        bpm /= 2
    deviation = statistics.median(abs(x-median) for x in intervals)/median
    coverage = min(1., len(intervals)/max(1, len(times)-1))
    confidence = max(0., min(.95, (1-deviation*4)*coverage*min(1, len(times)/8)))
    return {"beats": times, "bpm": round(bpm, 2), "confidence": round(confidence, 3),
            "method": "Bass-energy onset peaks at 20 ms resolution; tempo may be half/double the musical beat"}


def analyze(path, mode="beats", start=0, duration=120, work_dir=None):
    start = _number(start, 0, 86400, "start")
    duration = _number(duration, .1, 600, "duration")
    if mode not in ("beats", "waveform", "scenes"):
        raise ValueError("mode must be beats, waveform, or scenes")
    metadata = probe(path)
    if metadata["duration"]:
        if start >= metadata["duration"]:
            raise ValueError("Analysis start is beyond the end of the source")
        duration = min(duration, metadata["duration"]-start)
    base = {"start": start, "duration": duration, "time_reference": "relative_to_analysis_start"}
    if mode in ("beats", "waveform"):
        if not metadata["has_audio"]:
            raise ValueError("This asset has no audio stream")
        energies, peaks, decoded_duration = _envelope(path, start, duration, bass=mode == "beats")
        base["duration"] = decoded_duration
        if mode == "beats":
            return {**base, **_beats(energies)}
        # Fixed upper bound gives clients an inexpensive overview for any duration.
        stride = max(1, math.ceil(len(peaks)/600))
        reduced = [round(max(peaks[i:i+stride]), 5) for i in range(0, len(peaks), stride)]
        return {**base, "peaks": reduced, "peak_interval": stride*.02,
                "method": "Absolute mono PCM peaks, 0..1 full-scale; maximum 600 bins"}
    if not metadata["has_video"]:
        raise ValueError("Scene analysis requires a video stream")
    command = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "info", "-threads", str(THREADS),
               "-filter_threads", "1", "-ss", f"{start:.9f}", "-t", f"{duration:.9f}", "-i", str(path),
               "-an", "-vf", "setpts=PTS-STARTPTS,scale=320:-2,fps=10,select='gt(scene,0.30)',showinfo",
               "-f", "null", "-"]
    result = subprocess.run(command, capture_output=True, timeout=180, check=False)
    log = result.stderr.decode("utf-8", "replace")
    if work_dir:
        destination = Path(work_dir)
        destination.mkdir(parents=True, exist_ok=True)
        (destination/"scene-analysis.log").write_text(log[-200000:], encoding="utf-8")
    if result.returncode:
        raise ValueError("Scene analysis failed: "+log[-2000:])
    cuts = sorted({round(float(value), 3) for value in re.findall(r"pts_time:([0-9.eE+\-]+)", log) if float(value) > 0})
    return {**base, "cuts": cuts, "method": "FFmpeg scene-change score > 0.30, sampled at 10 fps and 320 px width"}
