# generate_lovelace_cards_v2.py
# ------------------------------------------------------------
# v2.0.0
# Генератор Lovelace-карточек (YAML-вставки) на основе:
# 1) Нормализованных данных (data/normalized/spaces.parquet)
# 2) Манифеста шаблонов (templates/manifest.yaml)
# 3) Каталога шаблонов YAML (templates/<type>/<variant>.yaml)
#
# Плейсхолдеры:
# - [[HEADING]]
# - [[SPACE]]
# - [[GENERAL_LIGHT_ENTITY]]
# - [[ZONE_LIGHT_i]]  -> light.<group_id>
# - [[MS_SENSOR_i]]   -> из ms_sensors_by_group (None -> sensor.unavailable)
#
# Выход:
#   data/lovelace_cards_generated.txt  (блоки {{ ... }} для вставки в Lovelace)
#   data/lovelace_cards_report.json    (отчёт выбора шаблонов и предупреждений)
# ------------------------------------------------------------

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Опционально: PyYAML (для чтения manifest.yaml)
try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # type: ignore


__version__ = "2.0.0"

# ============================================================
# CONFIG (удобно запускать кнопкой в PyCharm)
# ============================================================
# Все относительные пути считаем от корня репозитория.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SPACES_PARQUET = PROJECT_ROOT / "data" / "normalized" / "spaces.parquet"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "templates" / "manifest.yaml"
DEFAULT_TEMPLATES_DIR = PROJECT_ROOT / "templates"

DEFAULT_OUTPUT_TXT = PROJECT_ROOT / "data" / "lovelace_cards_generated.txt"
DEFAULT_REPORT_JSON = PROJECT_ROOT / "data" / "lovelace_cards_report.json"


# ============================================================
# DATA MODELS
# ============================================================

@dataclass(frozen=True)
class TemplateRef:
    """Ссылка на файл шаблона + список плейсхолдеров (для контроля)."""
    file: str
    placeholders: List[str]


@dataclass(frozen=True)
class CardTypeManifest:
    """Описание card_type из manifest.yaml."""
    title: str
    variants: Dict[int, TemplateRef]
    fallback_nearest_variant: bool


# ============================================================
# MANIFEST / TEMPLATES
# ============================================================

def _require_yaml() -> None:
    """Проверка зависимости PyYAML."""
    if yaml is None:
        raise RuntimeError("Не найден модуль 'yaml'. Установи: pip install pyyaml")


