"""SpeechManager, drivers de reserva, seleção de driver, bips e áudio."""

from __future__ import annotations

import asyncio
import stat
import threading
from pathlib import Path

import pytest

from nvda_linux import services
from nvda_linux.contracts import SpeechCommand, SpeechOutput, SpeechPriority, ToneOutput
from nvda_linux.core.config import TomlConfigStore
from nvda_linux.speech import audio, tones
from nvda_linux.speech.characters import describe_character, letter_name
from nvda_linux.speech.driver import (
    BreakSegment,
    IndexSegment,
    TextSegment,
    Utterance,
    VoiceSettings,
    segments_to_ssml,
    segments_to_text,
)
from nvda_linux.speech.drivers import select_driver
from nvda_linux.speech.drivers.espeak import EspeakDriver, language_from_locale
from nvda_linux.speech.drivers.piper import PiperDriver, model_sample_rate
from nvda_linux.speech.drivers.silence import SilenceDriver
from nvda_linux.speech.manager import SpeechManager
from tests.platform.fakes import FakeDriver, wait_for


def make_manager(
    config: TomlConfigStore | None = None, *, tones_out: ToneOutput | None = None
) -> tuple[SpeechManager, FakeDriver]:
    driver = FakeDriver()
    manager = SpeechManager(driver, config=config, tones=tones_out, language="pt")
    manager.start(asyncio.get_running_loop())
    return manager, driver


# ------------------------------------------------------------------ SSML/texto
def test_ssml_and_text_rendering() -> None:
    segs = (
        TextSegment("a < b", pitch=30),
        BreakSegment(400),
        TextSegment("x", spell=True),
        TextSegment("rápido", rate=50, language="en"),
    )
    ssml = segments_to_ssml(segs)
    assert ssml == (
        '<speak><prosody pitch="+30%">a &lt; b</prosody><break time="400ms"/>'
        '<say-as interpret-as="characters">x</say-as>'
        '<voice xml:lang="en"><prosody rate="150%">rápido</prosody></voice></speak>'
    )
    assert segments_to_text(segs) == "a < b . x rápido"


# ------------------------------------------------------------------ manager
async def test_manager_implements_contract() -> None:
    manager, _ = make_manager()
    assert isinstance(manager, SpeechOutput)


async def test_queue_order_and_done() -> None:
    manager, driver = make_manager()
    manager.speak_text("um")
    manager.speak_text("dois")
    assert driver.texts == ["um"]  # um enunciado por vez
    driver.finish()
    await wait_for(lambda: driver.texts == ["um", "dois"])
    driver.finish()
    await wait_for(lambda: not manager.is_speaking)


async def test_next_priority_jumps_queue() -> None:
    manager, driver = make_manager()
    manager.speak_text("a")
    manager.speak_text("b")
    manager.speak_text("urgente", SpeechPriority.NEXT)
    driver.finish()
    await wait_for(lambda: len(driver.texts) == 2)
    assert driver.texts == ["a", "urgente"]


async def test_now_priority_interrupts_and_resumes() -> None:
    manager, driver = make_manager()
    manager.speak_text("longo texto")
    manager.speak_text("agora", SpeechPriority.NOW)
    assert driver.texts == ["longo texto", "agora"]
    assert len(driver.cancel_times) == 1
    driver.finish()
    await wait_for(lambda: len(driver.texts) == 3)
    assert driver.texts[-1] == "longo texto"  # retomado


async def test_cancel_clears_everything_fast() -> None:
    manager, driver = make_manager()
    for i in range(500):
        manager.speak_text(f"frase {i}")
    manager.cancel()
    assert not manager.is_speaking
    assert len(driver.cancel_times) == 1
    assert manager.last_cancel_ns < 30_000_000
    driver.finish()  # done atrasado de enunciado cancelado é ignorado
    await asyncio.sleep(0.01)
    assert len(driver.spoken) == 1


