"""Sample-level arithmetic for clipping and mixing.

Format validation, conversion and result descriptions live in
:mod:`audio_workbench.formats`; this module keeps only numeric parameter
checks, gain application, interval slicing and saturated summation. The
legacy public names (``Audio``, ``inspect``, ``conform``, ``saturate``) are
re-exported for existing callers and tests.
"""

import array
import math

from .formats import MAX_SECONDS, Audio, conform, saturate
from . import formats

__all__ = ['number', 'saturate', 'inspect', 'clip', 'conform', 'mix', 'Audio']


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be a finite number between {low} and {high}')
    return value


def inspect(audio):
    """Legacy entry point; format facts are owned by formats.describe."""
    return formats.describe(audio)


def clip(audio, start, end, gain):
    start = number(start, 'start', 0, MAX_SECONDS)
    end = number(end, 'end', 0, MAX_SECONDS)
    gain = number(gain, 'gain', 0, 4)
    first, last = round(start * audio.rate), round(end * audio.rate)
    if first >= last or last > audio.frames:
        raise ValueError('clip interval must contain frames within the audio')
    samples = (saturate(s * gain) for s in audio.samples[first * audio.channels:last * audio.channels])
    return Audio(audio.rate, audio.channels, array.array('h', samples))


def mix(tracks):
    reference = tracks[0][0]
    for audio, offset, gain in tracks:
        if not formats.same_format(audio, reference):
            raise ValueError('track formats must match')
        number(offset, 'offset', 0, MAX_SECONDS)
        number(gain, 'gain', 0, 4)
    length = max(round(offset * reference.rate) + audio.frames for audio, offset, _ in tracks)
    if length > reference.rate * MAX_SECONDS:
        raise ValueError('mixed audio exceeds 30 seconds')
    sums = [0.0] * (length * reference.channels)
    for audio, offset, gain in tracks:
        position = round(offset * audio.rate) * audio.channels
        for index, sample in enumerate(audio.samples):
            sums[position + index] += sample * gain
    return Audio(reference.rate, reference.channels, array.array('h', (saturate(x) for x in sums)))
