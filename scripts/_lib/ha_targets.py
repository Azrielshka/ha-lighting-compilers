# -*- coding: utf-8 -*-
"""
ha_targets.py
Раскладка: какой локальный артефакт куда едет на Home Assistant.

Чистая логика, сети не касается. Вынесена отдельно, чтобы проверяться
тестами целиком — в отличие от транспорта, который без живого HA не проверить.

Конфигурация на стороне HA (у владельца уже такая, менять не надо):

    homeassistant:
      packages: !include_dir_merge_named includes/packages/

    automation manual: !include_dir_merge_list  includes/automations/
    script manual:     !include_dir_merge_named includes/scripts/

⚠ Форматы не взаимозаменяемы:
    merge_list  ждёт СПИСОК   -> домен automation: в HA список и есть
    merge_named ждёт СЛОВАРЬ  -> домен script: словарь
Перепутать = конфигурация не загрузится. Сторожат тесты генераторов.

Префикс zm_ в именах файлов — чтобы деплой перезаписывал только своё
и никогда не трогал файлы наладчика.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Корень конфигурации Home Assistant.
HA_CONFIG_ROOT = "/config"

# Куда blueprint'ы кладутся на HA (совпадает с canon.BLUEPRINT_DIR).
BLUEPRINTS_SUBDIR = "blueprints/automation/zone_manager"


@dataclass(frozen=True)
class FileTarget:
    """Один файл: откуда взять локально и куда положить на HA."""
    local: Path
    remote: str          # полный путь на HA
    target: str          # к какой галочке относится

    @property
    def exists(self) -> bool:
        return self.local.exists()

    @property
    def size(self) -> int:
        return self.local.stat().st_size if self.local.exists() else 0

    @property
    def remote_dir(self) -> str:
        return self.remote.rsplit("/", 1)[0]


@dataclass(frozen=True)
class Plan:
    """Что именно поедет на HA."""
    files: List[FileTarget]
    areas_file: Optional[Path]   # None, если пространства не выбраны

    @property
    def missing(self) -> List[FileTarget]:
        """Артефакты, которых нет на диске: шаг пайплайна не запускали."""
        return [f for f in self.files if not f.exists]

    @property
    def ready(self) -> List[FileTarget]:
        return [f for f in self.files if f.exists]

    @property
    def remote_dirs(self) -> List[str]:
        """Папки, которые должны существовать на HA (создаём, если их нет)."""
        return sorted({f.remote_dir for f in self.ready})

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.ready)


# Галочки деплоя. Порядок задаёт порядок в отчётах и в UI.
TARGETS: Tuple[str, ...] = (
    "lights",
    "scripts",
    "automations",
    "blueprints",
    "areas",
)

TARGET_TITLES: Dict[str, str] = {
    "lights": "Группы света",
    "scripts": "Скрипты",
    "automations": "Автоматизации",
    "blueprints": "Blueprint'ы",
    "areas": "Пространства и этажи",
}

# Группы света: локальное имя -> имя на HA.
# Пакеты, файл начинается с корневого ключа (lights_group: и т.д.).
LIGHT_GROUP_FILES: Dict[str, str] = {
    "lights_group.yaml": "zm_lights_group.yaml",
    "lights_general_groups.yaml": "zm_lights_general_groups.yaml",
    "lights_floor_groups.yaml": "zm_lights_floor_groups.yaml",
}


def build_plan(
    data_dir: Path,
    targets: List[str],
    config_root: str = HA_CONFIG_ROOT,
) -> Plan:
    """
    Собрать план деплоя: какие файлы куда поедут.

    data_dir — папка data/ проекта (там лежат артефакты генераторов).
    targets  — выбранные галочки.

    Файлы, которых нет на диске, в план попадают, но помечаются как missing:
    наладчик должен увидеть, что шаг пайплайна не запускался, а не гадать,
    почему на HA чего-то не хватает.
    """
    unknown = [t for t in targets if t not in TARGETS]
    if unknown:
        raise ValueError(
            f"неизвестные цели: {', '.join(unknown)}; есть: {', '.join(TARGETS)}"
        )

    root = config_root.rstrip("/")
    files: List[FileTarget] = []

    if "lights" in targets:
        for local_name, remote_name in LIGHT_GROUP_FILES.items():
            files.append(FileTarget(
                local=data_dir / "light_groups" / local_name,
                remote=f"{root}/includes/packages/{remote_name}",
                target="lights",
            ))

    if "scripts" in targets:
        files.append(FileTarget(
            local=data_dir / "scripts" / "scripts.yaml",
            remote=f"{root}/includes/scripts/zm_scripts.yaml",
            target="scripts",
        ))

    if "automations" in targets:
        files.append(FileTarget(
            local=data_dir / "automations" / "automations.yaml",
            remote=f"{root}/includes/automations/zm_automations.yaml",
            target="automations",
        ))

    if "blueprints" in targets:
        # Blueprint'ы одинаковы на всех объектах, переименовывать нечего:
        # на их имена ссылаются автоматизации через use_blueprint.path.
        blueprints_dir = data_dir / "blueprints"
        for path in sorted(blueprints_dir.glob("*.yaml")):
            files.append(FileTarget(
                local=path,
                remote=f"{root}/{BLUEPRINTS_SUBDIR}/{path.name}",
                target="blueprints",
            ))

        if not blueprints_dir.exists():
            # Папки нет вовсе — покажем это как отсутствующий артефакт,
            # иначе цель просто молча исчезнет из плана.
            files.append(FileTarget(
                local=blueprints_dir / "zm_default_on.yaml",
                remote=f"{root}/{BLUEPRINTS_SUBDIR}/zm_default_on.yaml",
                target="blueprints",
            ))

    areas_file: Optional[Path] = None
    if "areas" in targets:
        # Areas и Floors — не файлы: они создаются в реестрах HA по WebSocket.
        areas_file = data_dir / "areas" / "areas.yaml"

    return Plan(files=files, areas_file=areas_file)


def missing_pipeline_steps(plan: Plan) -> List[str]:
    """
    Какие шаги пайплайна надо запустить, чтобы недостающие артефакты появились.
    Внятный совет вместо «файл не найден».
    """
    # blueprints кладёт тот же generate_automations.py — не советуем дважды.
    steps = {
        "lights": "generate_lights_groups.py / generate_general_groups.py / generate_floor_groups.py",
        "scripts": "generate_scripts.py",
        "automations": "generate_automations.py",
        "blueprints": "generate_automations.py",
        "areas": "generate_areas.py",
    }

    needed = {f.target for f in plan.missing}

    if plan.areas_file is not None and not plan.areas_file.exists():
        needed.add("areas")

    ordered = [steps[t] for t in TARGETS if t in needed]

    # Убираем повторы, сохраняя порядок.
    return list(dict.fromkeys(ordered))