async def test_commands_pitch_break_lang_and_unknown() -> None:
    manager, driver = make_manager()
    manager.speak(
        [
            "normal",
            SpeechCommand("pitch", 20),
            "agudo",
            SpeechCommand("pitch", 0),
            SpeechCommand("break", 250),
            SpeechCommand("lang", "en"),
            "hello",
            SpeechCommand("misterio", 1),
            "   ",
        ]
    )
    segs = driver.spoken[0].segments
    assert segs[0] == TextSegment("normal")
    assert segs[1] == TextSegment("agudo", pitch=20)
    assert segs[2] == BreakSegment(250)
    assert segs[3] == TextSegment("hello", language="en")
    assert len(segs) == 4


async def test_beep_command_splits_utterance() -> None:
    beeps: list[tuple[float, int]] = []

    class Tones:
        def beep(self, hz: float, duration_ms: int, left: int = 50, right: int = 50) -> None:
            beeps.append((hz, duration_ms))

    manager, driver = make_manager(tones_out=Tones())
    manager.speak([SpeechCommand("beep", "880,40"), "depois do bip", SpeechCommand("beep", 300)])
    assert beeps == [(880.0, 40)]
    assert driver.texts == ["depois do bip"]
    driver.finish()
    await wait_for(lambda: beeps == [(880.0, 40), (300.0, 50)])


async def test_spelling_with_capitals(config: TomlConfigStore) -> None:
    config.set("speech.sayCapForCapitals", True)
    manager, driver = make_manager(config)
    manager.speak_spelling("Ab ?")
    segs = driver.spoken[0].segments
    assert segs[0] == TextSegment("maiúscula", pitch=30)
    assert segs[1] == TextSegment("A", pitch=30, spell=True)
    assert segs[2] == TextSegment("b", spell=True)
    assert segs[3] == TextSegment("espaço")
    assert segs[4] == TextSegment("interrogação")


async def test_spelling_without_engine_support_uses_letter_names() -> None:
    driver = SilenceDriver()
    type(driver).supports_spelling = False
    try:
        manager = SpeechManager(driver, language="pt")
        manager.start(asyncio.get_running_loop())
        manager.speak_spelling("b")
        assert driver.spoken[0].segments[0] == TextSegment("bê")
    finally:
        type(driver).supports_spelling = True


async def test_beep_for_capitals(config: TomlConfigStore) -> None:
    beeps: list[float] = []

    class Tones:
        def beep(self, hz: float, duration_ms: int, left: int = 50, right: int = 50) -> None:
            beeps.append(hz)

    config.set("speech.beepForCapitals", True)
    config.set("speech.capPitchChange", 0)
    manager, driver = make_manager(config, tones_out=Tones())
    manager.speak_spelling("X")
    assert beeps == [2000.0]
    assert driver.spoken[0].segments == (TextSegment("X", spell=True),)


async def test_pause_holds_queue() -> None:
    manager, driver = make_manager()
    manager.pause(True)
    manager.speak_text("espera")
    assert driver.spoken == [] and driver.paused == [True]
    manager.pause(False)
    assert driver.texts == ["espera"]


async def test_typed_characters_and_words(config: TomlConfigStore) -> None:
    config.set("keyboard.speakTypedWords", True)
    manager, driver = make_manager(config)
    driver.auto_done = True
    for ch in "oi ":
        manager.on_typed_character(ch)
    await wait_for(lambda: len(driver.spoken) == 4)
    assert driver.texts == ["o", "i", "oi", "espaço"]
    manager.on_typed_character("x")
    manager.flush_typed_word()
    await wait_for(lambda: driver.texts[-1] == "x")


# ------------------------------------------------------------------ índices
class MarkDriver(FakeDriver):
    """Driver que entende <mark/> (como o Speech Dispatcher)."""

    supports_index_marks = True


def make_indexed(
    driver: FakeDriver | None = None,
) -> tuple[SpeechManager, FakeDriver, list[int]]:
    driver = driver or FakeDriver()
    manager = SpeechManager(driver, language="pt")
    manager.start(asyncio.get_running_loop())
    reached: list[int] = []
    manager.add_index_listener(reached.append)
    return manager, driver, reached


