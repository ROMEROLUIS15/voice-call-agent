"""Comparison of text-to-speech voices on the phone line: latency to the first audio and samples.

    uv run --env-file .env python -m evals.text_to_speech_comparison [options]

Measures the "first token → first audio" segment of the latency budget (manifest §6) for each
voice and keeps phone-quality samples of every reply, to choose the voice by ear (manifest §12).
"""
