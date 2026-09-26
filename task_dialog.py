"""
task_dialog.py

Окно создания и редактирования задачи. Форма — ui/task_dialog.ui из
Qt Designer, здесь только поведение.

Одно окно работает в двух режимах, режим задаётся параметром task_id:
  * task_id is None — создание новой задачи, кнопка «Удалить» скрыта;
  * task_id задан    — редактирование: поля заполняются из базы,
                       кнопка «Удалить» видна.

Два режима в одном классе, а не два похожих окна: набор полей и правила
проверки у них одинаковые, различий всего три строки.

Подзадачи во время работы окна хранятся в памяти (список self._subtasks)
и записываются в базу только при сохранении. Иначе «Отмена» отменяла бы
изменения полей, но оставляла бы добавленные пункты — неожиданно для
пользователя.
"""

from PyQt5 import uic
from PyQt5.QtCore import QDate, QEvent, QSize, Qt
from PyQt5.QtGui import QIcon, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QListWidgetItem,
    QMessageBox,
    QShortcut,
    QVBoxLayout,
)

from constants import (
    CONFIRM_DELETE_TASK_HEADER,
    CONFIRM_DELETE_TASK_TEXT,
    DATE_FORMAT_DB,
    DATE_FORMAT_DISPLAY,
    DEADLINE_NO_DATE,
    ICON_CALENDAR,
    ICON_IMAGE,
    ICON_SIZE,
    ICON_TRASH,
    IMAGE_DIALOG_TITLE,
    IMAGE_FILE_FILTER,
    IMAGE_VIEWER_MAX_SIZE,
    IMAGE_VIEWER_TITLE,
    NO_CATEGORY_TEXT,
    NO_DEADLINE_DATE,
    NO_IMAGE_TEXT,
    PRIORITIES,
    PRIORITY_MEDIUM,
    SUBTASKS_LIST_TOOLTIP,
    TASK_DIALOG_TITLE_EDIT,
    TASK_DIALOG_TITLE_NEW,
    TASK_DIALOG_UI,
    WARNING_BAD_IMAGE_HEADER,
    WARNING_BAD_IMAGE_TEXT,
    WARNING_NO_TITLE_HEADER,
    WARNING_NO_TITLE_TEXT,
)
from database import Database


