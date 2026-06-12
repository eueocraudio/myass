"""Nível 1 do broker: a tabela de classes de recurso sobre MEM x CPU.

Uma *classe* é um nó da fila. Cada classe tem um piso de hardware
``(mem_min_mb, cpu_min_cores)``. A tabela default são os quatro quadrantes
descritos em ``CLAUDE.md`` (C1 baixa/baixa, C2 baixa/alta, C3 alta/baixa,
C4 alta/alta), derivados de dois limiares; mas a tabela é *arbitrária* — pode
receber qualquer lista de classes.

Duas operações:

- ``classify(exigencia)`` — em que nó uma atividade é escrita (o W). Escolhe a
  classe de maior piso que a *exigência* da atividade ainda alcança em ambas as
  dimensões. Trabalho pesado cai num nó pesado.
- ``eligible_classes(profile)`` — de quais nós um block pode ler. Uma classe só
  é elegível se o hardware do block satisfaz MEM **e** CPU do piso dela. Um
  block alto/alto lê de tudo; um block baixo/baixo só do nó baixo/baixo.

A tabela não é ordenada por severidade: o casamento é a única regra (revertido
de uma varredura ordenada anterior — ver *Broker* em ``CLAUDE.md``).
"""

from __future__ import annotations

from dataclasses import dataclass

# Defaults dos limiares dos quadrantes (ponto em aberto #5 do CLAUDE.md: os
# valores concretos de operação). Conservadores e sobrescrevíveis.
DEFAULT_MEM_THRESHOLD_MB = 4096
DEFAULT_CPU_THRESHOLD_CORES = 4


@dataclass(frozen=True)
class HwClass:
    """Um nó da fila: um id + o piso de hardware que ele representa."""

    class_id: str
    mem_min_mb: int
    cpu_min_cores: int

    def satisfied_by(self, mem_mb: int, cpu_cores: int) -> bool:
        """True se um hardware ``(mem_mb, cpu_cores)`` atende o piso da classe."""
        return mem_mb >= self.mem_min_mb and cpu_cores >= self.cpu_min_cores

    def dominates(self, other: "HwClass") -> bool:
        """True se este piso é >= o de ``other`` em ambas as dimensões e estritamente
        maior em ao menos uma (dominância de Pareto)."""
        ge = self.mem_min_mb >= other.mem_min_mb and self.cpu_min_cores >= other.cpu_min_cores
        gt = self.mem_min_mb > other.mem_min_mb or self.cpu_min_cores > other.cpu_min_cores
        return ge and gt


class ClassTable:
    """A tabela de classes do broker. Default = os quatro quadrantes MEM x CPU."""

    def __init__(
        self,
        mem_threshold_mb: int = DEFAULT_MEM_THRESHOLD_MB,
        cpu_threshold_cores: int = DEFAULT_CPU_THRESHOLD_CORES,
        classes: list[HwClass] | None = None,
    ):
        self.mem_threshold_mb = mem_threshold_mb
        self.cpu_threshold_cores = cpu_threshold_cores
        if classes is None:
            classes = self._default_quadrants(mem_threshold_mb, cpu_threshold_cores)
        if not classes:
            raise ValueError("a tabela de classes não pode ser vazia")
        ids = [c.class_id for c in classes]
        if len(ids) != len(set(ids)):
            raise ValueError("class_id duplicado na tabela de classes")
        self.classes: list[HwClass] = list(classes)
        self._by_id = {c.class_id: c for c in self.classes}

    @staticmethod
    def _default_quadrants(mem_t: int, cpu_t: int) -> list[HwClass]:
        return [
            HwClass("C1", 0, 0),          # baixa mem / baixa cpu
            HwClass("C2", 0, cpu_t),      # baixa mem / alta cpu
            HwClass("C3", mem_t, 0),      # alta mem  / baixa cpu
            HwClass("C4", mem_t, cpu_t),  # alta mem  / alta cpu
        ]

    @property
    def class_ids(self) -> list[str]:
        return [c.class_id for c in self.classes]

    def get(self, class_id: str) -> HwClass:
        return self._by_id[class_id]

    def classify(self, exigencia: dict | None) -> str:
        """Retorna o ``class_id`` em que uma atividade com esta *exigência* deve
        ser escrita (o W do nível 1).

        Exigência ausente/omissa vira ``0`` — uma atividade sem requisito declarado
        cai no nó de menor piso. Entre as classes cujo piso a exigência satisfaz,
        escolhe a *não dominada* (a de maior piso). Para os quadrantes default há
        sempre exatamente uma; em tabelas arbitrárias com empate de Pareto, o
        desempate é determinístico (maior soma de pisos, depois ``class_id``).
        """
        exigencia = exigencia or {}
        mem = int(exigencia.get("mem_mb", 0) or 0)
        cpu = int(exigencia.get("cpu_cores", 0) or 0)

        candidates = [c for c in self.classes if c.satisfied_by(mem, cpu)]
        if not candidates:
            # Nenhum piso é <= exigência em ambas as dimensões. Isso só acontece
            # se a tabela não tem uma classe-base (0,0). Cai na de menor piso.
            return min(
                self.classes,
                key=lambda c: (c.mem_min_mb + c.cpu_min_cores, c.class_id),
            ).class_id

        # A classe de maior piso entre as satisfeitas (não dominada por outra
        # candidata), com desempate determinístico.
        maximal = [c for c in candidates if not any(d.dominates(c) for d in candidates)]
        return max(
            maximal,
            key=lambda c: (c.mem_min_mb + c.cpu_min_cores, c.class_id),
        ).class_id

    def eligible_classes(self, profile: dict) -> list[str]:
        """Lista de ``class_id`` de que um block com este perfil de hardware pode
        ler — aqueles cujo piso o block satisfaz em MEM **e** CPU.

        Preserva a ordem da tabela (estável para o round-robin de leitura).
        """
        mem = int(profile.get("mem_mb", 0) or 0)
        cpu = int(profile.get("cpu_cores", 0) or 0)
        return [c.class_id for c in self.classes if c.satisfied_by(mem, cpu)]
