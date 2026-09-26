"""
categories_dialog.py

Окно управления категориями: добавление, переименование, смена цвета и
удаление. Форма — ui/categories_dialog.ui из Qt Designer.

В отличие от окна задачи, здесь изменения пишутся в базу сразу: у каждой
кнопки одно законченное действие, и подтверждать его отдельной кнопкой
«Сохранить» было бы лишним шагом.
"""

import sqlite3

from PyQt5 import uic
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QColorDialog,
    QDialog,
    QInputDialog,
    QListWidgetItem,
    QMessageBox,
)

from constants import (
    CATEGORIES_DIALOG_UI,
    CATEGORY_CIRCLE_SIZE,
    COLOR_DIALOG_TITLE,
    CONFIRM_DELETE_CATEGORY_HEADER,
    CONFIRM_DELETE_CATEGORY_TEXT,
    ICON_CATEGORIES,
    ICON_SIZE,
    ICON_TRASH,
    INPUT_NEW_CATEGORY_HEADER,
    INPUT_NEW_CATEGORY_LABEL,
    INPUT_RENAME_CATEGORY_HEADER,
    INPUT_RENAME_CATEGORY_LABEL,
    NEW_CATEGORY_COLOR,
    WARNING_CATEGORY_EXISTS_HEADER,
    WARNING_CATEGORY_EXISTS_TEXT,
    WARNING_CATEGORY_HAS_TASKS_HEADER,
    WARNING_CATEGORY_HAS_TASKS_TEXT,
)
from database import Database


def make_color_icon(color_name: str) -> QIcon:
    """Рисует цветной кружок и возвращает его как значок для списка.

    QPixmap — картинка в памяти, QPainter — инструмент рисования по ней.
    Готовых цветных кружков у нас нет, поэтому рисуем сами: это дешевле,
    чем держать в проекте по картинке на каждый возможный цвет.
    """
    pixmap = QPixmap(CATEGORY_CIRCLE_SIZE, CATEGORY_CIRCLE_SIZE)

    # Новый QPixmap заполнен мусором, поэтому делаем фон прозрачным.
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)

    # Сглаживание: без него у кружка будут заметны ступеньки.
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color_name))   # чем заливаем
    painter.setPen(Qt.NoPen)               # без обводки
    painter.drawEllipse(0, 0, CATEGORY_CIRCLE_SIZE, CATEGORY_CIRCLE_SIZE)

    # Рисование обязательно завершить, иначе QPixmap останется занятым.
    painter.end()

    return QIcon(pixmap)