def idx(n: int) -> SpeechCommand:
    return SpeechCommand("index", n)


def test_index_becomes_ssml_mark() -> None:
    ssml = segments_to_ssml((TextSegment("um"), IndexSegment(3), TextSegment("dois")))
    assert ssml == '<speak>um<mark name="3"/>dois</speak>'
    assert segments_to_text((TextSegment("um"), IndexSegment(3))) == "um"


async def test_index_without_marks_fires_after_each_chunk() -> None:
    manager, driver, reached = make_indexed()
    manager.speak(["linha um", idx(1), "linha dois", idx(2)])
    assert driver.texts == ["linha um"] and reached == []
    driver.finish()
    await wait_for(lambda: driver.texts == ["linha um", "linha dois"])
    assert reached == [1]
    driver.finish()
    await wait_for(lambda: reached == [1, 2])
    assert not manager.is_speaking


async def test_index_without_text_fires_at_once() -> None:
    manager, _driver, reached = make_indexed()
    manager.speak([idx(5), "   ", SpeechCommand("index", "6"), SpeechCommand("index", "x")])
    assert reached == [5, 6]


async def test_cancel_drops_pending_indexes() -> None:
    manager, driver, reached = make_indexed()
    manager.speak(["a", idx(1), "b", idx(2)])
    manager.cancel()
    driver.finish()  # fim atrasado do enunciado cancelado
    await asyncio.sleep(0.01)
    assert reached == []


async def test_marks_driver_keeps_one_utterance_and_reports_in_order() -> None:
    manager, driver, reached = make_indexed(MarkDriver())
    manager.speak(["um", idx(1), "dois", idx(2), "três"])
    assert len(driver.spoken) == 1 and driver.spoken[0].indexes == (1, 2)
    utt = driver.spoken[0].id
    driver.notify_index(utt, 2)  # o motor pulou o 1: sai antes, na ordem
    await wait_for(lambda: reached == [1, 2])
    driver.notify_index(utt, 1)  # repetido/atrasado: ignorado
    driver.finish()
    await asyncio.sleep(0.01)
    assert reached == [1, 2]


async def test_marks_not_reported_fire_when_utterance_ends() -> None:
    manager, driver, reached = make_indexed(MarkDriver())
    manager.speak(["um", idx(1), "dois", idx(2)])
    driver.finish()
    await wait_for(lambda: reached == [1, 2])


async def test_listener_cancel_stops_remaining_marks() -> None:
    manager, driver, reached = make_indexed(MarkDriver())
    manager.add_index_listener(lambda n: manager.cancel())
    manager.speak(["um", idx(1), "dois", idx(2)])
    driver.finish()
    await asyncio.sleep(0.01)
    assert reached == [1]


async def test_index_of_stale_utterance_is_ignored_and_listener_removal() -> None:
    manager, driver, reached = make_indexed(MarkDriver())
    later: list[int] = []
    remove = manager.add_index_listener(later.append)
    manager.speak(["um", idx(1)])
    old = driver.spoken[0].id
    manager.cancel()
    driver.notify_index(old, 1)
    await asyncio.sleep(0.01)
    assert reached == []
    remove()
    manager.speak(["dois", idx(2)])
    driver.finish()
    await wait_for(lambda: reached == [2])
    assert later == []


class _Focus:
    def __init__(self, protected: bool | None) -> None:
        self.protected = protected

    def focus_description(self) -> str:
        return "campo"

    def focus_is_protected(self) -> bool:
        if self.protected is None:
            raise RuntimeError("objeto morto")
        return self.protected