class TaskDialog(QDialog):
    """Окно задачи: создание, редактирование и удаление."""

    def __init__(
        self, database: Database, task_id: int = None, parent=None
    ) -> None:
        super().__init__(parent)

        self._db = database

        # None означает "задачи ещё нет в базе" — режим создания.
        self._task_id = task_id

        # Путь к прикреплённой картинке (в базе хранится он же).
        self._image_path = None

        # Подзадачи в виде списка словарей {"text": ..., "is_done": ...}.
        # Порядок элементов списка — это и есть порядок пунктов на экране
        # и в базе (столбец position).
        self._subtasks = []

        uic.loadUi(TASK_DIALOG_UI, self)

        self._prepare_widgets()
        self._connect_signals()

        if self._task_id is None:
            self.setWindowTitle(TASK_DIALOG_TITLE_NEW)
            # Удалять ещё нечего — кнопку убираем.
            self.deleteButton.hide()
            self.deadlineDateEdit.setDate(QDate.currentDate())
            self.priorityComboBox.setCurrentText(PRIORITY_MEDIUM)
        else:
            self.setWindowTitle(TASK_DIALOG_TITLE_EDIT)
            self._load_task()

        self._show_image_preview()
        self._refresh_subtasks_list()

    # ------------------------------------------------------------------
    # Первоначальная настройка виджетов
    # ------------------------------------------------------------------
    def _prepare_widgets(self) -> None:
        """Наполняет выпадающие списки и настраивает поля.

        Списки приоритетов и категорий заполняются кодом, а не в
        Qt Designer: приоритеты берутся из constants.py (одно место
        правки), а категории пользователь меняет во время работы.
        """
        self.priorityComboBox.addItems(PRIORITIES)

        # Первый пункт — "без категории", у него в скрытых данных None.
        # Остальные пункты хранят id своей категории.
        self.categoryComboBox.addItem(NO_CATEGORY_TEXT, None)
        for category in self._db.get_categories():
            self.categoryComboBox.addItem(category["name"], category["id"])

        self._prepare_deadline_edit()

        # scaledContents в форме растягивал бы картинку на весь размер
        # метки, искажая пропорции. Выключаем: масштабировать будем сами,
        # с сохранением соотношения сторон.
        self.imagePreviewLabel.setScaledContents(False)
        self.imagePreviewLabel.setAlignment(Qt.AlignCenter)

        self.subtasksListWidget.setToolTip(SUBTASKS_LIST_TOOLTIP)

        # Иконки на кнопках: пути лежат в constants.py.
        icon_size = QSize(ICON_SIZE, ICON_SIZE)
        for button, icon_path in (
            (self.attachImageButton, ICON_IMAGE),
            (self.deleteButton, ICON_TRASH),
        ):
            button.setIcon(QIcon(icon_path))
            button.setIconSize(icon_size)

        self.setWindowIcon(QIcon(ICON_CALENDAR))

        # Фильтр событий: превью — обычный QLabel из формы, своего класса
        # у него нет, поэтому переопределить mouseDoubleClickEvent негде.
        # installEventFilter говорит Qt пропускать все события метки
        # через наш eventFilter() — там и поймаем двойной клик.
        self.imagePreviewLabel.installEventFilter(self)

    def _prepare_deadline_edit(self) -> None:
        """Настраивает поле срока так, чтобы оно умело быть пустым.

        QDateEdit не может быть пустым — в нём всегда какая-то дата.
        Приём такой: минимально допустимой датой объявляется заведомо
        "нерабочая" (2000-01-01), и для неё задаётся specialValueText —
        подпись, которую поле показывает вместо самой даты. Для
        пользователя это выглядит как значение «Без срока», а для кода
        служит признаком "срок не задан".
        """
        self.deadlineDateEdit.setDisplayFormat(DATE_FORMAT_DISPLAY)
        self.deadlineDateEdit.setMinimumDate(
            QDate.fromString(NO_DEADLINE_DATE, DATE_FORMAT_DB)
        )
        self.deadlineDateEdit.setSpecialValueText(DEADLINE_NO_DATE)

    def _connect_signals(self) -> None:
        """Связывает сигналы виджетов с методами окна."""
        self.addSubtaskButton.clicked.connect(self._add_subtask)

        # returnPressed — нажатие Enter в поле ввода. Добавлять пункт
        # с клавиатуры удобнее, чем каждый раз тянуться к кнопке.
        self.newSubtaskLineEdit.returnPressed.connect(self._add_subtask)

        # itemChanged срабатывает при любом изменении пункта списка,
        # в том числе при переключении его галочки.
        self.subtasksListWidget.itemChanged.connect(self._on_subtask_changed)

        self.attachImageButton.clicked.connect(self._choose_image)

        self.saveButton.clicked.connect(self._save_task)
        self.deleteButton.clicked.connect(self._delete_task)

        # reject() — штатный способ закрыть диалог с отказом. Того же
        # результата даёт клавиша Esc: QDialog обрабатывает её сам.
        self.cancelButton.clicked.connect(self.reject)

        # QShortcut — горячая клавиша. Контекст WidgetShortcut означает,
        # что она работает только когда фокус в списке подзадач, поэтому
        # Delete в поле ввода по-прежнему удаляет символы.
        delete_subtask_shortcut = QShortcut(
            QKeySequence(Qt.Key_Delete), self.subtasksListWidget
        )
        delete_subtask_shortcut.setContext(Qt.WidgetShortcut)
        delete_subtask_shortcut.activated.connect(self._delete_subtask)

    # ------------------------------------------------------------------
    # Загрузка существующей задачи в поля
    # ------------------------------------------------------------------
    def _load_task(self) -> None:
        """Заполняет поля окна данными задачи из базы."""
        task = self._db.get_task(self._task_id)
        if task is None:
            # Задачу могли удалить из другого окна — сюда попасть не
            # должны, но молча работать с пустотой тоже нельзя.
            self.reject()
            return

        self.titleLineEdit.setText(task["title"])
        self.descriptionTextEdit.setPlainText(task["description"] or "")

        if task["deadline"]:
            self.deadlineDateEdit.setDate(
                QDate.fromString(task["deadline"], DATE_FORMAT_DB)
            )
        else:
            # Минимальная дата = "Без срока" (см. _prepare_deadline_edit).
            self.deadlineDateEdit.setDate(self.deadlineDateEdit.minimumDate())

        self.priorityComboBox.setCurrentText(task["priority"])

        # findData ищет пункт по скрытым данным — по id категории.
        # Если категорию задачи удалили, findData вернёт -1, поэтому
        # подстраховываемся пунктом "без категории" (индекс 0).
        category_index = self.categoryComboBox.findData(task["category_id"])
        self.categoryComboBox.setCurrentIndex(max(category_index, 0))

        self._image_path = task["image_path"]

        # Подзадачи переносим из базы в список в памяти: дальше окно
        # работает только с ним.
        self._subtasks = [
            {"text": row["text"], "is_done": bool(row["is_done"])}
            for row in self._db.get_subtasks(self._task_id)
        ]

    # ------------------------------------------------------------------
    # Подзадачи
    # ------------------------------------------------------------------
    def _refresh_subtasks_list(self) -> None:
        """Перерисовывает список подзадач по данным из self._subtasks."""
        # Пока мы сами наполняем список, itemChanged срабатывал бы на
        # каждый добавленный пункт и портил бы данные, по которым мы
        # прямо сейчас строим этот список.
        self.subtasksListWidget.blockSignals(True)
        self.subtasksListWidget.clear()

        for subtask in self._subtasks:
            item = QListWidgetItem(subtask["text"])

            # Флаги пункта — это набор его возможностей. К обычным
            # (виден, выбирается) добавляем ItemIsUserCheckable, и Qt
            # сам рисует у пункта галочку.
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if subtask["is_done"] else Qt.Unchecked
            )
            self.subtasksListWidget.addItem(item)

        self.subtasksListWidget.blockSignals(False)

    def _add_subtask(self) -> None:
        """Добавляет пункт из поля ввода в конец списка подзадач."""
        text = self.newSubtaskLineEdit.text().strip()
        if not text:
            return  # пустые пункты не добавляем

        self._subtasks.append({"text": text, "is_done": False})
        self.newSubtaskLineEdit.clear()
        self._refresh_subtasks_list()

    def _delete_subtask(self) -> None:
        """Удаляет выделенный пункт подзадач (клавиша Delete)."""
        row = self.subtasksListWidget.currentRow()
        if row < 0:
            return  # ничего не выделено

        del self._subtasks[row]
        self._refresh_subtasks_list()

    def _on_subtask_changed(self, item: QListWidgetItem) -> None:
        """Переносит переключённую галочку пункта в данные в памяти.

        row(item) даёт номер пункта в списке, а он совпадает с индексом
        в self._subtasks — списки строятся в одном порядке.
        """
        row = self.subtasksListWidget.row(item)
        self._subtasks[row]["is_done"] = item.checkState() == Qt.Checked

    # ------------------------------------------------------------------
    # Картинка
    # ------------------------------------------------------------------
    def _choose_image(self) -> None:
        """Выбор картинки стандартным диалогом открытия файла."""
        # getOpenFileName возвращает пару: путь и выбранный фильтр.
        # Фильтр нам не нужен, поэтому второе значение игнорируем.
        path, _ = QFileDialog.getOpenFileName(
            self, IMAGE_DIALOG_TITLE, "", IMAGE_FILE_FILTER
        )
        if not path:
            return  # пользователь нажал "Отмена"

        self._image_path = path
        self._show_image_preview()

    def _show_image_preview(self) -> None:
        """Показывает превью прикреплённой картинки.

        В базе хранится путь к файлу, а не сам файл. Поэтому картинки
        может не оказаться на месте (файл удалили или переименовали) —
        этот случай нужно обработать, а не падать.
        """
        if not self._image_path:
            self.imagePreviewLabel.clear()
            self.imagePreviewLabel.setText(NO_IMAGE_TEXT)
            self.imagePreviewLabel.setToolTip("")
            return

        # QPixmap — картинка в памяти, готовая к показу на экране.
        pixmap = QPixmap(self._image_path)

        if pixmap.isNull():
            # Файл не картинка или не читается.
            QMessageBox.warning(
                self,
                WARNING_BAD_IMAGE_HEADER,
                WARNING_BAD_IMAGE_TEXT.format(self._image_path),
            )
            self._image_path = None
            self._show_image_preview()
            return

        # Уменьшаем картинку под размер метки: KeepAspectRatio не даёт
        # исказить пропорции, SmoothTransformation — сглаживает.
        self.imagePreviewLabel.setPixmap(
            pixmap.scaled(
                self.imagePreviewLabel.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )
        self.imagePreviewLabel.setToolTip(self._image_path)

    def eventFilter(self, watched_object, event) -> bool:
        """Ловит двойной клик по превью — показать картинку крупно.

        Метод вызывается Qt для событий тех виджетов, на которые мы
        подписались через installEventFilter. Возвращаемое значение —
        «событие обработано, дальше не передавать» (True) или «пусть
        идёт своим путём» (False). Здесь перехватываем только двойной
        клик по превью, всё остальное отдаём Qt обрабатывать как обычно.
        """
        is_preview_double_click = (
            watched_object is self.imagePreviewLabel
            and event.type() == QEvent.MouseButtonDblClick
        )
        if is_preview_double_click and self._image_path:
            self._show_image_full_size()
            return True

        return super().eventFilter(watched_object, event)

    def _show_image_full_size(self) -> None:
        """Открывает картинку в отдельном окне в полный размер."""
        pixmap = QPixmap(self._image_path)
        if pixmap.isNull():
            return

        # Очень большие картинки уменьшаем, чтобы окно не выходило
        # за границы экрана.
        if max(pixmap.width(), pixmap.height()) > IMAGE_VIEWER_MAX_SIZE:
            pixmap = pixmap.scaled(
                IMAGE_VIEWER_MAX_SIZE,
                IMAGE_VIEWER_MAX_SIZE,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )

        viewer = QDialog(self)
        viewer.setWindowTitle(IMAGE_VIEWER_TITLE)

        image_label = QLabel(viewer)
        image_label.setPixmap(pixmap)

        # Раскладка нужна, чтобы окно само подобрало размер под картинку.
        layout = QVBoxLayout(viewer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(image_label)

        viewer.exec_()

    # ------------------------------------------------------------------
    # Сохранение и удаление
    # ------------------------------------------------------------------
    def _save_task(self) -> None:
        """Проверяет поля и записывает задачу в базу."""
        title = self.titleLineEdit.text().strip()
        if not title:
            QMessageBox.warning(
                self, WARNING_NO_TITLE_HEADER, WARNING_NO_TITLE_TEXT
            )
            self.titleLineEdit.setFocus()
            return  # окно не закрываем, даём исправить

        fields = {
            "title": title,
            "description": self.descriptionTextEdit.toPlainText().strip(),
            "deadline": self._collect_deadline(),
            "priority": self.priorityComboBox.currentText(),
            "category_id": self.categoryComboBox.currentData(),
            "image_path": self._image_path,
        }

        if self._task_id is None:
            # Создание: add_task принимает поля по порядку, поэтому
            # распаковываем словарь по именам (**).
            self._task_id = self._db.add_task(**fields)
        else:
            self._db.update_task(self._task_id, **fields)

        self._save_subtasks()

        # accept() закрывает окно с результатом "принято" — по нему
        # главное окно понимает, что список задач надо обновить.
        self.accept()

    def _collect_deadline(self):
        """Срок в формате базы или None, если выбрано «Без срока»."""
        selected_date = self.deadlineDateEdit.date()
        if selected_date == self.deadlineDateEdit.minimumDate():
            return None
        return selected_date.toString(DATE_FORMAT_DB)

    def _save_subtasks(self) -> None:
        """Записывает список подзадач в базу.

        Старые пункты удаляются, новые пишутся заново — так порядок
        и галочки всегда совпадают с тем, что пользователь видел
        в окне (подробнее — в комментарии к Database.clear_subtasks).
        """
        self._db.clear_subtasks(self._task_id)
        for subtask in self._subtasks:
            self._db.add_subtask(
                self._task_id, subtask["text"], subtask["is_done"]
            )

    def _delete_task(self) -> None:
        """Удаляет задачу после подтверждения."""
        answer = QMessageBox.question(
            self,
            CONFIRM_DELETE_TASK_HEADER,
            CONFIRM_DELETE_TASK_TEXT.format(self.titleLineEdit.text()),
            QMessageBox.Yes | QMessageBox.No,
            # Кнопка по умолчанию — "Нет": случайное нажатие Enter
            # не должно удалять задачу.
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        # Подзадачи удалятся сами — ON DELETE CASCADE в схеме БД.
        self._db.delete_task(self._task_id)
        self.accept()
