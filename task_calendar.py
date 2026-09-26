"""
task_calendar.py

Календарь с собственной отрисовкой дней.

Зачем понадобился свой класс. Обычный QCalendarWidget оформляется плохо:
внутри он собран из таблицы и служебных кнопок, цвета дней берёт из
палитры, и файл стилей до них почти не достаёт. Скруглить выделение
выбранного дня или нарисовать точку под днём с дедлайном через QSS
нельзя вообще.

Выход — переопределить paintCell(): этот метод Qt вызывает для каждой
клетки дня, передавая "кисть" (QPainter) и прямоугольник клетки. Что в
этом прямоугольнике нарисовать, решаем мы.

Как этот класс попадает на форму. В main_window.ui виджет календаря
"повышен" (promoted) до TaskCalendar: в XML формы указано, что вместо
QCalendarWidget нужно создать класс TaskCalendar из модуля
task_calendar. uic.loadUi при загрузке формы сам импортирует этот модуль
и подставляет наш класс. В Qt Designer то же самое делается правым
кликом по виджету -> "Преобразовать в...".
"""

from PyQt5.QtCore import QDate, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QCalendarWidget

from constants import (
    CALENDAR_CELL_MARGIN,
    CALENDAR_CELL_RADIUS,
    CALENDAR_DAY_BG,
    CALENDAR_DOT_COLOR,
    CALENDAR_DOT_OVERDUE_COLOR,
    CALENDAR_DOT_SIZE,
    CALENDAR_HEADER_COLOR,
    CALENDAR_OTHER_MONTH_COLOR,
    CALENDAR_SELECTION_COLOR,
    CALENDAR_TEXT_COLOR,
    CALENDAR_TODAY_BG,
)


class TaskCalendar(QCalendarWidget):
    """Календарь, который помечает дни с дедлайнами."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Дни с дедлайнами: {QDate: True, если среди задач есть
        # просроченная}. Данные приходят снаружи, сам календарь в базу
        # не ходит — как и карточка задачи.
        self._deadline_days = {}

        # Колонка с номерами недель — лишний шум.
        self.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)

        # Сетку не рисуем: разделение дней делают отступы.
        self.setGridVisible(False)

    def set_deadline_days(self, deadline_days: dict) -> None:
        """Задаёт дни, которые нужно пометить точкой.

        update() просит Qt перерисовать виджет — без него календарь
        остался бы с прежними точками до следующей перерисовки.
        """
        self._deadline_days = deadline_days
        self.update()

    # ------------------------------------------------------------------
    # Отрисовка одной клетки дня
    # ------------------------------------------------------------------
    def paintCell(self, painter: QPainter, rect, date: QDate) -> None:
        """Рисует одну клетку календаря.

        Порядок как у художника: сначала подложка, потом число, потом
        точка-отметка. save() и restore() сохраняют и возвращают
        настройки кисти — иначе наши цвета "утекли" бы в отрисовку
        соседних клеток.
        """
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        is_selected = date == self.selectedDate()
        is_today = date == QDate.currentDate()
        is_current_month = date.month() == self.monthShown()

        self._paint_background(painter, rect, is_selected, is_today)
        self._paint_day_number(
            painter, rect, date, is_selected, is_current_month
        )

        # У выбранного дня подложка тёмная, точка на ней не читается —
        # да и не нужна: задачи этого дня и так видны в списке справа.
        if date in self._deadline_days and not is_selected:
            self._paint_deadline_dot(
                painter, rect, self._deadline_days[date]
            )

        painter.restore()

    @staticmethod
    def _paint_background(painter, rect, is_selected, is_today) -> None:
        """Скруглённая подложка: тёмная у выбранного дня, светлая
        у сегодняшнего."""
        if not is_selected and not is_today:
            return

        color = CALENDAR_SELECTION_COLOR if is_selected else CALENDAR_TODAY_BG

        # QRectF — прямоугольник с дробными координатами: со сглаживанием
        # скруглённые углы на нём получаются аккуратнее, чем на целых.
        cell = QRectF(rect).adjusted(
            CALENDAR_CELL_MARGIN,
            CALENDAR_CELL_MARGIN,
            -CALENDAR_CELL_MARGIN,
            -CALENDAR_CELL_MARGIN,
        )

        painter.setPen(Qt.NoPen)               # без обводки
        painter.setBrush(QColor(color))        # заливка
        painter.drawRoundedRect(
            cell, CALENDAR_CELL_RADIUS, CALENDAR_CELL_RADIUS
        )

    def _paint_day_number(
        self, painter, rect, date, is_selected, is_current_month
    ) -> None:
        """Число дня: цвет зависит от того, что это за день."""
        if is_selected:
            color = CALENDAR_DAY_BG              # белым по тёмному
        elif not is_current_month:
            color = CALENDAR_OTHER_MONTH_COLOR   # соседний месяц — бледно
        elif date.dayOfWeek() in (6, 7):
            color = CALENDAR_HEADER_COLOR        # выходные — светлее
        else:
            color = CALENDAR_TEXT_COLOR

        font = painter.font()
        # День с задачами выделяем жирным — заметно даже без цвета.
        font.setBold(is_selected or date in self._deadline_days)
        painter.setFont(font)

        painter.setPen(QColor(color))

        # Число сдвигаем чуть вверх, чтобы под ним осталось место
        # для точки.
        painter.drawText(
            rect.adjusted(0, -CALENDAR_DOT_SIZE, 0, 0),
            Qt.AlignCenter,
            str(date.day()),
        )

    @staticmethod
    def _paint_deadline_dot(painter, rect, has_overdue: bool) -> None:
        """Точка под числом: есть задачи с дедлайном на этот день."""
        color = (
            CALENDAR_DOT_OVERDUE_COLOR if has_overdue else CALENDAR_DOT_COLOR
        )

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))

        # Точку ставим по центру по горизонтали и ближе к низу клетки.
        dot_x = rect.center().x() - CALENDAR_DOT_SIZE / 2
        dot_y = rect.bottom() - CALENDAR_DOT_SIZE - CALENDAR_CELL_MARGIN * 2
        painter.drawEllipse(
            QRectF(dot_x, dot_y, CALENDAR_DOT_SIZE, CALENDAR_DOT_SIZE)
        )