async def test_password_field_never_speaks_typed_characters(config: TomlConfigStore) -> None:
    config.set("keyboard.speakTypedWords", True)
    services.register("focus", _Focus(True))
    manager, driver = make_manager(config)
    driver.auto_done = True
    heard: list[str] = []
    manager.add_listener(heard.append)
    for ch in "ab1 ":
        manager.on_typed_character(ch)
    manager.flush_typed_word()
    await wait_for(lambda: len(driver.spoken) == 4)
    await asyncio.sleep(0.01)
    assert driver.texts == ["asterisco"] * 4
    assert heard == ["asterisco"] * 4  # nem o Visualizador de Fala vê a senha


async def test_password_echo_off_is_silent(config: TomlConfigStore) -> None:
    config.set("keyboard.speakTypedCharacters", False)
    services.register("focus", _Focus(True))
    manager, driver = make_manager(config)
    manager.on_typed_character("a")
    assert driver.spoken == []


async def test_focus_query_failure_is_treated_as_password(config: TomlConfigStore) -> None:
    services.register("focus", _Focus(None))
    manager, driver = make_manager(config)
    manager.on_typed_character("s")
    assert driver.texts == ["asterisco"]


async def test_normal_field_still_echoes(config: TomlConfigStore) -> None:
    services.register("focus", _Focus(False))
    manager, driver = make_manager(config)
    manager.on_typed_character("s")
    assert driver.texts == ["s"]


async def test_config_changes_reach_driver(config: TomlConfigStore) -> None:
    _manager, driver = make_manager(config)
    config.set("speech.rate", 77)
    assert driver.settings.rate == 77


async def test_listeners_and_set_driver() -> None:
    manager, driver = make_manager()
    heard: list[str] = []
    remove = manager.add_listener(heard.append)
    manager.speak_text("visualizador")
    assert heard == ["visualizador"]
    remove()
    new = FakeDriver()
    await manager.set_driver(new)
    assert driver.terminated and manager.driver is new
    manager.speak_text("novo")
    assert new.texts == ["novo"] and heard == ["visualizador"]


async def test_driver_exceptions_do_not_escape() -> None:
    class Broken(FakeDriver):
        def speak(self, utterance: Utterance) -> None:
            raise RuntimeError("quebrado")

        def cancel(self) -> None:
            raise RuntimeError("quebrado")

    manager = SpeechManager(Broken())
    manager.start(asyncio.get_running_loop())
    manager.speak_text("x")
    manager.cancel()
    assert not manager.is_speaking


# ------------------------------------------------------------------ caracteres
def test_character_names() -> None:
    assert describe_character(" ", "pt") == "espaço"
    assert describe_character(" ", "en") == "space"
    assert describe_character("ç", "pt", spell_letters=True) == "cê cedilha"
    assert letter_name("W", "en") == "double you"
    assert describe_character("\x07") == "U+0007"


# ------------------------------------------------------------------ drivers
def test_locale_to_espeak_voice() -> None:
    assert language_from_locale({"LANG": "pt_BR.UTF-8"}) == "pt-br"
    assert language_from_locale({"LANG": "C"}) == "en"


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


