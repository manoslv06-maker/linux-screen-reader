"""Ler tudo com índices: lotes, cursor acompanhando a fala e interrupção."""

from __future__ import annotations

from collections.abc import Callable

from nvda_linux import services
from nvda_linux.scripts import sayAll
from nvda_linux.scripts.runtime import Runtime
from tests.semantics.conftest import Platform
from tests.semantics.fakes import FakeSpeech
from tests.semantics.helpers import focus, obj, press
from tests.semantics.pages import build_dialog, build_web_page


class ListSource:
    """``n`` linhas falsas; a linha ``i`` começa na posição ``10 * i``."""

    def __init__(self, n: int) -> None:
        self.lines = [(10 * i, [f"linha {i}"]) for i in range(n)]
        self.moved: list[int] = []

    def next_line(self) -> tuple[int, list[str]] | None:
        return self.lines.pop(0) if self.lines else None

    def move_to(self, position: int) -> None:
        self.moved.append(position)


class NoIndexSpeech(FakeSpeech):
    """Fala de uma PLATAFORMA antiga, sem ``add_index_listener``."""

    def add_index_listener(self, listener: Callable[[int], None]) -> Callable[[], None]:
        raise AttributeError("add_index_listener")


def test_batches_follow_the_speech(platform: Platform) -> None:
    speech = platform.speech
    speech.auto_index = False
    source = ListSource(25)
    sayAll.start(source)
    assert len(speech.pending_indexes) == sayAll.BATCH_LINES
    for _ in range(sayAll.BATCH_LINES - 1):
        speech.reach_next()
    assert source.moved == [0, 10, 20, 30, 40, 50, 60, 70, 80]
    assert speech.pending_indexes and len(speech.utterances) == 10  # nada novo ainda
    speech.reach_next()  # chegou na última linha do lote: o próximo entra na fila
    assert len(speech.utterances) == 20
    while speech.reach_next() is not None:
        pass
    assert source.moved == [10 * i for i in range(25)]
    assert not sayAll.controller().active


def test_interruption_keeps_cursor_on_current_line(platform: Platform) -> None:
    speech = platform.speech
    speech.auto_index = False
    source = ListSource(25)
    sayAll.start(source)
    speech.reach_next()
    speech.reach_next()
    speech.cancel()  # o usuário apertou uma tecla
    assert speech.reach_next() is None
    assert source.moved == [0, 10]
    assert len(speech.utterances) == 10  # nenhum lote novo depois da interrupção


def test_new_say_all_replaces_the_old_one(platform: Platform) -> None:
    speech = platform.speech
    speech.auto_index = False
    first, second = ListSource(5), ListSource(3)
    sayAll.start(first)
    speech.reach_next()
    sayAll.start(second)  # cancela a fala do primeiro
    while speech.reach_next() is not None:
        pass
    assert first.moved == [0]
    assert second.moved == [0, 10, 20]


def test_without_index_support_reads_everything_at_once(platform: Platform) -> None:
    speech = NoIndexSpeech()
    services.register("speech", speech)
    source = ListSource(25)
    sayAll.start(source)
    assert len(speech.utterances) == 25
    assert source.moved == [240]
    assert not sayAll.controller().active


async def test_browse_mode_cursor_stops_where_speech_stopped(
    rt: Runtime, platform: Platform
) -> None:
    speech = platform.speech
    speech.auto_index = False
    page = build_web_page()
    focus(rt, page.doc)
    ti = rt.tree_interceptors.get_for(obj(page.doc))
    assert ti is not None
    assert speech.text.startswith("Página de Teste documento")  # título não foi cancelado
    assert "Fim da página." not in speech.text  # só o primeiro lote
    for _ in range(4):  # Início, Notícias, Contato, Bem-vindo
        speech.reach_next()
    speech.cancel()
    assert ti.caret == ti.buffer.text.index("Bem-vindo")
    speech.auto_index = True
    speech.clear()
    assert await press(rt, "kb:downarrow")
    assert speech.text.startswith("Leia as")


async def test_browse_mode_say_all_reaches_the_end(rt: Runtime, platform: Platform) -> None:
    speech = platform.speech
    speech.auto_index = False
    page = build_web_page()
    focus(rt, page.doc)
    ti = rt.tree_interceptors.get_for(obj(page.doc))
    assert ti is not None
    while speech.reach_next() is not None:
        pass
    assert "Fim da página." in speech.text
    assert ti.caret == ti.buffer.text.index("Fim da página.")


async def test_say_all_in_text_field_moves_review_cursor(
    rt: Runtime, platform: Platform
) -> None:
    d = build_dialog()
    focus(rt, d.entry)
    speech = platform.speech
    speech.auto_index = False
    speech.clear()
    assert await press(rt, "kb:nvda+downarrow")
    assert speech.text == "relatorio.txt | segunda linha"
    speech.reach_next()
    review = rt.focus.review
    assert review is not None and review.start == 0
    speech.reach_next()
    review = rt.focus.review
    assert review is not None and review.start == len("relatorio.txt\n")
