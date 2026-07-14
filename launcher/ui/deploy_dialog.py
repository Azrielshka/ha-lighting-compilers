"""
launcher/ui/deploy_dialog.py
------------------------------------------------------------
Диалог деплоя: параметры подключения, галочки целей, dry-run и LIVE.

Почему отдельным окном, а не полями в главном:
    - деплой — единственный шаг, который трогает живую систему на объекте;
      его стоит отделить визуально, чтобы не нажать случайно
    - параметров много (SSH + HA), в главном окне они бы всё загромоздили

Файлы едут по SFTP (проверено на живом HA), пространства — по WebSocket
(проверяется на объекте). Dry-run показывает план; LIVE отправляет.

⚠ Рестарт Home Assistant деплой НЕ делает (решение владельца). Об этом
напоминаем крупно.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

# Цели деплоя. Должны совпадать с scripts/_lib/ha_targets.py.
TARGETS: List[tuple] = [
    ("lights", "Группы света", "includes/packages/zm_*.yaml"),
    ("scripts", "Скрипты", "includes/scripts/zm_scripts.yaml"),
    ("automations", "Автоматизации", "includes/automations/zm_automations.yaml"),
    ("blueprints", "Blueprint'ы", "blueprints/automation/zone_manager/"),
    ("areas", "Пространства и этажи", "реестры HA (WebSocket)"),
]


class DeployDialog(QDialog):
    """Собирает параметры деплоя. Сам ничего не запускает — отдаёт их окну."""

    def __init__(self, parent=None, config: Dict = None):
        super().__init__(parent)

        self.setWindowTitle("Deploy — доставка конфигурации на Home Assistant")
        self.setMinimumWidth(620)

        config = config or {}

        # Результат: заполняется при нажатии кнопки.
        self.live = False
        self.accepted_targets: List[str] = []

        layout = QVBoxLayout()
        layout.setSpacing(12)
        self.setLayout(layout)

        layout.addWidget(self._build_targets_group(config))
        layout.addWidget(self._build_ssh_group(config))
        layout.addWidget(self._build_ha_group(config))
        layout.addWidget(self._build_warning())
        layout.addLayout(self._build_buttons())

    # ------------------------------------------------------------
    # Что отправлять
    # ------------------------------------------------------------
    def _build_targets_group(self, config: Dict) -> QGroupBox:
        group = QGroupBox("Что отправить")
        layout = QVBoxLayout()
        group.setLayout(layout)

        saved = config.get("deploy_targets")
        self.target_boxes: Dict[str, QCheckBox] = {}

        for key, title, where in TARGETS:
            box = QCheckBox(f"{title}  →  {where}")
            # По умолчанию всё включено: наладчик обычно льёт целиком.
            box.setChecked(key in saved if saved is not None else True)
            layout.addWidget(box)
            self.target_boxes[key] = box

        return group

    # ------------------------------------------------------------
    # SSH — файлы
    # ------------------------------------------------------------
    def _build_ssh_group(self, config: Dict) -> QGroupBox:
        group = QGroupBox("SSH — файлы (add-on «Advanced SSH & Web Terminal»)")
        layout = QGridLayout()
        layout.setHorizontalSpacing(10)
        group.setLayout(layout)

        layout.addWidget(QLabel("Хост:"), 0, 0)
        self.ssh_host = QLineEdit(config.get("ssh_host", ""))
        self.ssh_host.setPlaceholderText("homeassistant.local или IP")
        layout.addWidget(self.ssh_host, 0, 1, 1, 2)

        layout.addWidget(QLabel("Порт:"), 1, 0)
        self.ssh_port = QSpinBox()
        self.ssh_port.setRange(1, 65535)
        self.ssh_port.setValue(int(config.get("ssh_port", 22)))
        layout.addWidget(self.ssh_port, 1, 1)

        layout.addWidget(QLabel("Пользователь:"), 2, 0)
        self.ssh_user = QLineEdit(config.get("ssh_user", "root"))
        # При включённом SFTP аддон требует именно root.
        self.ssh_user.setPlaceholderText("root")
        layout.addWidget(self.ssh_user, 2, 1)

        layout.addWidget(QLabel("SSH-ключ:"), 3, 0)
        self.ssh_key = QLineEdit(config.get("ssh_key", ""))
        self.ssh_key.setPlaceholderText("путь к приватному ключу")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_key)
        layout.addWidget(self.ssh_key, 3, 1)
        layout.addWidget(browse, 3, 2)

        return group

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выберите приватный SSH-ключ")
        if path:
            self.ssh_key.setText(path)

    # ------------------------------------------------------------
    # HA — пространства
    # ------------------------------------------------------------
    def _build_ha_group(self, config: Dict) -> QGroupBox:
        group = QGroupBox("Home Assistant — пространства и этажи (WebSocket)")
        layout = QGridLayout()
        layout.setHorizontalSpacing(10)
        group.setLayout(layout)

        layout.addWidget(QLabel("Адрес:"), 0, 0)
        self.ha_url = QLineEdit(config.get("ha_url", ""))
        self.ha_url.setPlaceholderText("http://homeassistant.local:8123")
        layout.addWidget(self.ha_url, 0, 1)

        layout.addWidget(QLabel("Токен:"), 1, 0)
        self.ha_token = QLineEdit(config.get("ha_token", ""))
        self.ha_token.setPlaceholderText("long-lived access token")
        self.ha_token.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.ha_token, 1, 1)

        hint = QLabel(
            "Профиль в HA → Security → Long-lived access tokens → Create token"
        )
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint, 2, 1)

        # Для объектов с самоподписанным https (Traefik default cert).
        # На локальном http:// не нужен и просто игнорируется.
        self.ha_insecure = QCheckBox("Не проверять TLS-сертификат (самоподписанный https)")
        self.ha_insecure.setChecked(bool(config.get("ha_insecure", False)))
        layout.addWidget(self.ha_insecure, 3, 1)

        return group

    # ------------------------------------------------------------
    # Предупреждение про рестарт
    # ------------------------------------------------------------
    def _build_warning(self) -> QLabel:
        label = QLabel(
            "⚠ Рестарт Home Assistant деплой НЕ делает — перезапустите вручную.\n"
            "   Без рестарта изменения не применятся."
        )
        label.setStyleSheet(
            "background: #fff3cd; color: #856404; padding: 8px; border-radius: 4px;"
        )
        return label

    # ------------------------------------------------------------
    # Кнопки
    # ------------------------------------------------------------
    def _build_buttons(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        dry = QPushButton("Показать план (dry-run)")
        dry.setDefault(True)
        dry.clicked.connect(self._on_dry_run)

        live = QPushButton("Отправить на HA (LIVE)")
        live.clicked.connect(self._on_live)

        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)

        layout.addWidget(dry)
        layout.addWidget(live)
        layout.addStretch(1)
        layout.addWidget(cancel)

        return layout

    def _selected_targets(self) -> List[str]:
        return [key for key, box in self.target_boxes.items() if box.isChecked()]

    def _on_dry_run(self) -> None:
        targets = self._selected_targets()

        if not targets:
            QMessageBox.warning(self, "Deploy", "Отметьте хотя бы одну цель.")
            return

        self.live = False
        self.accepted_targets = targets
        self.accept()

    def _on_live(self) -> None:
        targets = self._selected_targets()

        if not targets:
            QMessageBox.warning(self, "Deploy", "Отметьте хотя бы одну цель.")
            return

        # Деплой — единственный шаг, который меняет живую систему на объекте.
        # Спрашиваем явно, даже несмотря на то, что транспорт пока заготовка.
        titles = "\n".join(
            f"  • {t}" for k, t, _ in TARGETS if k in targets
        )
        answer = QMessageBox.question(
            self,
            "Отправить на Home Assistant?",
            f"Будет отправлено:\n\n{titles}\n\n"
            f"Файлы на HA будут перезаписаны.\n"
            f"Хост: {self.ssh_host.text() or '— не задан —'}\n\n"
            f"Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        self.live = True
        self.accepted_targets = targets
        self.accept()

    # ------------------------------------------------------------
    # Что вернуть главному окну
    # ------------------------------------------------------------
    def result_config(self) -> Dict:
        return {
            "deploy_targets": self.accepted_targets,
            "ssh_host": self.ssh_host.text().strip(),
            "ssh_port": self.ssh_port.value(),
            "ssh_user": self.ssh_user.text().strip(),
            "ssh_key": self.ssh_key.text().strip(),
            "ha_url": self.ha_url.text().strip(),
            "ha_token": self.ha_token.text().strip(),
            "ha_insecure": self.ha_insecure.isChecked(),
        }

    def script_args(self) -> List[str]:
        """Аргументы для scripts/deploy.py."""
        args: List[str] = ["--targets", *self.accepted_targets]

        if self.ssh_host.text().strip():
            args += ["--host", self.ssh_host.text().strip()]
        args += ["--port", str(self.ssh_port.value())]

        if self.ssh_user.text().strip():
            args += ["--user", self.ssh_user.text().strip()]
        if self.ssh_key.text().strip():
            args += ["--key", self.ssh_key.text().strip()]
        if self.ha_url.text().strip():
            args += ["--url", self.ha_url.text().strip()]
        if self.ha_token.text().strip():
            args += ["--token", self.ha_token.text().strip()]
        if self.ha_insecure.isChecked():
            args.append("--insecure")

        if self.live:
            args.append("--live")

        return args
