import array
import base64
import unittest

from audio_workbench import formats, processing, service, waveio


def wav(rate, channels, samples):
    return waveio.encode(waveio.Audio(rate, channels, array.array('h', samples)))


def b64(data):
    return base64.b64encode(data).decode('ascii')


class FormatContractTests(unittest.TestCase):
    def test_constants_match_legacy_material_limits(self):
        self.assertEqual((formats.MIN_RATE, formats.MAX_RATE), (8000, 48000))
        self.assertEqual(formats.CHANNEL_CHOICES, (1, 2))
        self.assertEqual(formats.SAMPLE_WIDTH, 2)
        self.assertEqual(formats.MAX_SECONDS, 30)

    def test_waveio_uses_the_shared_header_and_duration_rules(self):
        self.assertTrue(formats.valid_wav_header(1, 2, 8000))
        self.assertFalse(formats.valid_wav_header(3, 2, 8000))
        self.assertFalse(formats.valid_wav_header(1, 4, 8000))
        self.assertFalse(formats.valid_wav_header(1, 2, 48001))
        self.assertTrue(formats.valid_duration(1, 8000))
        self.assertFalse(formats.valid_duration(0, 8000))
        self.assertFalse(formats.valid_duration(8000 * 30 + 1, 8000))
        # Same facts must be enforced when actual WAV bytes are decoded.
        import io
        import wave
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(48001)
            writer.writeframes(array.array('h', [1, 2]).tobytes())
        with self.assertRaisesRegex(ValueError, '8000-48000'):
            waveio.decode(buffer.getvalue())
        with self.assertRaisesRegex(ValueError, 'at most 30 seconds'):
            waveio.decode(wav(8000, 1, [0] * (8000 * 30 + 1)))

    def test_legacy_public_names_remain_available(self):
        from audio_workbench.waveio import Audio as WaveAudio
        from audio_workbench.processing import Audio as ProcessingAudio, conform, inspect, saturate
        self.assertIs(WaveAudio, formats.Audio)
        self.assertIs(ProcessingAudio, formats.Audio)
        self.assertIs(conform, formats.conform)
        self.assertIs(saturate, formats.saturate)
        audio = formats.Audio(8000, 1, array.array('h', [10, -20]))
        self.assertEqual(inspect(audio), formats.describe(audio))


class RoundTripFactTests(unittest.TestCase):
    """A produced file re-submitted for inspection reports identical facts."""

    def assert_report_matches_encoded_file(self, response):
        properties = response['properties']
        re_decoded = waveio.decode(base64.b64decode(response['audio']))
        # The same description function backs the standalone inspect endpoint,
        # so re-submitting the produced file reports identical format facts.
        self.assertEqual(formats.describe(re_decoded), properties)
        self.assertEqual(service.execute('/inspect', {'audio': response['audio']}), properties)

    def test_clip_output_round_trips_through_inspect(self):
        source = b64(wav(16000, 2, [3000, -3000, 1200, -1200] * 4000))
        response = service.execute('/clip', {'audio': source, 'start': 0, 'end': .25, 'gain': 1.5})
        self.assert_report_matches_encoded_file(response)

    def test_mix_output_round_trips_through_inspect(self):
        mono = b64(wav(8000, 1, [1000, -2000] * 400))
        stereo = b64(wav(8000, 2, [100, -100, 200, -200] * 200))
        response = service.execute('/mix', {'tracks': [
            {'audio': mono, 'offset': 0, 'gain': 1.25},
            {'audio': mono, 'offset': .01, 'gain': .75}]})
        self.assert_report_matches_encoded_file(response)
        converted = service.execute('/mix', {'tracks': [
            {'audio': mono}, {'audio': stereo, 'offset': 0, 'gain': 2}],
            'format': {'sample_rate': 48000, 'channels': 2}})
        self.assertEqual(converted['properties']['sample_rate'], 48000)
        self.assertEqual(converted['properties']['channels'], 2)
        self.assert_report_matches_encoded_file(converted)

    def test_describe_derives_from_the_audio_that_gets_encoded(self):
        audio = processing.clip(formats.Audio(8000, 1, array.array('h', [100, -200, 300])),
                                0, 2 / 8000, 1)
        encoded = waveio.encode(audio)
        self.assertEqual(formats.describe(audio),
                         formats.describe(waveio.decode(encoded)))


class SharedConversionTests(unittest.TestCase):
    def test_rendering_uses_the_same_frame_conversion_as_conform(self):
        for source_channels in (1, 2):
            for target_channels in (1, 2):
                source = formats.Audio(12000, source_channels,
                                       array.array('h', [v % 30000 - 15000
                                                         for v in range(120 * source_channels)]))
                converted = formats.conform(source, 48000, target_channels)
                samples = array.array('h')
                for frame in range(converted.frames):
                    samples.extend(formats.converted_frame(source, frame, 48000, target_channels))
                self.assertEqual(list(samples), list(converted.samples))

    def test_windowed_conversion_matches_clip_then_conform(self):
        source = formats.Audio(16000, 2,
                               array.array('h', [v % 30000 - 15000 for v in range(320)]))
        base, count = 40, 80
        trimmed = processing.clip(source, base / 16000, (base + count) / 16000, 1)
        expected = formats.conform(trimmed, 44100, 1)
        samples = array.array('h')
        for frame in range(expected.frames):
            samples.extend(formats.converted_frame(source, frame, 44100, 1,
                                                   base=base, count=count))
        self.assertEqual(list(samples), list(expected.samples))

    def test_upsampling_gain_and_saturation_rules_are_unchanged(self):
        self.assertEqual(formats.saturate(40000.4), 32767)
        self.assertEqual(formats.saturate(-40000.6), -32768)
        self.assertEqual(formats.saturate(1.5), 2)
        audio = formats.Audio(8000, 1, array.array('h', [30000]))
        with self.assertRaisesRegex(ValueError, 'through 48000'):
            formats.conform(audio, 7999, 1)
        with self.assertRaisesRegex(ValueError, 'through 48000'):
            formats.conform(audio, 8000.0, 1)
        with self.assertRaisesRegex(ValueError, 'through 48000'):
            formats.conform(formats.Audio(12000, 1, array.array('h', [1])), 8000, 1)
        with self.assertRaisesRegex(ValueError, 'channels must be 1 or 2'):
            formats.conform(audio, 8000, 3)


if __name__ == '__main__':
    unittest.main()
