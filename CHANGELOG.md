# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.
This project follows Semantic Versioning.

---

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