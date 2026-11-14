"""Single source of truth for PCM material format facts.

Every path that accepts, converts or describes 16-bit PCM audio (the legacy
``/inspect``, ``/clip`` and ``/mix`` endpoints as well as frozen arrangement
renders) goes through the rules in this module so format validation, sample
rate/channel conversion and result property descriptions cannot evolve
separately on each path.
"""

import array
from dataclasses import dataclass

# Material format contract shared by WAV decoding, request validation and the
# arrangement metadata checks.
SAMPLE_WIDTH = 2
CHANNEL_CHOICES = (1, 2)
MIN_RATE = 8000
MAX_RATE = 48000
MAX_SECONDS = 30
PEAK_DENOMINATOR = 32768


@dataclass
class Audio:
    """Decoded PCM material: format facts plus interleaved signed samples."""

    rate: int
    channels: int
    samples: array.array

    @property
    def frames(self):
        return len(self.samples) // self.channels


def valid_wav_header(channels, width, rate):
    """Header facts accepted from WAV containers (see waveio.decode)."""
    return channels in CHANNEL_CHOICES and width == SAMPLE_WIDTH and MIN_RATE <= rate <= MAX_RATE


def valid_duration(frames, rate):
    """Accepted materials hold between one frame and MAX_SECONDS of audio."""
    return 1 <= frames <= rate * MAX_SECONDS


def validate_target(rate, channels, source_rate):
    """Validate a requested conversion target using the legacy error contract."""
    if type(rate) is not int or not MIN_RATE <= rate <= MAX_RATE or rate < source_rate:
        raise ValueError('sample rate must be an integer from the source rate through 48000')
    if type(channels) is not int or channels not in CHANNEL_CHOICES:
        raise ValueError('channels must be 1 or 2')


def same_format(left, right):
    return (left.rate, left.channels) == (right.rate, right.channels)


def saturate(value):
    """Clamp a computed sample to the signed 16-bit range."""
    return max(-32768, min(32767, round(value)))


def converted_frame(source, frame, rate, channels, base=0, count=None):
    """Produce one target frame from a PCM source.

    Linear interpolation inside the source window clamps at the window's final
    frame; down-mixing averages channels and up-mixing duplicates the mono
    channel. Shared verbatim by conform() and arrangement rendering so the two
    conversion paths cannot drift apart.
    """
    if count is None:
        count = source.frames
    position = frame * source.rate / rate
    first = min(int(position), count - 1)
    second = min(first + 1, count - 1)
    fraction = position - first
    values = []
    for channel in range(source.channels):
        left = source.samples[(base + first) * source.channels + channel]
        right = source.samples[(base + second) * source.channels + channel]
        values.append(left + (right - left) * fraction)
    if channels == 1:
        return (saturate(sum(values) / len(values)),)
    if source.channels == 1:
        return (saturate(values[0]), saturate(values[0]))
    return tuple(saturate(value) for value in values)


def conform(audio, rate, channels):
    """Upsample and/or convert channels of a material to the target format."""
    validate_target(rate, channels, audio.rate)
    frames = round(audio.frames * rate / audio.rate)
    samples = array.array('h')
    for frame in range(frames):
        samples.extend(converted_frame(audio, frame, rate, channels))
    return Audio(rate, channels, samples)


def describe(audio):
    """Format facts reported for a material or a produced result.

    The facts derive from the same Audio object that waveio.encode serializes,
    so a processed file that is submitted again decodes to exactly these
    sample_rate/channels/frames/duration values.
    """
    return {'sample_rate': audio.rate, 'channels': audio.channels, 'frames': audio.frames,
            'duration_seconds': audio.frames / audio.rate,
            'peak': max(abs(sample) for sample in audio.samples) / PEAK_DENOMINATOR}
