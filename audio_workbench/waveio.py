"""WAV container (de)serialization for 16-bit PCM materials.

Format rules live in :mod:`audio_workbench.formats`; this module only turns
WAV bytes into an :class:`~audio_workbench.formats.Audio` and back, preserving
the legacy error mapping.
"""

import array
import io
import sys
import wave

from .formats import Audio, SAMPLE_WIDTH, valid_duration, valid_wav_header


def decode(data):
    try:
        with wave.open(io.BytesIO(data), 'rb') as reader:
            channels, width, rate, frames = (reader.getnchannels(), reader.getsampwidth(),
                                             reader.getframerate(), reader.getnframes())
            if not valid_wav_header(channels, width, rate):
                raise ValueError('expected 16-bit PCM, 1 or 2 channels, 8000-48000 Hz')
            if not valid_duration(frames, rate):
                raise ValueError('audio duration must be greater than zero and at most 30 seconds')
            raw = reader.readframes(frames)
            if len(raw) != frames * channels * SAMPLE_WIDTH:
                raise ValueError('truncated audio data')
    except (wave.Error, EOFError) as exc:
        raise ValueError('invalid WAV data') from exc
    samples = array.array('h')
    samples.frombytes(raw)
    if sys.byteorder != 'little':
        samples.byteswap()
    return Audio(rate, channels, samples)


def encode(audio):
    output = io.BytesIO()
    samples = array.array('h', audio.samples)
    if sys.byteorder != 'little':
        samples.byteswap()
    with wave.open(output, 'wb') as writer:
        writer.setnchannels(audio.channels)
        writer.setsampwidth(SAMPLE_WIDTH)
        writer.setframerate(audio.rate)
        writer.writeframes(samples.tobytes())
    return output.getvalue()
