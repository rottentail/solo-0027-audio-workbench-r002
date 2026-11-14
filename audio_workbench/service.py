import base64
import binascii
from . import formats, processing, waveio


def audio_from(value):
    if not isinstance(value, str):
        raise ValueError('audio must be base64 text')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('invalid base64 audio') from exc
    return waveio.decode(raw)


def output(audio):
    # One description path for both clip and mix: the encoded WAV and the
    # reported properties are derived from the same Audio object.
    return {'audio': base64.b64encode(waveio.encode(audio)).decode('ascii'),
            'properties': formats.describe(audio)}


def execute(path, body):
    if not isinstance(body, dict):
        raise ValueError('request must be a JSON object')
    if path == '/inspect':
        return formats.describe(audio_from(body.get('audio')))
    if path == '/clip':
        return output(processing.clip(audio_from(body.get('audio')), body.get('start'),
                                      body.get('end'), body.get('gain', 1)))
    if path == '/mix':
        tracks = body.get('tracks')
        if not isinstance(tracks, list) or not 1 <= len(tracks) <= 8:
            raise ValueError('tracks must contain between 1 and 8 items')
        if any(not isinstance(track, dict) for track in tracks):
            raise ValueError('each track must be an object')
        decoded = [(audio_from(t.get('audio')), t.get('offset', 0), t.get('gain', 1)) for t in tracks]
        target = body.get('format')
        if target is not None:
            if not isinstance(target, dict):
                raise ValueError('format must be an object')
            rate, channels = target.get('sample_rate'), target.get('channels')
            decoded = [(formats.conform(audio, rate, channels), offset, gain)
                       for audio, offset, gain in decoded]
        return output(processing.mix(decoded))
    raise LookupError('unknown endpoint')