async def test_espeak_driver_subprocess(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    exe = _script(tmp_path / "espeak-ng", f'echo "$@" > {out}.args\ncat > {out}\n')
    driver = EspeakDriver(str(exe))
    done: list[int] = []
    driver.bind(asyncio.get_running_loop(), done.append)
    await driver.initialize()
    driver.apply_settings(VoiceSettings(rate=0, pitch=99, volume=100, voice="pt-br"))
    driver.speak(Utterance(9, (TextSegment("olá"),)))
    await wait_for(lambda: done == [9])
    assert out.read_text(encoding="utf-8") == "<speak>olá</speak>"
    args = Path(f"{out}.args").read_text(encoding="utf-8").split()
    assert args[:2] == ["-m", "--stdin"]
    assert args[args.index("-s") + 1] == "80" and args[args.index("-v") + 1] == "pt-br"


async def test_espeak_cancel_kills_process(tmp_path: Path) -> None:
    exe = _script(tmp_path / "espeak-ng", "cat > /dev/null\nsleep 5\n")
    driver = EspeakDriver(str(exe))
    done: list[int] = []
    driver.bind(asyncio.get_running_loop(), done.append)
    await driver.initialize()
    driver.speak(Utterance(1, (TextSegment("longo"),)))
    await wait_for(lambda: driver._proc is not None)
    proc = driver._proc
    driver.cancel()
    assert proc is not None
    await asyncio.wait_for(proc.wait(), 2)
    await asyncio.sleep(0.05)
    assert done == []
    await driver.terminate()


async def test_piper_driver_streams_pcm(tmp_path: Path) -> None:
    model = tmp_path / "voz.onnx"
    model.write_bytes(b"")
    (tmp_path / "voz.onnx.json").write_text('{"audio": {"sample_rate": 16000}}', encoding="utf-8")
    assert model_sample_rate(model) == 16000
    exe = _script(tmp_path / "piper", "cat > /dev/null\nprintf 'PCMDATA'\n")
    player = audio.NullPlayer()
    driver = PiperDriver(str(exe), str(model), player=player)
    done: list[int] = []
    driver.bind(asyncio.get_running_loop(), done.append)
    await driver.initialize()
    assert driver.sample_rate == 16000
    driver.speak(Utterance(4, (TextSegment("oi"),)))
    await wait_for(lambda: done == [4])
    assert player.played == [(7, 16000, 1)]


async def test_select_driver_falls_back_to_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    from nvda_linux.speech.drivers.espeak import EspeakDriver as E
    from nvda_linux.speech.drivers.piper import PiperDriver as P
    from nvda_linux.speech.drivers.speechdispatcher import SpeechDispatcherDriver as S

    for cls in (E, P, S):
        monkeypatch.setattr(cls, "check", classmethod(lambda c: False))
    driver = await select_driver("auto", lambda k, d: d)
    assert driver.name == "silence"
    driver = await select_driver("piper", lambda k, d: d)
    assert driver.name == "silence"


# ------------------------------------------------------------------ bips
def test_generate_tone_shape_and_channels() -> None:
    pcm = tones.generate_tone(440.0, 100, left=100, right=0, volume=100)
    assert len(pcm) == int(tones.SAMPLE_RATE * 0.1) * 4
    import array

    samples = array.array("h", pcm)
    left, right = samples[0::2], samples[1::2]
    assert max(abs(s) for s in right) == 0
    assert 25000 < max(abs(s) for s in left) <= 32767
    assert abs(left[0]) < 100  # rampa de entrada: sem estalo
    assert tones.generate_tone(440.0, 0) == b""
    assert tones.generate_tone(-1, 50) == b""


def test_python_and_numpy_generators_match() -> None:
    a = tones._tone_python(523.0, 500, 44100, 50, 1000.0, 2000.0)
    if tones._np is not None:
        assert a == tones._tone_numpy(523.0, 500, 44100, 50, 1000.0, 2000.0)


async def test_tone_generator_is_non_blocking_and_threadsafe() -> None:
    gen = tones.ToneGenerator(audio.NullPlayer(), volume=50)
    assert isinstance(gen, ToneOutput)
    gen.bind(asyncio.get_running_loop())
    gen.beep(440, 30)
    worker = threading.Thread(target=gen.beep, args=(880, 30))
    worker.start()
    worker.join()
    await wait_for(lambda: len(gen.history) == 2)
    assert {h[0] for h in gen.history} == {440, 880}
    await gen.close()


async def test_subprocess_player_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    player = audio.SubprocessPlayer("cat", ["sh", "-c", "cat > /dev/null"])
    await player.play(b"\x00" * 1000, 44100, 2)
    stream = await player.open_stream(22050, 1)
    await stream.write(b"\x00" * 10)
    await stream.finish()
    from nvda_linux.core import compat

    compat.inject_module("sounddevice", None)
    monkeypatch.setattr("nvda_linux.speech.audio.shutil.which", lambda name: None)
    try:
        assert isinstance(audio.create_player(), audio.NullPlayer)
    finally:
        compat.reset_cache()
