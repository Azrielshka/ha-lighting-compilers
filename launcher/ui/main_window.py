"""
launcher/ui/main_window.py
------------------------------------------------------------
Главное окно Launcher v1.

Задача этого файла:
    - собрать базовый интерфейс launcher
    - показать поля конфигурации проекта
    - показать список операций
    - показать окно логов

Шаг 12 + hotfix:
    - поле Python Interpreter убрано из UI
    - Python определяется автоматически от Project Root
    - кнопки Browse... работают для Project Root и Excel File Path
    - при запуске launcher пытается автоматически заполнить стартовые пути
    - normalize_excel.py получает --excel из UI, если поле заполнено
    - если Excel File Path пустой, normalize_excel.py использует свой DEFAULT_EXCEL_PATH
    - Project Root и Excel File Path сохраняются между запусками в JSON config
    - во время выполнения операций элементы управления launcher блокируются
    - добавлена кнопка Clear Log
    - стартовые строки лога показываются сразу до запуска subprocess
    - отключение кнопок применяется сразу, без отложенных кликов
"""

# ------------------------------------------------------------
# Импорты стандартной библиотеки
# ------------------------------------------------------------
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------------
# Импорты Qt
# ------------------------------------------------------------
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QGroupBox,
    QSizePolicy,
    QMessageBox,
    QFileDialog,
)

# ------------------------------------------------------------
# Импорт сервисов launcher
# ------------------------------------------------------------
from launcher.services.process_runner import ProcessRunner
from launcher.services.config_store import ConfigStore


