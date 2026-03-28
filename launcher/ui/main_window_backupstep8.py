"""
launcher/ui/main_window.py
------------------------------------------------------------
Главное окно Launcher v1.

Задача этого файла:
    - собрать базовый интерфейс launcher
    - показать поля конфигурации проекта
    - показать список операций
    - показать окно логов

Шаг 7:
    - поле Python Interpreter убрано из UI
    - Python определяется автоматически от Project Root
    - Build All и одиночные операции используют auto-detected python
    - кнопки Browse... работают для Project Root и Excel File Path
"""

# ------------------------------------------------------------
# Импорты стандартной библиотеки
# ------------------------------------------------------------
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------------
# Импорты Qt-виджетов
# ------------------------------------------------------------
from PySide6.QtWidgets import (
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
# Импорт сервиса запуска процессов
# ------------------------------------------------------------
from launcher.services.process_runner import ProcessRunner


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
        # Сервис запуска CLI-процессов
        # ------------------------------------------------------------
        self.process_runner = ProcessRunner()

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
        # Стартовые строки в лог
        # ------------------------------------------------------------
        self.append_log("Launcher UI initialized")
        self.append_log("Step 7: Browse buttons are enabled")
        self.append_log("Python is auto-detected from Project Root/.venv/Scripts/python.exe")

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
            "data/example.xlsx"
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

        layout.addWidget(self.btn_normalize)
        layout.addWidget(self.btn_lights)
        layout.addWidget(self.btn_general)
        layout.addWidget(self.btn_floor)
        layout.addWidget(self.btn_lovelace)

        layout.addSpacing(12)
        layout.addWidget(self.btn_build_all)

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
    # Выбор папки Project Root
    # ------------------------------------------------------------
    def _browse_project_root(self) -> None:
        """
        Открывает диалог выбора папки проекта
        и записывает выбранный путь в поле Project Root.
        """

        # ------------------------------------------------------------
        # Стартовая папка для диалога:
        # если в поле уже есть путь и он существует — открываем его,
        # иначе открываем домашнюю папку пользователя.
        # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # Выбор Excel файла
    # ------------------------------------------------------------
    def _browse_excel_file(self) -> None:
        """
        Открывает диалог выбора Excel-файла
        и записывает выбранный путь в поле Excel File Path.
        """

        # ------------------------------------------------------------
        # Стартовая папка для диалога:
        # 1. если уже указан существующий файл — открываем его папку
        # 2. иначе если указан Project Root — открываем его
        # 3. иначе системная папка по умолчанию
        # ------------------------------------------------------------
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

        if not project_root:
            self.append_log("ERROR: Project Root is empty")
            QMessageBox.warning(self, "Launcher v1", "Заполни поле Project Root.")
            return None

        if not Path(project_root).exists():
            self.append_log(f"ERROR: Project Root does not exist: {project_root}")
            QMessageBox.warning(
                self,
                "Launcher v1",
                f"Папка Project Root не найдена:\n{project_root}",
            )
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
            return None

        return config

    # ------------------------------------------------------------
    # Универсальный запуск одной операции
    # ------------------------------------------------------------
    def _run_single_operation(self, operation_key: str) -> None:
        """
        Запускает одну операцию launcher по ключу из self.script_map.

        Примеры operation_key:
            - normalize
            - lights
            - general
            - floor
            - lovelace
        """

        config = self._validate_runtime_config()
        if config is None:
            return

        script_relative_path = self.script_map.get(operation_key)
        if not script_relative_path:
            self.append_log(f"ERROR: unknown operation key: {operation_key}")
            self.append_log("-" * 60)
            return

        self._execute_script(
            config=config,
            script_relative_path=script_relative_path,
        )

    # ------------------------------------------------------------
    # Полный pipeline Build All
    # ------------------------------------------------------------
    def _run_build_all(self) -> None:
        """
        Запускает все шаги pipeline последовательно.

        Логика:
            1. проверяем конфиг
            2. запускаем шаги по self.pipeline_order
            3. если один шаг падает — останавливаем pipeline
            4. если все успешны — пишем общий успех
        """

        config = self._validate_runtime_config()
        if config is None:
            return

        self.append_log("Operation requested: Build All")
        self.append_log(f"Project Root: {config['project_root']}")
        self.append_log(f"Excel File Path: {config['excel_file'] or '<empty>'}")
        self.append_log(
            f"Python Interpreter (auto): {config['python_interpreter']}"
        )
        self.append_log("Pipeline mode: sequential execution")
        self.append_log("-" * 60)

        total_steps = len(self.pipeline_order)

        for index, operation_key in enumerate(self.pipeline_order, start=1):
            script_relative_path = self.script_map.get(operation_key)

            if not script_relative_path:
                self.append_log(
                    f"ERROR: missing script mapping for operation: {operation_key}"
                )
                self.append_log("Pipeline aborted")
                self.append_log("-" * 60)
                return

            script_name = Path(script_relative_path).name

            self.append_log(f"Build step {index}/{total_steps}: {script_name}")

            result = self._execute_script(
                config=config,
                script_relative_path=script_relative_path,
            )

            if result is None:
                self.append_log(f"Build step {index}/{total_steps} failed to start")
                self.append_log("Pipeline aborted")
                self.append_log("-" * 60)
                return

            if result.returncode != 0:
                self.append_log(
                    f"Pipeline stopped on failed step {index}/{total_steps}: {script_name}"
                )
                self.append_log("Build All completed with errors")
                self.append_log("-" * 60)
                return

        self.append_log("All pipeline steps completed successfully")
        self.append_log("Build All completed successfully")
        self.append_log("-" * 60)

    # ------------------------------------------------------------
    # Общий низкоуровневый запуск одного скрипта
    # ------------------------------------------------------------
    def _execute_script(self, config: dict, script_relative_path: str):
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
        self.append_log(f"Excel File Path: {config['excel_file'] or '<empty>'}")
        self.append_log(
            f"Python Interpreter (auto): {config['python_interpreter']}"
        )
        self.append_log("Start subprocess execution")

        try:
            result = self.process_runner.run_python_script(
                python_executable=config["python_interpreter"],
                project_root=config["project_root"],
                script_relative_path=script_relative_path,
            )
        except Exception as exc:
            self.append_log(f"ERROR: failed to start process: {exc}")
            self.append_log("-" * 60)
            return None

        # ------------------------------------------------------------
        # Для читаемого лога оборачиваем каждый аргумент команды в кавычки
        # Это не влияет на запуск, только улучшает отображение в логе.
        # ------------------------------------------------------------
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

        return result

    # ------------------------------------------------------------
    # Добавление строки в лог с timestamp
    # ------------------------------------------------------------
    def append_log(self, message: str) -> None:
        """
        Добавляет строку в окно логов с текущим временем.
        """

        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {message}")