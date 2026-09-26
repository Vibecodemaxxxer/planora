"""
main_window.py

Логика главного окна приложения. Внешний вид окна описан в файле
ui/main_window.ui (сделан в Qt Designer), а здесь живёт поведение:
переключение режимов, фильтры и заполнение списков задач данными из БД.

Разделение простое: .ui отвечает за "как выглядит", этот модуль — за
"что происходит". Поэтому при изменении внешнего вида в Qt Designer код
обычно менять не нужно — лишь бы не менялись objectName виджетов.
"""

from PyQt5 import uic
from PyQt5.QtCore import QDate, QSize, Qt, QTimer
from PyQt5.QtGui import QColor, QIcon, QKeySequence, QTextCharFormat
from PyQt5.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QShortcut,
)

from categories_dialog import CategoriesDialog
from constants import (
    APP_NAME,
    CALENDAR_DAY_BG,
    CALENDAR_HEADER_COLOR,
    CARD_MIN_HEIGHT,
    CATEGORY_FILTER_ALL,
    CONFIRM_DELETE_TASK_HEADER,
    CONFIRM_DELETE_TASK_TEXT,
    DATE_FORMAT_DB,
    DATE_FORMAT_DISPLAY,
    EMPTY_ALL_TASKS_TEXT,
    EMPTY_DAY_TASKS_TEXT,
    ICON_CALENDAR,
    ICON_CATEGORIES,
    ICON_LIST,
    ICON_NEW_TASK,
    ICON_SEARCH,
    ICON_SIZE,
    MAIN_WINDOW_MIN_HEIGHT,
    MAIN_WINDOW_MIN_WIDTH,
    MAIN_WINDOW_UI,
    MENU_DELETE_TASK,
    MENU_OPEN_TASK,
    MENU_TASK_DONE,
    MODE_ALL_TASKS_INDEX,
    MODE_CALENDAR_INDEX,
    SELECTED_DAY_LABEL_TEMPLATE,
    SHORTCUT_MODE_ALL_TASKS,
    SHORTCUT_MODE_CALENDAR,
    SHORTCUT_NEW_TASK,
    SHORTCUT_SEARCH,
)
from database import Database

# Модуль здесь напрямую не используется, но импорт нужен: календарь на
# форме "повышен" до класса TaskCalendar, и uic.loadUi() ищет этот класс,
# импортируя модуль по имени из XML. При обычном запуске он находится сам,
# а вот PyInstaller такую связь не видит — по коду ссылок нет — и при
# сборке модуль в .exe не попадает. Этот импорт делает зависимость явной.
from task_calendar import TaskCalendar  # noqa: F401
from task_card import TaskCard
from task_dialog import TaskDialog


