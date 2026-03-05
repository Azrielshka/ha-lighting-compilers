# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.
This project follows Semantic Versioning.

---
## [2.0.2] - 2026-03-05

### Added
- Optional generation of technical room groups per floor in `generate_floor_groups.py`.
- New flag `GENERATE_TECH_GROUPS` to enable/disable technical floor groups.
- Canonical rule `TECHNICAL_CARD_TYPES` added to `scripts/_lib/canon.py`.

### Changed
- `generate_floor_groups.py` now reads `spaces.parquet` instead of `device_rows.parquet`.
- Floor grouping uses canonical `general_light_entity` values from normalized data.

## [2.0.1] - 2026-03-05

### Changed
- `generate_lights_groups.py` now reads normalized data from `data/normalized/device_rows.parquet` instead of Excel.
- Lamp entity generation moved to canonical rule `normalize_lamp_id_to_entity()` in `scripts/_lib/canon.py`.
- `generate_general_groups.py` refactored to read normalized data from `data/normalized/device_rows.parquet` instead of Excel.
- Output moved to `data/light_groups/lights_general_groups.yaml`.
- General light group IDs now follow canonical rule `<room_slug>_obshchii` (via `GENERAL_LIGHT_RULE`).
- `generate_floor_groups.py` refactored to read normalized data from `data/normalized/device_rows.parquet` instead of parsing `lights_general_groups.yaml`.
- Output moved to `data/light_groups/lights_floor_groups.yaml`.
- Floor groups now include canonical general room groups (`light.<room_slug>_obshchii`) built via `GENERAL_LIGHT_RULE`.
2) Команды в терминале PyCharm
### Added
- Shared naming rule `normalize_lamp_id_to_entity()` for consistent Home Assistant entity IDs across generators.

## [2.0.0] - 2026-03-05

### Added

- Introduced **data normalization layer** (`normalize_excel.py`).
- Added canonical dataset generation:
  - `data/normalized/device_rows.parquet`
  - `data/normalized/spaces.parquet`
  - `data/normalized/normalized_meta.json`
- Added parquet-based data pipeline for further generators.
- Added support for **template-based Lovelace card generation**.
- Implemented `manifest.yaml` + YAML template system ("Card Bestiary").
- Added automatic placeholder replacement in templates:
  - `[[HEADING]]`
  - `[[SPACE]]`
  - `[[GENERAL_LIGHT_ENTITY]]`
  - `[[ZONE_LIGHT_i]]`
  - `[[MS_SENSOR_i]]`
- Added `lovelace_cards_report.json` generation for debugging template selection.
- Added project `requirements.txt`.

---

### Changed

- Lovelace card generation now uses **normalized parquet data** instead of direct Excel parsing.
- Sensor entity naming updated: sensor.1_20_3 → sensor.ms_1_20_3

- Motion sensors now explicitly marked with `ms_` prefix.
- Normalizer now guarantees **unique motion sensors per zone**.
- Improved logging when running `normalize_excel.py`.

---

### Technical

- Added project-wide canonical rules in `scripts/_lib`:
  - `canon.py`
  - `naming.py`
  - `excel_schema.py`
- Added support for running scripts both via:
  - PyCharm Run button
  - CLI execution

---

### Notes

- `general_light_entity` naming remains: light.<room_slug>_obshchii

Example:
light.403_kabinet_medits_obshchii
light.404_lestnitsa_obshchi

- Motion sensors are generated as: sensor.ms_<id>

Example: sensor.ms_1_20_3

## [1.1.2] - 2026-03-03

### Fixed
- Fixed incorrect relative paths when running scripts from /scripts directory
- Implemented BASE_DIR project root resolution for all generators
- Resolved FileNotFoundError when executing via PyCharm

### Improved
- Updated transliteration logic to match Home Assistant slug rules
  - щ → shch
  - ц → ts
  - х → kh
- Reduced entity_id mismatches (~15% → 0%)

---

## [1.1.1] - 2026-03-03

### Attempted Fix
- Added BASE_DIR path resolution (contained structural error)

---

## [1.1.0] - 2026-03-03

### Added
- HA-compatible transliteration logic in generate_floor_groups
- Improved entity_id consistency

---

## [1.0.0] - 2026-01-14

### Initial Release
- generate_general_groups.py
- generate_lights_groups.py
- generate_floor_groups.py
- YAML generation from Excel table