def load_manifest(path: Path) -> Dict[str, CardTypeManifest]:
    """Читает manifest.yaml и преобразует к структуре для быстрого выбора шаблонов."""
    _require_yaml()

    if not path.exists():
        raise FileNotFoundError(f"Manifest не найден: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))  # type: ignore
    card_types = raw.get("card_types", {}) or {}

    out: Dict[str, CardTypeManifest] = {}
    for card_type_key, cfg in card_types.items():
        title = str(cfg.get("title", card_type_key))
        variants_raw = cfg.get("variants", {}) or {}
        fallback_cfg = cfg.get("fallback", {}) or {}
        nearest = bool(fallback_cfg.get("nearest_variant", True))

        variants: Dict[int, TemplateRef] = {}
        for k, v in variants_raw.items():
            try:
                n = int(str(k))
            except ValueError:
                continue

            file_ = str(v.get("file", "")).strip()
            placeholders = list(v.get("placeholders", []) or [])
            variants[n] = TemplateRef(file=file_, placeholders=placeholders)

        out[str(card_type_key)] = CardTypeManifest(
            title=title,
            variants=variants,
            fallback_nearest_variant=nearest,
        )

    return out


def pick_variant(
    manifest: Dict[str, CardTypeManifest],
    card_type: str,
    groups_count: int,
) -> Tuple[str, int, TemplateRef, str]:
    """
    Выбирает шаблон по (card_type, groups_count).
    Возвращает: used_type, used_variant, TemplateRef, reason
    """
    used_type = card_type if card_type in manifest else "generic"
    ct = manifest.get(used_type)

    if ct is None or not ct.variants:
        raise RuntimeError(f"В manifest нет вариантов для card_type='{used_type}'")

    if groups_count in ct.variants:
        return used_type, groups_count, ct.variants[groups_count], "exact"

    if ct.fallback_nearest_variant:
        available = sorted(ct.variants.keys())
        nearest = min(available, key=lambda x: abs(x - groups_count))
        return used_type, nearest, ct.variants[nearest], f"nearest({groups_count}->{nearest})"

    smallest = min(ct.variants.keys())
    return used_type, smallest, ct.variants[smallest], f"fallback_smallest({groups_count}->{smallest})"


def load_template_text(templates_dir: Path, ref: TemplateRef) -> str:
    """Загружает текст YAML-шаблона (как текст, без парсинга YAML)."""
    file_path = (templates_dir / ref.file).resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Template file не найден: {file_path}")
    return file_path.read_text(encoding="utf-8")


# ============================================================
# PLACEHOLDERS
# ============================================================

def build_heading(space: str) -> str:
    """Заголовок карточки (простое правило: '_' -> ' ')."""
    return str(space).replace("_", " ").strip()


def as_light_entity(group_id: str) -> str:
    """ZONE_LIGHT_i = light.<group_id>."""
    return f"light.{str(group_id).strip()}"


def render_placeholders(
    template_text: str,
    space: str,
    general_light_entity: str,
    groups: List[str],
    ms_sensors_by_group: List[Optional[str]],
) -> Tuple[str, List[str]]:
    """Подстановка [[...]] плейсхолдеров в текст шаблона."""
    warnings: List[str] = []
    rendered = template_text

    # База
    rendered = rendered.replace("[[HEADING]]", build_heading(space))
    rendered = rendered.replace("[[SPACE]]", str(space))
    rendered = rendered.replace("[[GENERAL_LIGHT_ENTITY]]", str(general_light_entity))

    # Зоны
    for i, gid in enumerate(groups, start=1):
        rendered = rendered.replace(f"[[ZONE_LIGHT_{i}]]", as_light_entity(gid))

    # Датчики по группам
    for i, sensor in enumerate(ms_sensors_by_group, start=1):
        ph = f"[[MS_SENSOR_{i}]]"
        if ph not in rendered:
            continue

        if sensor is None or (isinstance(sensor, float) and pd.isna(sensor)) or not str(sensor).strip():
            rendered = rendered.replace(ph, "sensor.unavailable")
            warnings.append(f"missing_ms_sensor: index {i}")
        else:
            rendered = rendered.replace(ph, str(sensor).strip())

    # Если остались незаменённые плейсхолдеры — пишем предупреждение
    if "[[ZONE_LIGHT_" in rendered or "[[MS_SENSOR_" in rendered:
        warnings.append("unresolved_placeholders: template expects more zones/sensors than provided")

    return rendered, warnings


# ============================================================
# GENERATION
# ============================================================

def generate_cards(
    spaces_parquet: Path,
    manifest_path: Path,
    templates_dir: Path,
    output_txt: Path,
    report_json: Path,
) -> None:
    """Генерация карточек из spaces.parquet + manifest + templates."""
    if not spaces_parquet.exists():
        raise FileNotFoundError(f"spaces.parquet не найден: {spaces_parquet}")

    manifest = load_manifest(manifest_path)
    spaces_df = pd.read_parquet(spaces_parquet)

    # Проверяем, что контракт данных соблюдён
    required_cols = [
        "space",
        "card_type",
        "groups",
        "groups_count",
        "general_light_entity",
        "ms_sensors_by_group",
    ]
    for c in required_cols:
        if c not in spaces_df.columns:
            raise ValueError(f"В spaces.parquet нет обязательной колонки: '{c}'")

    blocks: List[str] = []
    report: Dict[str, Dict] = {}

    for _, row in spaces_df.iterrows():
        space = str(row["space"])
        card_type = str(row["card_type"])
        groups = list(row["groups"])
        groups_count = int(row["groups_count"]) if not pd.isna(row["groups_count"]) else len(groups)
        general_light_entity = str(row["general_light_entity"])

        ms_by_group = row.get("ms_sensors_by_group", [])
        ms_sensors_by_group = list(ms_by_group) if ms_by_group is not None else []

        used_type, used_variant, ref, reason = pick_variant(manifest, card_type, groups_count)
        template_text = load_template_text(templates_dir, ref)

        rendered, warnings = render_placeholders(
            template_text=template_text,
            space=space,
            general_light_entity=general_light_entity,
            groups=groups,
            ms_sensors_by_group=ms_sensors_by_group,
        )

        blocks.append("{{\n" + rendered.rstrip() + "\n}}\n")

        report[space] = {
            "card_type": card_type,
            "groups_count": groups_count,
            "selected": {
                "used_card_type": used_type,
                "used_variant": used_variant,
                "template_file": ref.file,
                "reason": reason,
            },
            "warnings": warnings,
        }

    output_txt.parent.mkdir(parents=True, exist_ok=True)
    report_json.parent.mkdir(parents=True, exist_ok=True)

    output_txt.write_text("\n".join(blocks), encoding="utf-8")
    report_json.write_text(
        json.dumps(
            {
                "version": __version__,
                "spaces": len(report),
                "output": str(output_txt),
                "manifest": str(manifest_path),
                "templates_dir": str(templates_dir),
                "report": report,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("OK: Lovelace cards generated")
    print(" - Output:", output_txt)
    print(" - Report:", report_json)


def main() -> None:
    """CLI обёртка для запуска из терминала или кнопкой в PyCharm."""
    parser = argparse.ArgumentParser(description="Generate Lovelace cards from normalized parquet + templates manifest.")
    parser.add_argument("--spaces", default=str(DEFAULT_SPACES_PARQUET), help="Path to spaces.parquet")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH), help="Path to templates/manifest.yaml")
    parser.add_argument("--templates", default=str(DEFAULT_TEMPLATES_DIR), help="Templates root dir")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_TXT), help="Output TXT file")
    parser.add_argument("--report", default=str(DEFAULT_REPORT_JSON), help="Output report JSON file")

    args = parser.parse_args()

    # Лог запуска
    print("\n=== Generate Lovelace Cards ===")
    print("Spaces   :", args.spaces)
    print("Manifest :", args.manifest)
    print("Templates:", args.templates)
    print("Output   :", args.out)
    print("Report   :", args.report)
    print()

    generate_cards(
        spaces_parquet=Path(args.spaces),
        manifest_path=Path(args.manifest),
        templates_dir=Path(args.templates),
        output_txt=Path(args.out),
        report_json=Path(args.report),
    )


if __name__ == "__main__":
    main()