class MainWindow(QMainWindow):
    """Главное окно Planora.

    Форма подгружается из .ui во время работы программы, поэтому все
    виджеты формы становятся атрибутами этого объекта: например, кнопка
    с objectName "newTaskButton" доступна как self.newTaskButton.
    """

    def __init__(self, database: Database, parent=None) -> None:
        super().__init__(parent)

        # Окно не создаёт базу само, а получает уже готовый объект
        # Database извне (из main.py). Так окно не зависит от того, где
        # лежит файл БД, и его проще переиспользовать.
        self._db = database

        # Категории, разложенные по id: {id: строка категории}. Нужны
        # карточкам задач (цвет полоски и название категории). Держим их
        # в словаре, чтобы не дёргать базу для каждой карточки отдельно.
        self._categories_by_id = {}

        # uic.loadUi(путь, self) читает XML формы и достраивает уже
        # созданный объект self: создаёт все виджеты формы и делает их
        # атрибутами self. Альтернатива (pyuic5) компилирует .ui в
        # .py-файл, но по решению проекта мы грузим формы напрямую.
        # Важно: класс должен наследоваться от того же типа, что и
        # корневой виджет формы (у нас это QMainWindow).
        uic.loadUi(MAIN_WINDOW_UI, self)

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)

        self._prepare_icons()
        self._prepare_calendar()
        self._connect_signals()
        self._reload_categories()

        # Стартуем в режиме "Календарь" с выбранным сегодняшним днём.
        self.calendarWidget.setSelectedDate(QDate.currentDate())
        self._switch_mode(MODE_CALENDAR_INDEX)

        self.refresh()

    # ------------------------------------------------------------------
    # Иконки
    # ------------------------------------------------------------------
    def _prepare_icons(self) -> None:
        """Расставляет иконки на кнопках главного окна.

        Иконки — это картинки из assets/icons, то есть тоже мультимедиа.
        В Qt Designer их обычно подключают через файл ресурсов .qrc, но
        мы грузим формы напрямую из .ui, поэтому проще и надёжнее
        назначить иконки кодом — и путь тогда один, из constants.py.
        """
        icon_size = QSize(ICON_SIZE, ICON_SIZE)

        buttons_with_icons = (
            (self.newTaskButton, ICON_NEW_TASK),
            (self.calendarModeButton, ICON_CALENDAR),
            (self.allTasksModeButton, ICON_LIST),
            (self.categoriesButton, ICON_CATEGORIES),
        )
        for button, icon_path in buttons_with_icons:
            button.setIcon(QIcon(icon_path))
            button.setIconSize(icon_size)

        # Лупа внутри поля поиска. addAction вставляет значок прямо
        # в поле и сам отодвигает текст, чтобы он не налезал на иконку.
        self.searchLineEdit.addAction(
            QIcon(ICON_SEARCH), QLineEdit.LeadingPosition
        )

        # Иконка самого окна — видна в заголовке и на панели задач.
        self.setWindowIcon(QIcon(ICON_CALENDAR))

    # ------------------------------------------------------------------
    # Настройка календаря
    # ------------------------------------------------------------------
    def _prepare_calendar(self) -> None:
        """Донастраивает календарь.

        Сами дни рисует класс TaskCalendar (см. task_calendar.py), а
        здесь остаётся строка с названиями дней недели: её Qt рисует
        сам, и цвет ей задаётся форматом текста.
        """
        header_format = QTextCharFormat()
        header_format.setForeground(QColor(CALENDAR_HEADER_COLOR))
        header_format.setBackground(QColor(CALENDAR_DAY_BG))
        self.calendarWidget.setHeaderTextFormat(header_format)

        # Названия выходных Qt по умолчанию красит красным, а красный
        # в нашей палитре означает "просрочено". Формат дня недели
        # действует и на подпись в шапке, поэтому переопределяем его.
        for weekday in (Qt.Saturday, Qt.Sunday):
            self.calendarWidget.setWeekdayTextFormat(weekday, header_format)

    # ------------------------------------------------------------------
    # Подключение сигналов
    # ------------------------------------------------------------------
    def _connect_signals(self) -> None:
        """Связывает сигналы виджетов со слотами (методами) окна.

        Сигнал — это оповещение, которое виджет рассылает, когда с ним
        что-то произошло (нажали кнопку, изменился текст). Слот — обычный
        метод, который на это оповещение реагирует. Строка вида
        widget.signal.connect(self.method) читается как "когда произойдёт
        signal, вызови self.method". Опрашивать виджеты в цикле не нужно:
        Qt вызовет метод сам.
        """
        # Кнопки-режимы в боковой панели. lambda нужна потому, что
        # clicked передаёт слоту свой параметр (состояние checked), а нам
        # нужно передать номер режима.
        self.calendarModeButton.clicked.connect(
            lambda: self._switch_mode(MODE_CALENDAR_INDEX)
        )
        self.allTasksModeButton.clicked.connect(
            lambda: self._switch_mode(MODE_ALL_TASKS_INDEX)
        )

        # Клик по дню в календаре — обновить список задач этого дня.
        self.calendarWidget.selectionChanged.connect(self._refresh_day_tasks)

        # Поиск и фильтр по категории в режиме "Все задачи".
        # textChanged срабатывает на каждый введённый символ, поэтому
        # список фильтруется сразу, без отдельной кнопки "Найти".
        self.searchLineEdit.textChanged.connect(self._refresh_all_tasks)
        self.categoryFilterComboBox.currentIndexChanged.connect(
            self._refresh_all_tasks
        )

        # Создание новой задачи. lambda нужна по той же причине, что и
        # выше: clicked передаёт слоту свой аргумент, а _open_task_dialog
        # ждёт id задачи — для новой задачи это None.
        self.newTaskButton.clicked.connect(lambda: self._open_task_dialog())

        self.categoriesButton.clicked.connect(self._open_categories_dialog)

        self._create_shortcuts()

    def _create_shortcuts(self) -> None:
        """Создаёт горячие клавиши окна.

        QShortcut связывает сочетание клавиш с методом. Первые четыре
        привязаны к самому окну (self), поэтому работают в любом режиме.
        """
        shortcuts = {
            SHORTCUT_NEW_TASK: lambda: self._open_task_dialog(),
            SHORTCUT_SEARCH: self._focus_search,
            SHORTCUT_MODE_CALENDAR: (
                lambda: self._switch_mode(MODE_CALENDAR_INDEX)
            ),
            SHORTCUT_MODE_ALL_TASKS: (
                lambda: self._switch_mode(MODE_ALL_TASKS_INDEX)
            ),
        }
        for keys, handler in shortcuts.items():
            QShortcut(QKeySequence(keys), self).activated.connect(handler)

        # Delete и Enter должны работать только когда пользователь внутри
        # списка задач: иначе Delete срабатывал бы и при наборе текста
        # в поиске. Контекст WidgetShortcut как раз это и означает —
        # "только когда фокус в этом виджете".
        for task_list in (self.dayTasksListWidget, self.allTasksListWidget):
            for key, handler in (
                (Qt.Key_Delete, self._delete_selected_task),
                (Qt.Key_Return, self._open_selected_task),
                (Qt.Key_Enter, self._open_selected_task),
            ):
                shortcut = QShortcut(QKeySequence(key), task_list)
                shortcut.setContext(Qt.WidgetShortcut)
                shortcut.activated.connect(handler)

    def _focus_search(self) -> None:
        """Ctrl+F: переключиться на «Все задачи» и встать в поле поиска."""
        self._switch_mode(MODE_ALL_TASKS_INDEX)
        self.searchLineEdit.setFocus()
        self.searchLineEdit.selectAll()

    # ------------------------------------------------------------------
    # Режимы главного окна
    # ------------------------------------------------------------------
    def _switch_mode(self, mode_index: int) -> None:
        """Переключает страницу QStackedWidget и подсвечивает кнопку
        активного режима.

        QStackedWidget — это "стопка" страниц, из которой видна ровно
        одна; переключение не создаёт новых окон. Кнопки режимов помечены
        в Qt Designer как checkable, поэтому активную отмечаем вручную,
        а вторую снимаем — иначе обе остались бы нажатыми.
        """
        self.modeStackedWidget.setCurrentIndex(mode_index)
        self.calendarModeButton.setChecked(mode_index == MODE_CALENDAR_INDEX)
        self.allTasksModeButton.setChecked(mode_index == MODE_ALL_TASKS_INDEX)

    # ------------------------------------------------------------------
    # Фильтр по категории
    # ------------------------------------------------------------------
    def _reload_categories(self) -> None:
        """Перечитывает категории из БД: наполняет фильтр и словарь
        категорий по id.

        Вызывается при запуске и понадобится снова после того, как
        пользователь изменит категории в отдельном окне.

        В QComboBox каждый пункт хранит не только видимый текст, но и
        "скрытые данные" (второй аргумент addItem) — id категории. Так по
        выбору пользователя мы сразу получаем id и не сопоставляем
        названия строками. У пункта "Все категории" эти данные — None.
        """
        categories = self._db.get_categories()
        self._categories_by_id = {row["id"]: row for row in categories}

        # blockSignals временно выключает сигналы виджета: во время
        # перезаполнения currentIndexChanged срабатывал бы несколько раз
        # и зря перерисовывал список задач.
        self.categoryFilterComboBox.blockSignals(True)
        self.categoryFilterComboBox.clear()
        self.categoryFilterComboBox.addItem(CATEGORY_FILTER_ALL, None)
        for category in categories:
            self.categoryFilterComboBox.addItem(
                category["name"], category["id"]
            )
        self.categoryFilterComboBox.blockSignals(False)

    def _selected_category_id(self):
        """id выбранной в фильтре категории или None для "Все категории"."""
        return self.categoryFilterComboBox.currentData()

    # ------------------------------------------------------------------
    # Обновление списков задач
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Перечитывает данные из БД в оба списка.

        Единая точка обновления: после сохранения, изменения или
        удаления задачи достаточно вызвать refresh(), и окно целиком
        придёт в соответствие с базой.
        """
        self._mark_calendar_deadlines()
        self._refresh_day_tasks()
        self._refresh_all_tasks()

    def _mark_calendar_deadlines(self) -> None:
        """Собирает дни с дедлайнами и передаёт их календарю.

        Получается словарь {дата: есть ли среди задач просроченная} —
        по нему календарь рисует под днём серую или красную точку.
        Выполненные задачи не учитываем: напоминать о них не нужно.
        """
        deadline_days = {}
        today = QDate.currentDate()

        for task in self._db.get_tasks():
            if not task["deadline"] or task["is_done"]:
                continue

            deadline = QDate.fromString(task["deadline"], DATE_FORMAT_DB)
            is_overdue = deadline < today

            # Если на день попали и обычная, и просроченная задача,
            # день должен остаться красным — поэтому объединяем по "или".
            deadline_days[deadline] = (
                deadline_days.get(deadline, False) or is_overdue
            )

        self.calendarWidget.set_deadline_days(deadline_days)

    def _refresh_day_tasks(self) -> None:
        """Список задач с дедлайном на выбранный в календаре день."""
        selected_date = self.calendarWidget.selectedDate()

        # У QDate есть свой toString с шаблоном формата: в БД дата лежит
        # в ISO-виде (так она правильно сортируется как строка), а
        # пользователю показываем привычные дд.мм.гггг.
        self.selectedDayLabel.setText(
            SELECTED_DAY_LABEL_TEMPLATE.format(
                selected_date.toString(DATE_FORMAT_DISPLAY)
            )
        )

        tasks = self._db.get_tasks_by_date(
            selected_date.toString(DATE_FORMAT_DB)
        )
        self._fill_task_list(
            self.dayTasksListWidget, tasks, EMPTY_DAY_TASKS_TEXT
        )

    def _refresh_all_tasks(self) -> None:
        """Список всех задач с учётом поиска и фильтра по категории."""
        tasks = self._filtered_tasks()
        self._fill_task_list(
            self.allTasksListWidget, tasks, EMPTY_ALL_TASKS_TEXT
        )

    def _filtered_tasks(self) -> list:
        """Отбирает задачи по строке поиска и выбранной категории.

        Фильтруем в Python, а не в SQL: задач в учебном приложении
        немного, зато условия читаются проще, чем склеенный из кусков
        SQL-запрос.
        """
        search_text = self.searchLineEdit.text().strip().lower()
        category_id = self._selected_category_id()

        result = []
        for task in self._db.get_tasks():
            if category_id is not None and task["category_id"] != category_id:
                continue
            if search_text and search_text not in task["title"].lower():
                continue
            result.append(task)
        return result

    # ------------------------------------------------------------------
    # Наполнение QListWidget
    # ------------------------------------------------------------------
    def _fill_task_list(
        self, list_widget: QListWidget, tasks: list, empty_text: str
    ) -> None:
        """Очищает список и заново наполняет его карточками задач."""
        list_widget.clear()

        if not tasks:
            # Пункт-заглушка: делаем его невыбираемым, чтобы он не вёл
            # себя как настоящая задача (нельзя выделить и удалить).
            placeholder = QListWidgetItem(empty_text)
            placeholder.setFlags(Qt.NoItemFlags)
            list_widget.addItem(placeholder)
            return

        for task in tasks:
            self._add_task_card(list_widget, task)

    def _add_task_card(self, list_widget: QListWidget, task) -> None:
        """Создаёт карточку задачи и вставляет её в список.

        Схема работы QListWidget с виджетами внутри: сначала создаётся
        обычный пустой пункт, потом ему через setItemWidget назначается
        наш виджет, который и рисуется вместо текста.
        """
        subtasks_done, subtasks_total = self._db.count_subtasks(task["id"])

        card = TaskCard(
            task,
            self._categories_by_id.get(task["category_id"]),
            subtasks_done,
            subtasks_total,
        )
        # Собственные сигналы карточки: она сообщает о нажатии галочки и
        # о двойном клике, а действует по ним окно.
        card.doneToggled.connect(self._on_task_done_toggled)
        card.openRequested.connect(self._open_task_dialog)
        card.clicked.connect(self._select_task)
        card.menuRequested.connect(self._show_task_menu)

        item = QListWidgetItem()

        # В пункте храним id задачи в "пользовательской роли". Роль — это
        # ячейка данных внутри пункта: в Qt.DisplayRole лежит видимый
        # текст, а Qt.UserRole свободна для наших собственных данных.
        # Благодаря этому по выбранному пункту мы всегда знаем, какую
        # задачу открыть или удалить.
        item.setData(Qt.UserRole, task["id"])

        # Пункт списка сам не знает, сколько места нужно вложенному
        # виджету, — размер нужно сообщить ему явно, иначе карточка
        # окажется обрезанной по высоте.
        card_size = card.sizeHint()
        item.setSizeHint(
            QSize(card_size.width(), max(card_size.height(), CARD_MIN_HEIGHT))
        )

        list_widget.addItem(item)
        list_widget.setItemWidget(item, card)

    # ------------------------------------------------------------------
    # Окно задачи
    # ------------------------------------------------------------------
    def _open_task_dialog(self, task_id: int = None) -> None:
        """Открывает окно задачи: без task_id — создание, с ним —
        редактирование.

        exec_() показывает диалог модально: главное окно на это время
        блокируется, а строка кода ждёт, пока пользователь не закроет
        диалог. Возвращает результат: QDialog.Accepted, если нажали
        «Сохранить» или «Удалить», и QDialog.Rejected при отмене.
        Поэтому списки перечитываем только в первом случае.
        """
        dialog = TaskDialog(self._db, task_id, self)
        if dialog.exec_() == QDialog.Accepted:
            self.refresh()

    def _open_categories_dialog(self) -> None:
        """Открывает окно категорий и перечитывает всё после закрытия.

        Категории могли переименовать, перекрасить или удалить, поэтому
        обновить нужно и фильтр, и карточки задач (на них цветная
        полоска категории).
        """
        dialog = CategoriesDialog(self._db, self)
        dialog.exec_()

        # Запоминаем выбранную категорию, чтобы фильтр не сбрасывался
        # на "Все категории" после перезаполнения списка.
        selected_category_id = self._selected_category_id()

        self._reload_categories()

        restored_index = self.categoryFilterComboBox.findData(
            selected_category_id
        )
        self.categoryFilterComboBox.setCurrentIndex(max(restored_index, 0))

        self.refresh()

    # ------------------------------------------------------------------
    # Выделение задачи, клавиатура и контекстное меню
    # ------------------------------------------------------------------
    def _current_task_list(self) -> QListWidget:
        """Список задач того режима, который открыт сейчас."""
        if self.modeStackedWidget.currentIndex() == MODE_CALENDAR_INDEX:
            return self.dayTasksListWidget
        return self.allTasksListWidget

    def _select_task(self, task_id: int) -> None:
        """Выделяет в текущем списке пункт с указанной задачей."""
        task_list = self._current_task_list()
        for row in range(task_list.count()):
            item = task_list.item(row)
            if item.data(Qt.UserRole) == task_id:
                task_list.setCurrentItem(item)
                # Фокус нужен, чтобы сразу работали Delete и Enter:
                # они привязаны к списку, а не к окну целиком.
                task_list.setFocus()
                return

    def _selected_task_id(self):
        """id выделенной задачи или None, если ничего не выделено."""
        item = self._current_task_list().currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _open_selected_task(self) -> None:
        """Enter: открыть выделенную задачу на редактирование."""
        task_id = self._selected_task_id()
        if task_id is not None:
            self._open_task_dialog(task_id)

    def _delete_selected_task(self) -> None:
        """Delete: удалить выделенную задачу после подтверждения."""
        task_id = self._selected_task_id()
        if task_id is None:
            return
        self._delete_task(task_id)

    def _delete_task(self, task_id: int) -> None:
        """Спрашивает подтверждение и удаляет задачу."""
        task = self._db.get_task(task_id)
        if task is None:
            return

        answer = QMessageBox.question(
            self,
            CONFIRM_DELETE_TASK_HEADER,
            CONFIRM_DELETE_TASK_TEXT.format(task["title"]),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self._db.delete_task(task_id)
        self.refresh()

    def _show_task_menu(self, task_id: int, global_position) -> None:
        """Контекстное меню карточки: открыть, выполнено, удалить.

        QMenu собирается заново на каждый правый клик — так пункт
        «Выполнено» показывает актуальное состояние задачи. exec_()
        показывает меню и ждёт выбора, возвращая выбранное действие
        (или None, если меню закрыли просто так).
        """
        task = self._db.get_task(task_id)
        if task is None:
            return

        self._select_task(task_id)

        menu = QMenu(self)
        open_action = menu.addAction(MENU_OPEN_TASK)

        done_action = menu.addAction(MENU_TASK_DONE)
        # Пункт-переключатель с галочкой, отражающей текущее состояние.
        done_action.setCheckable(True)
        done_action.setChecked(bool(task["is_done"]))

        menu.addSeparator()
        delete_action = menu.addAction(MENU_DELETE_TASK)

        chosen_action = menu.exec_(global_position)

        if chosen_action == open_action:
            self._open_task_dialog(task_id)
        elif chosen_action == done_action:
            self._db.set_task_done(task_id, not task["is_done"])
            self.refresh()
        elif chosen_action == delete_action:
            self._delete_task(task_id)

    # ------------------------------------------------------------------
    # Реакция на действия в карточке
    # ------------------------------------------------------------------
    def _on_task_done_toggled(self, task_id: int, is_done: bool) -> None:
        """Отмечает задачу выполненной или снимает отметку."""
        self._db.set_task_done(task_id, is_done)

        # Обновляем списки не сразу, а через очередь событий Qt.
        # refresh() пересоздаёт все карточки, то есть удаляет и ту, чей
        # чекбокс прямо сейчас обрабатывает нажатие. Удалять виджет
        # внутри его же обработчика нельзя — Qt после возврата продолжит
        # работать с уже несуществующим объектом, и приложение упадёт.
        # QTimer.singleShot(0, ...) откладывает вызов до момента, когда
        # обработка нажатия полностью закончится.
        QTimer.singleShot(0, self.refresh)
