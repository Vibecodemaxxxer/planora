"""
task_card.py

Карточка одной задачи — виджет, который вставляется в QListWidget вместо
обычной текстовой строки: цветная полоска категории, название, метка
состояния дедлайна, приоритет, прогресс по подзадачам и галочка
"выполнено".

Почему отдельный файл, а не часть main_window.py:
  1. Карточка используется в двух местах — в списке задач выбранного дня
     и в общем списке "Все задачи". Это самостоятельный элемент, а не
     часть конкретного окна.
  2. main_window.py отвечает за окно (режимы, фильтры, обновление
     данных). Если сложить туда ещё и сборку карточки, файл станет
     вдвое больше и смешает две разные задачи.

Почему карточка собирается кодом, а не в Qt Designer: карточек во время
работы создаются десятки — по одной на задачу, и в списке они появляются
и исчезают при каждом обновлении. Такой виджет удобнее собирать в цикле
кодом. Требование ТЗ "не меньше двух форм из Designer" при этом
выполняется: три окна приложения сделаны именно в Designer.
"""

from PyQt5.QtCore import QDate, QPoint, Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from constants import (
    CARD_COLOR_BAR_RADIUS,
    CARD_COLOR_BAR_WIDTH,
    CARD_MARGIN,
    CARD_MIN_HEIGHT,
    CARD_PROGRESS_HEIGHT,
    CARD_PROGRESS_WIDTH,
    CARD_SPACING,
    CARD_THUMBNAIL_SIZE,
    CARD_TOOLTIP_TEMPLATE,
    CATEGORY_COLOR_DEFAULT,
    DATE_FORMAT_DB,
    DEADLINE_DONE,
    DEADLINE_NO_DATE,
    DEADLINE_OVERDUE,
    DEADLINE_SOON_KEY,
    DEADLINE_SOON_TEMPLATE,
    DEADLINE_STATE_COLORS,
    DEADLINE_TODAY,
    DEADLINE_TOMORROW,
    DONE_CHECKBOX_TOOLTIP,
    NO_CATEGORY_TEXT,
    PRIORITY_COLORS,
    SUBTASKS_PROGRESS_TEMPLATE,
)


def deadline_state(deadline_iso, is_done):
    """Вычисляет состояние задачи по её сроку.

    Возвращает пару (текст метки, цвет). Состояние нигде не хранится
    в базе, а считается каждый раз заново — иначе "Сегодня" пришлось бы
    пересчитывать у всех задач при смене суток.

    Порядок проверок важен: выполненная задача считается выполненной
    независимо от срока, даже если срок уже прошёл.
    """
    if is_done:
        return DEADLINE_DONE, DEADLINE_STATE_COLORS[DEADLINE_DONE]

    if not deadline_iso:
        return DEADLINE_NO_DATE, DEADLINE_STATE_COLORS[DEADLINE_NO_DATE]

    deadline = QDate.fromString(deadline_iso, DATE_FORMAT_DB)

    # daysTo считает разницу в днях: отрицательная — срок в прошлом.
    days_left = QDate.currentDate().daysTo(deadline)

    if days_left < 0:
        return DEADLINE_OVERDUE, DEADLINE_STATE_COLORS[DEADLINE_OVERDUE]
    if days_left == 0:
        return DEADLINE_TODAY, DEADLINE_STATE_COLORS[DEADLINE_TODAY]
    if days_left == 1:
        return DEADLINE_TOMORROW, DEADLINE_STATE_COLORS[DEADLINE_TOMORROW]

    return (
        DEADLINE_SOON_TEMPLATE.format(days_left),
        DEADLINE_STATE_COLORS[DEADLINE_SOON_KEY],
    )