class CategoriesDialog(QDialog):
    """Окно списка категорий."""

    def __init__(self, database: Database, parent=None) -> None:
        super().__init__(parent)

        self._db = database

        uic.loadUi(CATEGORIES_DIALOG_UI, self)

        self.categoriesListWidget.setIconSize(
            QSize(CATEGORY_CIRCLE_SIZE, CATEGORY_CIRCLE_SIZE)
        )

        self.deleteCategoryButton.setIcon(QIcon(ICON_TRASH))
        self.deleteCategoryButton.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setWindowIcon(QIcon(ICON_CATEGORIES))

        self._connect_signals()
        self._refresh_categories_list()

    # ------------------------------------------------------------------
    # Сигналы
    # ------------------------------------------------------------------
    def _connect_signals(self) -> None:
        """Связывает кнопки окна с методами."""
        self.addCategoryButton.clicked.connect(self._add_category)
        self.changeColorButton.clicked.connect(self._change_color)
        self.renameCategoryButton.clicked.connect(self._rename_category)
        self.deleteCategoryButton.clicked.connect(self._delete_category)

        # accept(), а не reject(): по закрытию окна главное окно
        # перечитывает категории — они могли измениться.
        self.closeButton.clicked.connect(self.accept)

        # Двойной клик по категории — сразу смена цвета: самое частое
        # действие в этом окне.
        self.categoriesListWidget.itemDoubleClicked.connect(
            self._change_color
        )

    # ------------------------------------------------------------------
    # Список категорий
    # ------------------------------------------------------------------
    def _refresh_categories_list(self) -> None:
        """Перечитывает категории из базы в список."""
        self.categoriesListWidget.clear()

        for category in self._db.get_categories():
            item = QListWidgetItem(category["name"])
            item.setIcon(make_color_icon(category["color"]))

            # id категории храним в скрытых данных пункта — по нему
            # работают кнопки переименования, цвета и удаления.
            item.setData(Qt.UserRole, category["id"])
            self.categoriesListWidget.addItem(item)

    def _selected_category(self):
        """Выделенная категория из базы или None, если ничего не выбрано."""
        item = self.categoriesListWidget.currentItem()
        if item is None:
            return None

        category_id = item.data(Qt.UserRole)
        for category in self._db.get_categories():
            if category["id"] == category_id:
                return category
        return None

    # ------------------------------------------------------------------
    # Действия с категориями
    # ------------------------------------------------------------------
    def _add_category(self) -> None:
        """Добавляет категорию: название и цвет спрашиваем по очереди."""
        name = self._ask_category_name(
            INPUT_NEW_CATEGORY_HEADER, INPUT_NEW_CATEGORY_LABEL
        )
        if not name:
            return

        color = self._ask_color(NEW_CATEGORY_COLOR)
        if color is None:
            return

        try:
            self._db.add_category(name, color)
        except sqlite3.IntegrityError:
            # Столбец name объявлен UNIQUE, поэтому база сама не даст
            # создать одноимённую категорию — остаётся объяснить это
            # пользователю.
            self._warn_name_taken(name)
            return

        self._refresh_categories_list()

    def _rename_category(self) -> None:
        """Переименовывает выделенную категорию."""
        category = self._selected_category()
        if category is None:
            return

        new_name = self._ask_category_name(
            INPUT_RENAME_CATEGORY_HEADER,
            INPUT_RENAME_CATEGORY_LABEL,
            category["name"],
        )
        if not new_name or new_name == category["name"]:
            return

        try:
            self._db.rename_category(category["id"], new_name)
        except sqlite3.IntegrityError:
            self._warn_name_taken(new_name)
            return

        self._refresh_categories_list()

    def _change_color(self) -> None:
        """Меняет цвет выделенной категории."""
        category = self._selected_category()
        if category is None:
            return

        color = self._ask_color(category["color"])
        if color is None:
            return

        self._db.set_category_color(category["id"], color)
        self._refresh_categories_list()

    def _delete_category(self) -> None:
        """Удаляет категорию, если в ней нет задач."""
        category = self._selected_category()
        if category is None:
            return

        # По ТЗ категорию с задачами удалять нельзя: задачи остались бы
        # без категории, и пользователь этого не ожидает.
        if self._db.category_has_tasks(category["id"]):
            QMessageBox.warning(
                self,
                WARNING_CATEGORY_HAS_TASKS_HEADER,
                WARNING_CATEGORY_HAS_TASKS_TEXT.format(category["name"]),
            )
            return

        answer = QMessageBox.question(
            self,
            CONFIRM_DELETE_CATEGORY_HEADER,
            CONFIRM_DELETE_CATEGORY_TEXT.format(category["name"]),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self._db.delete_category(category["id"])
        self._refresh_categories_list()

    # ------------------------------------------------------------------
    # Стандартные диалоги-помощники
    # ------------------------------------------------------------------
    def _ask_category_name(self, header, label, current_name=""):
        """Спрашивает название категории через QInputDialog.

        Возвращает введённое название без лишних пробелов или None,
        если пользователь нажал «Отмена». Второе значение, которое
        возвращает getText, — признак нажатия «ОК».
        """
        name, is_accepted = QInputDialog.getText(
            self, header, label, text=current_name
        )
        if not is_accepted:
            return None
        return name.strip()

    def _ask_color(self, current_color):
        """Спрашивает цвет через стандартный QColorDialog.

        Возвращает цвет строкой вида "#6366f1" или None при отмене.
        Текущий цвет передаётся начальным, чтобы диалог открывался
        не на случайном значении.
        """
        color = QColorDialog.getColor(
            QColor(current_color), self, COLOR_DIALOG_TITLE
        )

        # Если нажали "Отмена", диалог возвращает недействительный цвет.
        if not color.isValid():
            return None

        # name() даёт строку "#rrggbb" — в таком виде цвет лежит в базе
        # и подставляется в стили.
        return color.name()

    def _warn_name_taken(self, name: str) -> None:
        """Сообщает, что категория с таким названием уже есть."""
        QMessageBox.warning(
            self,
            WARNING_CATEGORY_EXISTS_HEADER,
            WARNING_CATEGORY_EXISTS_TEXT.format(name),
        )