# ------------------------------------------------------------
# Главное окно launcher
# ------------------------------------------------------------
class LauncherWindow(QMainWindow):
    """
    Главное окно Launcher v1.

    Содержит:
        - верхнюю панель конфигурации
        - левую панель операций
        - правую/нижнюю часть с логом
    """

    def __init__(self):
        super().__init__()

        # ------------------------------------------------------------
        # Базовые настройки окна
        # ------------------------------------------------------------
        self.setWindowTitle("HA College Lighting — Launcher v1")
        self.resize(1100, 700)

        # ------------------------------------------------------------
        # Флаг состояния выполнения.
        #
        # Зачем нужен:
        #   позволяет понимать, что сейчас launcher выполняет
        #   subprocess/pipeline, и на это время нужно заблокировать UI.
        # ------------------------------------------------------------
        self.is_running = False

        # ------------------------------------------------------------
        # Сервис запуска CLI-процессов
        # ------------------------------------------------------------
        self.process_runner = ProcessRunner()

        # ------------------------------------------------------------
        # Сервис сохранения пользовательского конфига launcher
        #
        # Конфиг сохраняем рядом с launcher в папке launcher/config
        # Это удобно:
        #   - не зависит от конкретного ПК
        #   - переносится вместе с проектом
        #   - легко найти и удалить вручную при необходимости
        # ------------------------------------------------------------
        launcher_dir = Path(__file__).resolve().parents[1]
        self.config_store = ConfigStore(
            launcher_dir / "config" / "launcher_config.json"
        )

        # ------------------------------------------------------------
        # Карта операций launcher:
        # ключ — внутреннее имя операции
        # значение — относительный путь до скрипта проекта
        # ------------------------------------------------------------
        self.script_map = {
            "normalize": "scripts/normalize_excel.py",
            "lights": "scripts/generate_lights_groups.py",
            "general": "scripts/generate_general_groups.py",
            "floor": "scripts/generate_floor_groups.py",
            "lovelace": "scripts/generate_lovelace_cards_v2.py",
        }

        # ------------------------------------------------------------
        # Порядок шагов полного pipeline для Build All
        # ------------------------------------------------------------
        self.pipeline_order = [
            "normalize",
            "lights",
            "general",
            "floor",
            "lovelace",
        ]

        # ------------------------------------------------------------
        # Центральный виджет окна
        # ------------------------------------------------------------
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # ------------------------------------------------------------
        # Главный layout окна
        # ------------------------------------------------------------
        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)
        central_widget.setLayout(root_layout)

        # ------------------------------------------------------------
        # Верхний блок конфигурации
        # ------------------------------------------------------------
        config_group = self._build_config_group()
        root_layout.addWidget(config_group)

        # ------------------------------------------------------------
        # Нижний блок: операции + лог
        # ------------------------------------------------------------
        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)
        root_layout.addLayout(content_layout, stretch=1)

        operations_group = self._build_operations_group()
        log_group = self._build_log_group()

        content_layout.addWidget(operations_group, 0)
        content_layout.addWidget(log_group, 1)

        # ------------------------------------------------------------
        # Подключаем кнопки
        # ------------------------------------------------------------
        self._connect_signals()

        # ------------------------------------------------------------
        # Загружаем сохранённый config.
        #
        # Логика:
        #   1. если есть сохранённые пути — используем их
        #   2. если сохранённого config нет — используем startup defaults
        # ------------------------------------------------------------
        self._restore_saved_or_default_config()

        # ------------------------------------------------------------
        # Стартовые строки в лог
        # ------------------------------------------------------------
        self.append_log("Launcher UI initialized")
        self.append_log("Step 12: Clear Log button is enabled")
        self.append_log("Project Root and Excel File Path are saved between launches")
        self.append_log("Python is auto-detected from Project Root/.venv/Scripts/python.exe")
        self.append_log("Hotfix: immediate UI refresh before blocking subprocess execution")

        # ------------------------------------------------------------
        # Сразу применяем стартовый лог визуально
        # ------------------------------------------------------------
        self._flush_ui_updates()

    # ------------------------------------------------------------
    # Сборка верхнего блока конфигурации
    # ------------------------------------------------------------
    def _build_config_group(self) -> QGroupBox:
        """
        Создаёт блок с путями:
            - Project Root
            - Excel File Path
        """

        group = QGroupBox("Project Configuration")

        layout = QGridLayout()
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)
        group.setLayout(layout)

        # ------------------------------------------------------------
        # Поле: Project Root
        # ------------------------------------------------------------
        project_root_label = QLabel("Project Root:")
        self.project_root_input = QLineEdit()
        self.project_root_input.setPlaceholderText(
            "C:/Users/Andrey/PycharmProjects/ha-college-lighting"
        )
        self.project_root_browse_btn = QPushButton("Browse...")

        layout.addWidget(project_root_label, 0, 0)
        layout.addWidget(self.project_root_input, 0, 1)
        layout.addWidget(self.project_root_browse_btn, 0, 2)

        # ------------------------------------------------------------
        # Поле: Excel File Path
        # ------------------------------------------------------------
        excel_file_label = QLabel("Excel File Path:")
        self.excel_file_input = QLineEdit()
        self.excel_file_input.setPlaceholderText(
            "Leave empty to use normalize_excel.py default path"
        )
        self.excel_file_browse_btn = QPushButton("Browse...")

        layout.addWidget(excel_file_label, 1, 0)
        layout.addWidget(self.excel_file_input, 1, 1)
        layout.addWidget(self.excel_file_browse_btn, 1, 2)

        # ------------------------------------------------------------
        # Центральная колонка растягивается
        # ------------------------------------------------------------
        layout.setColumnStretch(1, 1)

        return group

    # ------------------------------------------------------------
    # Сборка левой панели операций
    # ------------------------------------------------------------
    def _build_operations_group(self) -> QGroupBox:
        """
        Создаёт блок с кнопками операций launcher.
        """

        group = QGroupBox("Operations")
        group.setMinimumWidth(260)
        group.setMaximumWidth(320)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        group.setLayout(layout)

        self.btn_normalize = QPushButton("Normalize Excel")
        self.btn_lights = QPushButton("Generate Lights Groups")
        self.btn_general = QPushButton("Generate General Groups")
        self.btn_floor = QPushButton("Generate Floor Groups")
        self.btn_lovelace = QPushButton("Generate Lovelace Cards")
        self.btn_build_all = QPushButton("Build All")
        self.btn_clear_log = QPushButton("Clear Log")

        layout.addWidget(self.btn_normalize)
        layout.addWidget(self.btn_lights)
        layout.addWidget(self.btn_general)
        layout.addWidget(self.btn_floor)
        layout.addWidget(self.btn_lovelace)

        layout.addSpacing(12)
        layout.addWidget(self.btn_build_all)
        layout.addWidget(self.btn_clear_log)

        layout.addStretch(1)

        return group

    # ------------------------------------------------------------
    # Сборка области логов
    # ------------------------------------------------------------
    def _build_log_group(self) -> QGroupBox:
        """
        Создаёт окно логов.
        """

        group = QGroupBox("Execution Log")

        layout = QVBoxLayout()
        group.setLayout(layout)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText(
            "Execution logs will appear here..."
        )
        self.log_output.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )

        layout.addWidget(self.log_output)

        return group

    # ------------------------------------------------------------
    # Подключение кнопок к обработчикам
    # ------------------------------------------------------------
    def _connect_signals(self) -> None:
        """
        Подключает кнопки launcher к соответствующим методам.
        """

        # ------------------------------------------------------------
        # Кнопки выбора путей
        # ------------------------------------------------------------
        self.project_root_browse_btn.clicked.connect(self._browse_project_root)
        self.excel_file_browse_btn.clicked.connect(self._browse_excel_file)

        # ------------------------------------------------------------
        # Автосохранение полей при ручном редактировании.
        # ------------------------------------------------------------
        self.project_root_input.editingFinished.connect(self._save_current_config)
        self.excel_file_input.editingFinished.connect(self._save_current_config)

        # ------------------------------------------------------------
        # Кнопки операций pipeline
        # ------------------------------------------------------------
        self.btn_normalize.clicked.connect(
            lambda: self._run_single_operation("normalize")
        )
        self.btn_lights.clicked.connect(
            lambda: self._run_single_operation("lights")
        )
        self.btn_general.clicked.connect(
            lambda: self._run_single_operation("general")
        )
        self.btn_floor.clicked.connect(
            lambda: self._run_single_operation("floor")
        )
        self.btn_lovelace.clicked.connect(
            lambda: self._run_single_operation("lovelace")
        )
        self.btn_build_all.clicked.connect(self._run_build_all)

        # ------------------------------------------------------------
        # Кнопка очистки лога
        # ------------------------------------------------------------
        self.btn_clear_log.clicked.connect(self._clear_log)

    # ------------------------------------------------------------
    # Очистка окна логов
    # ------------------------------------------------------------
    def _clear_log(self) -> None:
        """
        Полностью очищает окно логов и добавляет новую стартовую строку.

        Зачем это нужно:
            - быстро начать новый тест с чистого лога
            - упростить чтение актуального результата
        """

        self.log_output.clear()
        self.append_log("Execution log cleared")
        self._flush_ui_updates()

    # ------------------------------------------------------------
    # Принудительное обновление GUI без обработки новых кликов
    # ------------------------------------------------------------
    def _flush_ui_updates(self) -> None:
        """
        Заставляет Qt применить изменения интерфейса сразу.

        Зачем это нужно:
            - показать новые строки лога до запуска subprocess
            - реально применить disabled-состояние кнопок до блокирующего вызова
            - не дать накопившимся кликам пользователя выполниться позже

        Важно:
            ExcludeUserInputEvents позволяет обновить интерфейс,
            но не обрабатывать новые пользовательские клики/кнопки.
        """

        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    # ------------------------------------------------------------
    # Переключение состояния UI на время выполнения
    # ------------------------------------------------------------
    def _set_running_state(self, is_running: bool) -> None:
        """
        Блокирует или разблокирует элементы управления launcher.

        Зачем это нужно:
            - не дать пользователю повторно запускать операции
            - не дать менять пути во время активного запуска
            - явно показывать, что launcher сейчас занят
        """

        self.is_running = is_running

        # ------------------------------------------------------------
        # Поля ввода путей
        # ------------------------------------------------------------
        self.project_root_input.setEnabled(not is_running)
        self.excel_file_input.setEnabled(not is_running)

        # ------------------------------------------------------------
        # Кнопки выбора путей
        # ------------------------------------------------------------
        self.project_root_browse_btn.setEnabled(not is_running)
        self.excel_file_browse_btn.setEnabled(not is_running)

        # ------------------------------------------------------------
        # Кнопки запуска операций
        # ------------------------------------------------------------
        self.btn_normalize.setEnabled(not is_running)
        self.btn_lights.setEnabled(not is_running)
        self.btn_general.setEnabled(not is_running)
        self.btn_floor.setEnabled(not is_running)
        self.btn_lovelace.setEnabled(not is_running)
        self.btn_build_all.setEnabled(not is_running)

        # ------------------------------------------------------------
        # Clear Log тоже блокируем на время выполнения,
        # чтобы пользователь не стёр лог посреди активного процесса.
        # ------------------------------------------------------------
        self.btn_clear_log.setEnabled(not is_running)

    # ------------------------------------------------------------
    # Восстановление сохранённого config или startup defaults
    # ------------------------------------------------------------
    def _restore_saved_or_default_config(self) -> None:
        """
        Восстанавливает поля launcher.

        Приоритет:
            1. сохранённый JSON config
            2. startup defaults
        """

        saved_config = self.config_store.load()

        project_root = str(saved_config.get("project_root", "")).strip()
        excel_file = str(saved_config.get("excel_file", "")).strip()

        loaded_from_saved = False

        if project_root and Path(project_root).exists():
            self.project_root_input.setText(project_root)
            loaded_from_saved = True
            self.append_log(f"Loaded saved Project Root: {project_root}")

        if excel_file and Path(excel_file).exists():
            self.excel_file_input.setText(excel_file)
            loaded_from_saved = True
            self.append_log(f"Loaded saved Excel file: {excel_file}")

        if not loaded_from_saved:
            self._apply_startup_defaults()

        self._save_current_config()

    # ------------------------------------------------------------
    # Сохранение текущих полей в JSON config
    # ------------------------------------------------------------
    def _save_current_config(self) -> None:
        """
        Сохраняет текущие значения полей launcher в JSON config.
        """

        data = {
            "project_root": self.project_root_input.text().strip(),
            "excel_file": self.excel_file_input.text().strip(),
        }

        self.config_store.save(data)

    # ------------------------------------------------------------
    # Автозаполнение стартовых путей при открытии launcher
    # ------------------------------------------------------------
    def _apply_startup_defaults(self) -> None:
        """
        Пытается автоматически заполнить поля Project Root и Excel File Path.
        """

        project_root = self._detect_project_root()

        if project_root is None:
            return

        self.project_root_input.setText(str(project_root))
        self.append_log(f"Startup default Project Root: {project_root}")

        excel_path = self._detect_default_excel_file(project_root)
        if excel_path is not None:
            self.excel_file_input.setText(str(excel_path))
            self.append_log(f"Startup default Excel file: {excel_path}")

    # ------------------------------------------------------------
    # Определение корня проекта относительно текущего файла launcher
    # ------------------------------------------------------------
    def _detect_project_root(self) -> Path | None:
        """
        Пытается определить корень проекта.

        Ожидаемая структура:
            <project_root>/launcher/ui/main_window.py

        Поэтому от текущего файла поднимаемся на два уровня вверх:
            ui -> launcher -> project_root
        """

        current_file = Path(__file__).resolve()
        candidate_root = current_file.parents[2]

        required_paths = [
            candidate_root / "launcher",
            candidate_root / "scripts",
            candidate_root / "data",
        ]

        if all(path.exists() for path in required_paths):
            return candidate_root

        return None

    # ------------------------------------------------------------
    # Поиск excel-файла по умолчанию в проекте
    # ------------------------------------------------------------
    def _detect_default_excel_file(self, project_root: Path) -> Path | None:
        """
        Пытается найти excel-файл по умолчанию в папке data.

        Приоритет:
            1. data/example.xlsx
            2. первый найденный *.xlsx в data
        """

        data_dir = project_root / "data"
        if not data_dir.exists():
            return None

        preferred_file = data_dir / "example.xlsx"
        if preferred_file.exists():
            return preferred_file

        excel_files = sorted(data_dir.glob("*.xlsx"))
        if excel_files:
            return excel_files[0]

        return None

    # ------------------------------------------------------------
    # Выбор папки Project Root
    # ------------------------------------------------------------
    def _browse_project_root(self) -> None:
        """
        Открывает диалог выбора папки проекта
        и записывает выбранный путь в поле Project Root.
        """

        current_value = self.project_root_input.text().strip()
        start_dir = current_value if current_value and Path(current_value).exists() else ""

        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Project Root",
            start_dir,
        )

        if not selected_dir:
            return

        self.project_root_input.setText(selected_dir)
        self.append_log(f"Project Root selected: {selected_dir}")
        self._save_current_config()
        self._flush_ui_updates()

    # ------------------------------------------------------------
    # Выбор Excel файла
    # ------------------------------------------------------------
    def _browse_excel_file(self) -> None:
        """
        Открывает диалог выбора Excel-файла
        и записывает выбранный путь в поле Excel File Path.
        """

        current_excel = self.excel_file_input.text().strip()
        project_root = self.project_root_input.text().strip()

        if current_excel and Path(current_excel).exists():
            start_dir = str(Path(current_excel).parent)
        elif project_root and Path(project_root).exists():
            start_dir = project_root
        else:
            start_dir = ""

        selected_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Excel File",
            start_dir,
            "Excel files (*.xlsx *.xls);;All files (*.*)",
        )

        if not selected_file:
            return

        self.excel_file_input.setText(selected_file)
        self.append_log(f"Excel file selected: {selected_file}")
        self._save_current_config()
        self._flush_ui_updates()

    # ------------------------------------------------------------
    # Получение текущих значений из полей
    # ------------------------------------------------------------
    def _get_current_config(self) -> dict:
        """
        Возвращает текущие значения полей.
        """

        project_root = self.project_root_input.text().strip()
        excel_file = self.excel_file_input.text().strip()

        return {
            "project_root": project_root,
            "excel_file": excel_file,
            "python_interpreter": self._resolve_python_interpreter(project_root),
        }

    # ------------------------------------------------------------
    # Автоматическое определение python.exe от Project Root
    # ------------------------------------------------------------
    def _resolve_python_interpreter(self, project_root: str) -> str:
        """
        Возвращает ожидаемый путь до python.exe внутри .venv проекта.

        Формат:
            <project_root>/.venv/Scripts/python.exe

        Если project_root пустой, возвращает пустую строку.
        """

        if not project_root:
            return ""

        python_path = Path(project_root) / ".venv" / "Scripts" / "python.exe"
        return str(python_path)

    # ------------------------------------------------------------
    # Формирование CLI-аргументов для конкретного скрипта
    # ------------------------------------------------------------
    def _build_script_args(self, operation_key: str, config: dict) -> list[str]:
        """
        Возвращает список CLI-аргументов для запуска конкретной операции.

        Логика шага 9:
            - только normalize умеет получать --excel из UI
            - если Excel File Path пустой, аргумент не передаём
              и normalize_excel.py использует свой DEFAULT_EXCEL_PATH
        """

        script_args: list[str] = []

        if operation_key == "normalize":
            excel_file = config["excel_file"].strip()

            if excel_file:
                script_args.extend(["--excel", excel_file])

        return script_args

    # ------------------------------------------------------------
    # Базовая валидация путей для запуска subprocess
    # ------------------------------------------------------------
    def _validate_runtime_config(self) -> dict | None:
        """
        Проверяет обязательные поля для реального запуска процесса.

        Возвращает словарь конфигурации, если всё корректно.
        Если есть ошибка — показывает сообщение и пишет в лог.
        """

        config = self._get_current_config()

        project_root = config["project_root"]
        python_interpreter = config["python_interpreter"]
        excel_file = config["excel_file"]

        if not project_root:
            self.append_log("ERROR: Project Root is empty")
            QMessageBox.warning(self, "Launcher v1", "Заполни поле Project Root.")
            self._flush_ui_updates()
            return None

        if not Path(project_root).exists():
            self.append_log(f"ERROR: Project Root does not exist: {project_root}")
            QMessageBox.warning(
                self,
                "Launcher v1",
                f"Папка Project Root не найдена:\n{project_root}",
            )
            self._flush_ui_updates()
            return None

        if not Path(python_interpreter).exists():
            self.append_log(
                f"ERROR: Auto-detected Python Interpreter does not exist: {python_interpreter}"
            )
            QMessageBox.warning(
                self,
                "Launcher v1",
                "Не найден python.exe в ожидаемом месте:\n"
                f"{python_interpreter}\n\n"
                "Проверь, что в корне проекта существует .venv.",
            )
            self._flush_ui_updates()
            return None

        if excel_file and not Path(excel_file).exists():
            self.append_log(f"ERROR: Excel File Path does not exist: {excel_file}")
            QMessageBox.warning(
                self,
                "Launcher v1",
                f"Excel файл не найден:\n{excel_file}",
            )
            self._flush_ui_updates()
            return None

        return config

    # ------------------------------------------------------------
    # Универсальный запуск одной операции
    # ------------------------------------------------------------
    def _run_single_operation(self, operation_key: str) -> None:
        """
        Запускает одну операцию launcher по ключу из self.script_map.
        """

        if self.is_running:
            self.append_log("Launcher is busy. Wait until the current operation finishes.")
            self._flush_ui_updates()
            return

        config = self._validate_runtime_config()
        if config is None:
            return

        script_relative_path = self.script_map.get(operation_key)
        if not script_relative_path:
            self.append_log(f"ERROR: unknown operation key: {operation_key}")
            self.append_log("-" * 60)
            self._flush_ui_updates()
            return

        script_args = self._build_script_args(operation_key, config)

        self._set_running_state(True)
        self.append_log("UI locked for operation execution")
        self._flush_ui_updates()

        try:
            self._execute_script(
                config=config,
                operation_key=operation_key,
                script_relative_path=script_relative_path,
                script_args=script_args,
            )
        finally:
            self._set_running_state(False)
            self.append_log("UI unlocked after operation execution")
            self._flush_ui_updates()

    # ------------------------------------------------------------
    # Полный pipeline Build All
    # ------------------------------------------------------------
    def _run_build_all(self) -> None:
        """
        Запускает все шаги pipeline последовательно.
        """

        if self.is_running:
            self.append_log("Launcher is busy. Wait until the current operation finishes.")
            self._flush_ui_updates()
            return

        config = self._validate_runtime_config()
        if config is None:
            return

        self._set_running_state(True)
        self.append_log("UI locked for Build All execution")

        try:
            self.append_log("Operation requested: Build All")
            self.append_log(f"Project Root: {config['project_root']}")
            self.append_log(
                f"Excel File Path: {config['excel_file'] or '<empty: normalize default will be used>'}"
            )
            self.append_log(
                f"Python Interpreter (auto): {config['python_interpreter']}"
            )
            self.append_log("Pipeline mode: sequential execution")
            self.append_log("-" * 60)

            # ------------------------------------------------------------
            # Показываем стартовые строки сразу и применяем disabled UI
            # до запуска первого шага pipeline
            # ------------------------------------------------------------
            self._flush_ui_updates()

            total_steps = len(self.pipeline_order)

            for index, operation_key in enumerate(self.pipeline_order, start=1):
                script_relative_path = self.script_map.get(operation_key)

                if not script_relative_path:
                    self.append_log(
                        f"ERROR: missing script mapping for operation: {operation_key}"
                    )
                    self.append_log("Pipeline aborted")
                    self.append_log("-" * 60)
                    self._flush_ui_updates()
                    return

                script_name = Path(script_relative_path).name
                script_args = self._build_script_args(operation_key, config)

                self.append_log(f"Build step {index}/{total_steps}: {script_name}")
                self._flush_ui_updates()

                result = self._execute_script(
                    config=config,
                    operation_key=operation_key,
                    script_relative_path=script_relative_path,
                    script_args=script_args,
                )

                if result is None:
                    self.append_log(f"Build step {index}/{total_steps} failed to start")
                    self.append_log("Pipeline aborted")
                    self.append_log("-" * 60)
                    self._flush_ui_updates()
                    return

                if result.returncode != 0:
                    self.append_log(
                        f"Pipeline stopped on failed step {index}/{total_steps}: {script_name}"
                    )
                    self.append_log("Build All completed with errors")
                    self.append_log("-" * 60)
                    self._flush_ui_updates()
                    return

            self.append_log("All pipeline steps completed successfully")
            self.append_log("Build All completed successfully")
            self.append_log("-" * 60)
            self._flush_ui_updates()

        finally:
            self._set_running_state(False)
            self.append_log("UI unlocked after Build All execution")
            self._flush_ui_updates()

    # ------------------------------------------------------------
    # Общий низкоуровневый запуск одного скрипта
    # ------------------------------------------------------------
    def _execute_script(
        self,
        config: dict,
        operation_key: str,
        script_relative_path: str,
        script_args: list[str] | None = None,
    ):
        """
        Выполняет один python-скрипт проекта через ProcessRunner
        и пишет подробный лог.

        Возвращает:
            result - если запуск состоялся
            None   - если процесс не удалось стартовать
        """

        script_name = Path(script_relative_path).name

        self.append_log(f"Operation requested: {script_name}")
        self.append_log(f"Project Root: {config['project_root']}")

        if operation_key == "normalize":
            if config["excel_file"]:
                self.append_log(f"Excel File Path: {config['excel_file']}")
                self.append_log("Normalize mode: Excel path overridden from UI")
            else:
                self.append_log("Excel File Path: <empty>")
                self.append_log("Normalize mode: using DEFAULT_EXCEL_PATH from normalize_excel.py")
        else:
            self.append_log(
                f"Excel File Path: {config['excel_file'] or '<not used by this script>'}"
            )

        self.append_log(
            f"Python Interpreter (auto): {config['python_interpreter']}"
        )
        self.append_log("Start subprocess execution")
        self._flush_ui_updates()

        try:
            result = self.process_runner.run_python_script(
                python_executable=config["python_interpreter"],
                project_root=config["project_root"],
                script_relative_path=script_relative_path,
                script_args=script_args,
            )
        except Exception as exc:
            self.append_log(f"ERROR: failed to start process: {exc}")
            self.append_log("-" * 60)
            self._flush_ui_updates()
            return None

        formatted_command = " ".join(f'"{part}"' for part in result.command)
        self.append_log(f"Command: {formatted_command}")

        if result.stdout.strip():
            self.append_log("STDOUT:")
            for line in result.stdout.splitlines():
                self.append_log(f"  {line}")

        if result.stderr.strip():
            self.append_log("STDERR:")
            for line in result.stderr.splitlines():
                self.append_log(f"  {line}")

        self.append_log(f"Exit code: {result.returncode}")

        if result.returncode == 0:
            self.append_log("Completed successfully")
        else:
            self.append_log("Completed with errors")

        self.append_log("-" * 60)
        self._flush_ui_updates()

        return result

    # ------------------------------------------------------------
    # Событие закрытия окна
    # ------------------------------------------------------------
    def closeEvent(self, event) -> None:
        """
        Перед закрытием окна сохраняет текущий config launcher.
        """

        self._save_current_config()
        super().closeEvent(event)

    # ------------------------------------------------------------
    # Добавление строки в лог с timestamp
    # ------------------------------------------------------------
    def append_log(self, message: str) -> None:
        """
        Добавляет строку в окно логов с текущим временем.
        """

        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {message}")