class TaskCard(QWidget):
    """Карточка задачи для списка.

    Карточка ничего не знает про базу данных: она только показывает
    переданные ей данные, а о нажатии галочки сообщает наружу сигналом
    doneToggled. Записывает изменение в БД главное окно. Так карточку
    можно вставить в любой список, не переписывая её логику.
    """

    # Собственные сигналы виджета. Объявляются на уровне класса, в
    # скобках — типы аргументов. Главное окно подключается к ним так же,
    # как к штатным сигналам Qt: card.doneToggled.connect(...).
    #
    # doneToggled   — нажали галочку: (id задачи, новое состояние).
    # openRequested — задачу просят открыть на редактирование: (id).
    # clicked       — по карточке щёлкнули левой кнопкой: (id).
    # menuRequested — правый клик: (id, точка на экране для меню).
    doneToggled = pyqtSignal(int, bool)
    openRequested = pyqtSignal(int)
    clicked = pyqtSignal(int)
    menuRequested = pyqtSignal(int, QPoint)

    def __init__(
        self, task, category, subtasks_done, subtasks_total, parent=None
    ) -> None:
        super().__init__(parent)

        # id нужен, чтобы карточка могла сказать, о какой именно задаче
        # идёт речь, когда пользователь нажмёт галочку.
        self._task_id = task["id"]

        # objectName даёт возможность обращаться к виджету из QSS
        # (правило "#taskCard { ... }") — понадобится при оформлении.
        self.setObjectName("taskCard")
        self.setMinimumHeight(CARD_MIN_HEIGHT)

        # Название категории показываем подсказкой при наведении: на
        # самой карточке категорию обозначает цветная полоска, а текст
        # занял бы место.
        category_name = category["name"] if category else NO_CATEGORY_TEXT
        self.setToolTip(CARD_TOOLTIP_TEMPLATE.format(category_name))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            CARD_MARGIN, CARD_MARGIN, CARD_MARGIN, CARD_MARGIN
        )
        layout.setSpacing(CARD_SPACING)

        layout.addWidget(self._create_color_bar(category))

        # Второй аргумент — коэффициент растяжения. Единица означает
        # "эта часть забирает всё свободное место по ширине", поэтому
        # метки срока и приоритета уезжают вправо, а галочка встаёт
        # у правого края карточки.
        layout.addLayout(
            self._create_content(task, subtasks_done, subtasks_total), 1
        )

        # Миниатюра появляется только у задач с прикреплённой картинкой.
        thumbnail = self._create_thumbnail(task)
        if thumbnail is not None:
            layout.addWidget(thumbnail)

        layout.addWidget(self._create_done_checkbox(task))

    @property
    def task_id(self) -> int:
        """id задачи, которую показывает карточка."""
        return self._task_id

    # ------------------------------------------------------------------
    # Составные части карточки
    # ------------------------------------------------------------------
    @staticmethod
    def _create_color_bar(category) -> QFrame:
        """Цветная вертикальная полоска категории слева.

        Цвет у каждой категории свой и берётся из базы, поэтому он
        задаётся прямо в коде через setStyleSheet, а не в общем файле
        style.qss — в нём один цвет пришлось бы прописать для всех.
        """
        color = category["color"] if category else CATEGORY_COLOR_DEFAULT

        color_bar = QFrame()
        color_bar.setObjectName("categoryColorBar")
        color_bar.setFixedWidth(CARD_COLOR_BAR_WIDTH)
        color_bar.setStyleSheet(
            f"background-color: {color};"
            f"border-radius: {CARD_COLOR_BAR_RADIUS}px;"
        )
        return color_bar

    def _create_content(
        self, task, subtasks_done, subtasks_total
    ) -> QVBoxLayout:
        """Центральная часть: строка с названием и строка прогресса."""
        content_layout = QVBoxLayout()
        content_layout.setSpacing(4)

        content_layout.addLayout(self._create_title_row(task))

        # Полоску прогресса добавляем только если у задачи есть
        # подзадачи: у задачи без них прогресс показывать нечем.
        if subtasks_total:
            # Выравнивание влево: без него полоска растянулась бы
            # на всю ширину карточки и перетягивала бы внимание.
            content_layout.addWidget(
                self._create_progress_bar(subtasks_done, subtasks_total),
                alignment=Qt.AlignLeft,
            )

        return content_layout

    def _create_title_row(self, task) -> QHBoxLayout:
        """Строка: название, метка дедлайна, приоритет."""
        title_row = QHBoxLayout()
        title_row.setSpacing(CARD_SPACING)

        title_row.addWidget(self._create_title_label(task))

        # addStretch вставляет "пружину": она забирает свободное место,
        # поэтому название прижимается влево, а метки — вправо.
        title_row.addStretch()

        title_row.addWidget(self._create_deadline_label(task))
        title_row.addWidget(self._create_priority_label(task))
        return title_row

    @staticmethod
    def _create_title_label(task) -> QLabel:
        """Название задачи. У выполненной — зачёркнутое."""
        title_label = QLabel(task["title"])
        title_label.setObjectName("taskTitleLabel")

        # QFont — шрифт виджета. Берём текущий шрифт метки и меняем в нём
        # только нужные свойства, чтобы не сбить размер, заданный темой.
        font = title_label.font()
        font.setBold(True)
        font.setStrikeOut(bool(task["is_done"]))
        title_label.setFont(font)
        return title_label

    @staticmethod
    def _create_deadline_label(task) -> QLabel:
        """Цветная метка состояния срока."""
        text, color = deadline_state(task["deadline"], task["is_done"])

        deadline_label = QLabel(text)
        deadline_label.setObjectName("deadlineLabel")
        deadline_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        return deadline_label

    @staticmethod
    def _create_priority_label(task) -> QLabel:
        """Приоритет задачи, окрашенный по своей важности."""
        priority = task["priority"]

        priority_label = QLabel(priority)
        priority_label.setObjectName("priorityLabel")

        # .get со значением по умолчанию: если в базе окажется
        # неизвестный приоритет, приложение не упадёт из-за KeyError.
        color = PRIORITY_COLORS.get(priority, CATEGORY_COLOR_DEFAULT)
        priority_label.setStyleSheet(f"color: {color};")
        return priority_label

    @staticmethod
    def _create_progress_bar(subtasks_done, subtasks_total) -> QProgressBar:
        """Полоска прогресса по подзадачам с подписью "2 из 5"."""
        progress_bar = QProgressBar()
        progress_bar.setObjectName("subtasksProgressBar")

        # Максимум — общее число подзадач, значение — выполненные.
        # Проценты Qt считает сам, но нам нужна подпись в штуках,
        # поэтому текст задаётся явно через setFormat.
        progress_bar.setMaximum(subtasks_total)
        progress_bar.setValue(subtasks_done)
        progress_bar.setFormat(
            SUBTASKS_PROGRESS_TEMPLATE.format(subtasks_done, subtasks_total)
        )
        progress_bar.setFixedHeight(CARD_PROGRESS_HEIGHT)
        progress_bar.setFixedWidth(CARD_PROGRESS_WIDTH)
        return progress_bar

    @staticmethod
    def _create_thumbnail(task):
        """Маленькое превью прикреплённой картинки или None.

        Возвращает None в двух случаях: картинки у задачи нет или файл
        не читается (его могли удалить или переименовать — в базе лежит
        только путь). Тогда карточка просто обходится без миниатюры.
        """
        if not task["image_path"]:
            return None

        pixmap = QPixmap(task["image_path"])
        if pixmap.isNull():
            return None

        thumbnail = QLabel()
        thumbnail.setObjectName("taskThumbnailLabel")
        thumbnail.setFixedSize(CARD_THUMBNAIL_SIZE, CARD_THUMBNAIL_SIZE)
        thumbnail.setAlignment(Qt.AlignCenter)
        thumbnail.setToolTip(task["image_path"])

        # KeepAspectRatioByExpanding заполняет квадрат целиком, обрезая
        # лишнее по длинной стороне: так миниатюры выглядят одинаково
        # ровно и у горизонтальных, и у вертикальных картинок.
        thumbnail.setPixmap(
            pixmap.scaled(
                CARD_THUMBNAIL_SIZE,
                CARD_THUMBNAIL_SIZE,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
        )
        return thumbnail

    def _create_done_checkbox(self, task) -> QCheckBox:
        """Галочка "выполнено" в правой части карточки."""
        done_checkbox = QCheckBox()
        done_checkbox.setObjectName("taskDoneCheckBox")
        done_checkbox.setToolTip(DONE_CHECKBOX_TOOLTIP)

        # Порядок важен: сначала выставляем состояние, и только потом
        # подключаем сигнал. Иначе setChecked при создании карточки сам
        # вызвал бы обработчик, и задача "переключилась" бы в базе без
        # участия пользователя.
        done_checkbox.setChecked(bool(task["is_done"]))
        done_checkbox.toggled.connect(self._on_done_toggled)
        return done_checkbox

    # ------------------------------------------------------------------
    # Мышь и обработка нажатия галочки
    # ------------------------------------------------------------------
    def _on_done_toggled(self, is_checked: bool) -> None:
        """Пересылает нажатие галочки наружу вместе с id задачи."""
        self.doneToggled.emit(self._task_id, is_checked)

    def mousePressEvent(self, event) -> None:
        """Одиночный клик по карточке — сообщить, что её выбрали.

        Карточка закрывает собой пункт списка, поэтому сам QListWidget
        щелчка не видит и выделение не переносится. Главное окно по этому
        сигналу выделяет нужный пункт — и тогда работают Delete и Enter.
        """
        self.clicked.emit(self._task_id)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        """Правый клик по карточке — попросить показать меню.

        Qt вызывает этот метод при правом щелчке (или нажатии клавиши
        вызова меню). Само меню собирает главное окно: там есть доступ
        к базе и к окну задачи. globalPos — точка в координатах экрана,
        именно она нужна меню, чтобы появиться под курсором.
        """
        self.menuRequested.emit(self._task_id, event.globalPos())

    def mouseDoubleClickEvent(self, event) -> None:
        """Двойной клик по карточке — открыть задачу на редактирование.

        Это переопределение обработчика события: Qt вызывает метод с
        таким именем у виджета, когда по нему дважды щёлкнули мышью.
        В отличие от сигнала, событие приходит виджету само, подключать
        ничего не нужно — достаточно определить метод с нужным именем.
        Сама карточка окно не открывает, а только сообщает о просьбе
        сигналом; открывает главное окно.
        """
        self.openRequested.emit(self._task_id)

        # Вызов метода базового класса — хорошая привычка: так остальная
        # штатная обработка события не теряется.
        super().mouseDoubleClickEvent(event)
