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
from PyQt5.QtWidgets import QListWidget, QListWidgetItem, QMainWindow

from constants import (
    APP_NAME,
    CARD_MIN_HEIGHT,
    CATEGORY_FILTER_ALL,
    DATE_FORMAT_DB,
    DATE_FORMAT_DISPLAY,
    EMPTY_ALL_TASKS_TEXT,
    EMPTY_DAY_TASKS_TEXT,
    MAIN_WINDOW_MIN_HEIGHT,
    MAIN_WINDOW_MIN_WIDTH,
    MAIN_WINDOW_UI,
    MODE_ALL_TASKS_INDEX,
    MODE_CALENDAR_INDEX,
    SELECTED_DAY_LABEL_TEMPLATE,
)
from database import Database
from task_card import TaskCard


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

        self._connect_signals()
        self._reload_categories()

        # Стартуем в режиме "Календарь" с выбранным сегодняшним днём.
        self.calendarWidget.setSelectedDate(QDate.currentDate())
        self._switch_mode(MODE_CALENDAR_INDEX)

        self.refresh()

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

        # Кнопки "Новая задача" и "Категории" будут открывать свои
        # диалоги, когда те появятся (task_dialog.py, categories_dialog.py).

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
        self._refresh_day_tasks()
        self._refresh_all_tasks()

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
        # Собственный сигнал карточки: она сообщает о нажатии галочки,
        # а записывает изменение в базу окно.
        card.doneToggled.connect(self._on_task_done_toggled)

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
